from sqlalchemy import select
from sqlalchemy.dialects import postgresql

from app.db.models import Issue, Repository
from app.retrieval.filters import build_base_conditions
from app.schemas.search import SearchFilters


def test_search_filter_values_are_casefolded_and_deduplicated() -> None:
    filters = SearchFilters(
        languages=["Python", " python "],
        repo_owners=["SugarLabs", "sugarlabs"],
        repo_full_names=["FastAPI/FastAPI"],
        program_tags=["GSoC", "gsoc"],
        excluded_labels=["Documentation", "documentation"],
    )

    assert filters.languages == ["python"]
    assert filters.repo_owners == ["sugarlabs"]
    assert filters.repo_full_names == ["fastapi/fastapi"]
    assert filters.program_tags == ["gsoc"]
    assert filters.excluded_labels == ["documentation"]


def test_base_conditions_compile_case_insensitive_negatives_and_array_overlap() -> None:
    filters = SearchFilters(
        program_tags=["gsoc"],
        excluded_labels=["documentation"],
        excluded_topics=["not-a-fit"],
    )
    statement = (
        select(Issue.id)
        .join(Repository, Repository.id == Issue.repo_id)
        .where(*build_base_conditions(filters, {42}))
    )

    sql = str(statement.compile(dialect=postgresql.dialect()))

    assert "repositories.program_tags &&" in sql
    assert "unnest(issues.labels) AS issue_excluded_labels(value)" in sql
    assert "unnest(repositories.topics) AS repository_excluded_topics(value)" in sql
    assert "lower(" in sql
    assert "issues.id NOT IN" in sql
