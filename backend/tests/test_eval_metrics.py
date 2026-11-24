from datetime import UTC, datetime

from app.schemas.search import RetrievedIssue, ScoreBreakdown, SearchFilters
from evals.benchmark_dataset import (
    BENCHMARK_ISSUES,
    BENCHMARK_REPOSITORIES,
    EVAL_CASES,
)
from evals.metrics import (
    negative_constraint_violations,
    recall_at_k,
    reciprocal_rank,
)


def _result(
    repo: str,
    number: int,
    *,
    labels: list[str] | None = None,
    topics: list[str] | None = None,
) -> RetrievedIssue:
    return RetrievedIssue(
        id=number,
        repo_full_name=repo,
        repo_owner=repo.split("/")[0],
        repo_topics=topics or [],
        primary_language="Python",
        program_tags=[],
        number=number,
        title="Issue",
        html_url="https://example.test",
        labels=labels or [],
        comments_count=0,
        maintainer_activity_score=0.5,
        github_updated_at=datetime(2026, 11, 25, tzinfo=UTC),
        snippet="Issue details",
        scores=ScoreBreakdown(
            vector_score=0.5,
            fts_score=0.5,
            rrf_score=0.5,
            maintainer_score=0.5,
            freshness_score=0.5,
            program_boost=0.0,
            experience_boost=0.5,
            final_score=0.5,
        ),
    )


def test_recall_at_k_uses_unique_relevant_issue_keys() -> None:
    retrieved = [("org/repo", 1), ("org/repo", 2), ("org/repo", 1)]

    assert recall_at_k(retrieved, {("org/repo", 1), ("org/repo", 2)}, 2) == 1.0
    assert recall_at_k(retrieved, {("org/repo", 3)}, 2) == 0.0


def test_reciprocal_rank_returns_first_relevant_rank() -> None:
    retrieved = [("org/repo", 1), ("org/repo", 2), ("org/repo", 3)]

    assert reciprocal_rank(retrieved, {("org/repo", 2), ("org/repo", 3)}) == 0.5
    assert reciprocal_rank(retrieved, {("other/repo", 9)}) == 0.0


def test_negative_constraint_violation_rate_checks_labels_and_repo_topics() -> None:
    results = [
        _result("org/one", 1),
        _result("org/two", 2, labels=["Documentation"]),
        _result("org/three", 3, topics=["NOT-A-FIT"]),
    ]

    rate = negative_constraint_violations(
        results,
        SearchFilters(excluded_labels=["documentation"], excluded_topics=["not-a-fit"]),
    )

    assert rate == 2 / 3
    assert negative_constraint_violations([], SearchFilters()) == 0.0


def test_benchmark_has_thirty_issues_eight_repositories_and_twelve_queries() -> None:
    assert len(BENCHMARK_ISSUES) == 30
    assert len(BENCHMARK_REPOSITORIES) == 8
    assert len(EVAL_CASES) == 12
