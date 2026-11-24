import math
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import UTC, datetime

from app.schemas.search import RetrievedIssue, ScoreBreakdown, SearchFilters

EASY_LABELS = frozenset({"good first issue", "help wanted", "beginner"})


@dataclass
class RetrievalCandidate:
    id: int
    repo_full_name: str
    repo_owner: str
    repo_topics: list[str]
    primary_language: str | None
    program_tags: list[str]
    number: int
    title: str
    html_url: str
    labels: list[str]
    comments_count: int
    maintainer_activity_score: float
    github_updated_at: datetime
    snippet: str
    vector_rank: int | None = None
    fts_rank: int | None = None
    vector_score: float = 0.0
    fts_score: float = 0.0


def compute_rrf_score(
    vector_rank: int | None,
    fts_rank: int | None,
    k: int = 60,
    vector_weight: float = 0.6,
    fts_weight: float = 0.4,
) -> float:
    if k < 1:
        raise ValueError("k must be positive")
    if vector_rank is not None and vector_rank < 1:
        raise ValueError("vector_rank must be positive or None")
    if fts_rank is not None and fts_rank < 1:
        raise ValueError("fts_rank must be positive or None")
    return sum(
        weight / (k + rank)
        for weight, rank in ((vector_weight, vector_rank), (fts_weight, fts_rank))
        if rank is not None
    )


def compute_freshness_score(
    github_updated_at: datetime,
    now: datetime | None = None,
    half_life_days: float = 90.0,
) -> float:
    if half_life_days <= 0:
        raise ValueError("half_life_days must be positive")
    reference = _as_utc(now or datetime.now(UTC))
    updated = _as_utc(github_updated_at)
    age_days = max((reference - updated).total_seconds() / 86_400, 0.0)
    return math.exp(-math.log(2) * age_days / half_life_days)


def compute_experience_boost(labels: Sequence[str], experience_level: str) -> float:
    if experience_level not in {"beginner", "intermediate", "advanced"}:
        raise ValueError(f"Unknown experience level: {experience_level}")
    easy_issue = bool({label.strip().casefold() for label in labels} & EASY_LABELS)
    if experience_level == "beginner":
        return 1.0 if easy_issue else 0.25
    if experience_level == "advanced":
        return 0.25 if easy_issue else 1.0
    return 0.5


def rerank_candidates(
    candidates: Sequence[RetrievalCandidate],
    filters: SearchFilters,
    now: datetime | None = None,
) -> list[RetrievedIssue]:
    if not candidates:
        return []
    raw_rrf_scores = [
        compute_rrf_score(candidate.vector_rank, candidate.fts_rank) for candidate in candidates
    ]
    max_rrf = max(raw_rrf_scores, default=0.0)
    results: list[RetrievedIssue] = []
    reference_time = now or datetime.now(UTC)
    for candidate, raw_rrf in zip(candidates, raw_rrf_scores, strict=True):
        norm_rrf = raw_rrf / max_rrf if max_rrf > 0 else 0.0
        maintainer_score = _clamp(candidate.maintainer_activity_score)
        freshness_score = compute_freshness_score(candidate.github_updated_at, reference_time)
        program_boost = float(filters.prioritize_gsoc and "gsoc" in candidate.program_tags)
        experience_boost = compute_experience_boost(candidate.labels, filters.experience_level)
        final_score = (
            0.62 * norm_rrf
            + 0.15 * maintainer_score
            + 0.10 * freshness_score
            + 0.08 * program_boost
            + 0.05 * experience_boost
        )
        results.append(
            RetrievedIssue(
                id=candidate.id,
                repo_full_name=candidate.repo_full_name,
                repo_owner=candidate.repo_owner,
                repo_topics=candidate.repo_topics,
                primary_language=candidate.primary_language,
                program_tags=candidate.program_tags,
                number=candidate.number,
                title=candidate.title,
                html_url=candidate.html_url,
                labels=candidate.labels,
                comments_count=candidate.comments_count,
                maintainer_activity_score=candidate.maintainer_activity_score,
                github_updated_at=candidate.github_updated_at,
                snippet=candidate.snippet,
                scores=ScoreBreakdown(
                    vector_score=_clamp(candidate.vector_score),
                    fts_score=_clamp(candidate.fts_score),
                    rrf_score=norm_rrf,
                    maintainer_score=maintainer_score,
                    freshness_score=freshness_score,
                    program_boost=program_boost,
                    experience_boost=experience_boost,
                    final_score=final_score,
                ),
            )
        )
    return sorted(
        results,
        key=lambda result: (
            -result.scores.final_score,
            result.repo_full_name.casefold(),
            result.number,
        ),
    )


def _as_utc(value: datetime) -> datetime:
    return value.replace(tzinfo=UTC) if value.tzinfo is None else value.astimezone(UTC)


def _clamp(value: float) -> float:
    return min(max(value, 0.0), 1.0)
