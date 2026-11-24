from collections.abc import Sequence

from app.schemas.search import RetrievedIssue, SearchFilters

IssueKey = tuple[str, int]
EvaluationResult = IssueKey | RetrievedIssue


def _key(value: EvaluationResult) -> IssueKey:
    if isinstance(value, RetrievedIssue):
        return value.repo_full_name, value.number
    return value


def recall_at_k(
    retrieved: Sequence[EvaluationResult],
    relevant: set[IssueKey] | Sequence[IssueKey],
    k: int,
) -> float:
    if k < 1:
        raise ValueError("k must be positive")
    relevant_set = set(relevant)
    if not relevant_set:
        return 0.0
    found = {_key(result) for result in retrieved[:k]}
    return len(found & relevant_set) / len(relevant_set)


def reciprocal_rank(
    retrieved: Sequence[EvaluationResult],
    relevant: set[IssueKey] | Sequence[IssueKey],
) -> float:
    relevant_set = set(relevant)
    for rank, result in enumerate(retrieved, start=1):
        if _key(result) in relevant_set:
            return 1.0 / rank
    return 0.0


def negative_constraint_violations(
    results: Sequence[RetrievedIssue],
    filters: SearchFilters,
) -> float:
    if not results:
        return 0.0
    excluded_labels = {label.casefold() for label in filters.excluded_labels}
    excluded_topics = {topic.casefold() for topic in filters.excluded_topics}
    violation_count = 0
    for result in results:
        issue_labels = {label.casefold() for label in result.labels}
        repository_topics = {topic.casefold() for topic in result.repo_topics}
        if issue_labels & excluded_labels or (issue_labels | repository_topics) & excluded_topics:
            violation_count += 1
    return violation_count / len(results)
