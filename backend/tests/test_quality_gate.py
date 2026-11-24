from datetime import UTC, datetime, timedelta

import pytest

from app.ingestion.github_client import FetchedIssue, FetchedRepository
from app.ingestion.quality_gate import (
    build_embedding_text,
    compute_maintainer_activity_score,
    evaluate_issue_actionability,
)

NOW = datetime(2026, 11, 25, tzinfo=UTC)
LONG_BODY = (
    "This issue explains a concrete behavior that should be improved. "
    "It includes enough context for a contributor to investigate and propose a fix."
)


def _issue(**overrides: object) -> FetchedIssue:
    values: dict[str, object] = {
        "github_id": 1,
        "number": 12,
        "title": "Improve useful behavior",
        "body": LONG_BODY,
        "url": "https://github.com/acme/project/issues/12",
        "state": "open",
        "created_at": NOW - timedelta(days=2),
        "updated_at": NOW - timedelta(days=1),
        "labels": [],
        "assignees_count": 0,
        "comments_count": 0,
        "has_linked_pr": False,
    }
    values.update(overrides)
    return FetchedIssue.model_validate(values)


def _repo(**overrides: object) -> FetchedRepository:
    values: dict[str, object] = {
        "github_id": 2,
        "owner": "acme",
        "name": "project",
        "name_with_owner": "acme/project",
        "primary_language": "Python",
        "topics": ["web", "api"],
        "stars": 100,
        "is_archived": False,
    }
    values.update(overrides)
    return FetchedRepository.model_validate(values)


@pytest.mark.parametrize(
    ("issue_overrides", "repo_archived", "expected_reason"),
    [
        ({}, True, "repository_archived"),
        ({"state": "closed"}, False, "issue_not_open"),
        ({"assignees_count": 1}, False, "issue_assigned"),
        ({"has_linked_pr": True}, False, "linked_pull_request"),
        ({"body": "Too short."}, False, "body_too_short"),
    ],
)
def test_quality_gate_rejects_unactionable_issues(
    issue_overrides: dict[str, object],
    repo_archived: bool,
    expected_reason: str,
) -> None:
    actionable, reasons = evaluate_issue_actionability(
        _issue(**issue_overrides), repo_archived, now=NOW
    )

    assert actionable is False
    assert expected_reason in reasons


@pytest.mark.parametrize(
    "label",
    [
        "duplicate",
        "wontfix",
        "invalid",
        "needs-more-info",
        "waiting-for-author",
        "blocked",
        "tracking",
        "meta",
        "stale",
        "question",
        "support",
    ],
)
def test_noise_labels_are_rejected_case_insensitively(label: str) -> None:
    actionable, reasons = evaluate_issue_actionability(
        _issue(labels=[label.upper()]), False, now=NOW
    )

    assert actionable is False
    assert "noise_label" in reasons


def test_staleness_uses_18_month_default_window() -> None:
    old_issue = _issue(updated_at=datetime(2025, 5, 24, tzinfo=UTC))
    recent_issue = _issue(updated_at=datetime(2025, 5, 26, tzinfo=UTC))

    assert "issue_stale" in evaluate_issue_actionability(old_issue, False, now=NOW)[1]
    assert evaluate_issue_actionability(recent_issue, False, now=NOW)[0]


def test_good_first_issue_extends_staleness_window_to_24_months() -> None:
    issue = _issue(
        labels=["Good First Issue"],
        updated_at=datetime(2025, 1, 25, tzinfo=UTC),
    )

    assert evaluate_issue_actionability(issue, False, now=NOW)[0]


def test_activity_score_is_normalized_and_archived_is_zero() -> None:
    assert compute_maintainer_activity_score(10, 10, False) == 0.8111
    assert compute_maintainer_activity_score(180, 20, False) == 0.0
    assert compute_maintainer_activity_score(1, 20, True) == 0.0
    assert 0.0 <= compute_maintainer_activity_score(0, 100, False) <= 1.0


def test_embedding_text_strips_comments_and_images_and_respects_limit() -> None:
    issue = _issue(
        body=(
            "<!-- internal note --> A useful description. ![diagram](image.png) "
            "<b>More details</b>   across lines."
        )
    )
    text = build_embedding_text(_repo(), issue, max_chars=120)

    assert "<!--" not in text
    assert "![diagram]" not in text
    assert "image.png" not in text
    assert len(text) <= 120
