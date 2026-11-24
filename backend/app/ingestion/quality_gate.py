import calendar
import re
from datetime import UTC, datetime
from html import unescape

from app.ingestion.github_client import FetchedIssue, FetchedRepository

NOISE_LABELS = frozenset(
    {
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
    }
)
_HTML_COMMENT = re.compile(r"<!--.*?-->", re.DOTALL)
_MARKDOWN_IMAGE = re.compile(r"!\[[^\]]*]\([^)]*\)")
_HTML_TAG = re.compile(r"<[^>]*>")
_WHITESPACE = re.compile(r"\s+")


def compute_maintainer_activity_score(
    days_since_last_commit: int | None,
    merged_prs_90d: int,
    is_archived: bool,
) -> float:
    if is_archived or days_since_last_commit is None or days_since_last_commit >= 180:
        return 0.0
    recency_score = max(0.0, 1.0 - max(days_since_last_commit, 0) / 180)
    pull_request_score = min(max(merged_prs_90d, 0), 20) / 20
    return round(0.7 * recency_score + 0.3 * pull_request_score, 4)


def clean_issue_text(value: str | None) -> str:
    without_comments = _HTML_COMMENT.sub(" ", value or "")
    without_images = _MARKDOWN_IMAGE.sub(" ", without_comments)
    without_tags = _HTML_TAG.sub(" ", without_images)
    return _WHITESPACE.sub(" ", unescape(without_tags)).strip()


def _subtract_months(value: datetime, months: int) -> datetime:
    month_index = value.year * 12 + value.month - 1 - months
    year, month_zero_based = divmod(month_index, 12)
    month = month_zero_based + 1
    day = min(value.day, calendar.monthrange(year, month)[1])
    return value.replace(year=year, month=month, day=day)


def _as_utc(value: datetime) -> datetime:
    return value.replace(tzinfo=UTC) if value.tzinfo is None else value.astimezone(UTC)


def evaluate_issue_actionability(
    issue: FetchedIssue,
    repo_archived: bool,
    now: datetime | None = None,
) -> tuple[bool, list[str]]:
    rejection_reasons: list[str] = []
    if repo_archived:
        rejection_reasons.append("repository_archived")
    if issue.state.casefold() != "open":
        rejection_reasons.append("issue_not_open")
    if issue.assignees_count > 0:
        rejection_reasons.append("issue_assigned")
    if issue.has_linked_pr:
        rejection_reasons.append("linked_pull_request")
    normalized_labels = {label.strip().casefold() for label in issue.labels}
    if normalized_labels & NOISE_LABELS:
        rejection_reasons.append("noise_label")
    if len(clean_issue_text(issue.body)) < 80:
        rejection_reasons.append("body_too_short")

    reference_time = _as_utc(now or datetime.now(UTC))
    updated_at = _as_utc(issue.updated_at)
    recency_months = 24 if normalized_labels & {"good first issue", "help wanted"} else 18
    if updated_at < _subtract_months(reference_time, recency_months):
        rejection_reasons.append("issue_stale")

    return not rejection_reasons, rejection_reasons


def build_embedding_text(
    repo: FetchedRepository,
    issue: FetchedIssue,
    max_chars: int = 1500,
) -> str:
    if max_chars < 1:
        raise ValueError("max_chars must be positive")
    sections = [
        f"Repository: {repo.name_with_owner}",
        f"Language: {repo.primary_language or 'Unknown'}",
        f"Topics: {', '.join(repo.topics)}" if repo.topics else "",
        f"Issue labels: {', '.join(issue.labels)}" if issue.labels else "",
        f"Issue title: {clean_issue_text(issue.title)}",
        "Issue body:",
    ]
    heading = "\n".join(section for section in sections if section)
    body = clean_issue_text(issue.body)
    if not body:
        return heading[:max_chars]
    body_budget = max(0, max_chars - len(heading) - 1)
    return f"{heading}\n{body[:body_budget]}"[:max_chars]
