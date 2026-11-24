from datetime import UTC, datetime, timedelta

import pytest

from app.db.models import UserProfile
from app.retrieval.filters import merge_filters
from app.retrieval.reranker import (
    RetrievalCandidate,
    compute_experience_boost,
    compute_freshness_score,
    compute_rrf_score,
    rerank_candidates,
)
from app.schemas.search import SearchFilters


def _candidate(
    *,
    number: int,
    program_tags: list[str] | None = None,
    labels: list[str] | None = None,
    vector_rank: int | None = None,
    fts_rank: int | None = None,
) -> RetrievalCandidate:
    return RetrievalCandidate(
        id=number,
        repo_full_name=f"org/repo-{number}",
        repo_owner="org",
        repo_topics=[],
        primary_language="Python",
        program_tags=program_tags or [],
        number=number,
        title=f"Issue {number}",
        html_url=f"https://example.test/issues/{number}",
        labels=labels or [],
        comments_count=0,
        maintainer_activity_score=0.5,
        github_updated_at=datetime(2026, 11, 25, tzinfo=UTC),
        snippet="Description",
        vector_rank=vector_rank,
        fts_rank=fts_rank,
        vector_score=0.8,
        fts_score=0.6,
    )


def test_rrf_score_combines_available_rankings() -> None:
    assert compute_rrf_score(1, 1) == pytest.approx(1 / 61)
    assert compute_rrf_score(1, None) == pytest.approx(0.6 / 61)
    assert compute_rrf_score(None, 1) == pytest.approx(0.4 / 61)


def test_freshness_decays_by_half_life_and_clamps_future_dates() -> None:
    now = datetime(2026, 11, 25, tzinfo=UTC)

    assert compute_freshness_score(now - timedelta(days=90), now) == pytest.approx(0.5)
    assert compute_freshness_score(now + timedelta(days=1), now) == pytest.approx(1.0)


def test_experience_boost_prefers_appropriate_issue_labels() -> None:
    beginner_labels = ["Good First Issue"]

    assert compute_experience_boost(beginner_labels, "beginner") == 1.0
    assert compute_experience_boost([], "beginner") == 0.25
    assert compute_experience_boost([], "intermediate") == 0.5
    assert compute_experience_boost([], "advanced") == 1.0
    assert compute_experience_boost(beginner_labels, "advanced") == 0.25


def test_reranker_normalizes_rrf_and_boosts_gsoc_results() -> None:
    now = datetime(2026, 11, 25, tzinfo=UTC)
    candidates = [
        _candidate(number=1, program_tags=["gsoc"], vector_rank=2, fts_rank=2),
        _candidate(number=2, program_tags=["ecosystem"], vector_rank=1, fts_rank=1),
    ]

    results = rerank_candidates(candidates, SearchFilters(), now=now)

    assert results[0].number == 1
    assert results[0].scores.program_boost == 1.0
    assert results[1].scores.program_boost == 0.0
    assert results[1].scores.rrf_score == 1.0
    assert results[0].scores.final_score > results[1].scores.final_score


def test_merge_filters_extends_profile_preferences_and_keeps_negatives() -> None:
    profile = UserProfile(
        session_key="test-profile",
        preferred_languages=["Python"],
        preferred_orgs=["SugarLabs"],
        excluded_labels=["duplicate", "documentation"],
        excluded_topics=["not-a-fit"],
        experience_level="beginner",
    )
    override = SearchFilters(
        languages=["Rust"],
        repo_owners=["Apache"],
        excluded_labels=["wontfix"],
        excluded_topics=["archived"],
        experience_level="advanced",
        prioritize_gsoc=False,
    )

    merged = merge_filters(profile, override)

    assert merged.languages == ["python", "rust"]
    assert merged.repo_owners == ["apache", "sugarlabs"]
    assert merged.excluded_labels == ["documentation", "duplicate", "wontfix"]
    assert merged.excluded_topics == ["archived", "not-a-fit"]
    assert merged.experience_level == "advanced"
    assert merged.prioritize_gsoc is False
