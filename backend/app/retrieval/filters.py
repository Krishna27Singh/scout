from collections.abc import Sequence

from sqlalchemy import ColumnElement, exists, func, not_, select
from sqlalchemy.orm.attributes import InstrumentedAttribute

from app.db.models import Issue, Repository, UserProfile
from app.schemas.search import SearchFilters


def _union_values(saved: Sequence[str], requested: Sequence[str]) -> list[str]:
    return sorted({value.casefold() for value in (*saved, *requested) if value.strip()})


def merge_filters(
    profile: UserProfile | None,
    override: SearchFilters | None,
    *,
    replace_saved_languages: bool = False,
) -> SearchFilters:
    saved_languages = profile.preferred_languages if profile is not None else []
    saved_owners = profile.preferred_orgs if profile is not None else []
    saved_excluded_labels = profile.excluded_labels if profile is not None else []
    saved_excluded_topics = profile.excluded_topics if profile is not None else []
    saved_experience = profile.experience_level if profile is not None else "intermediate"
    requested = override or SearchFilters()
    values = {
        "languages": _union_values(
            [] if replace_saved_languages else saved_languages,
            requested.languages,
        ),
        "repo_owners": _union_values(saved_owners, requested.repo_owners),
        "repo_full_names": _union_values([], requested.repo_full_names),
        "program_tags": _union_values([], requested.program_tags),
        "excluded_labels": _union_values(saved_excluded_labels, requested.excluded_labels),
        "excluded_topics": _union_values(saved_excluded_topics, requested.excluded_topics),
        "experience_level": (
            requested.experience_level
            if override is not None and "experience_level" in override.model_fields_set
            else saved_experience
        ),
        "prioritize_gsoc": (
            requested.prioritize_gsoc
            if override is not None and "prioritize_gsoc" in override.model_fields_set
            else True
        ),
    }
    return SearchFilters.model_validate(values)


def _array_contains_any_casefolded(
    column: InstrumentedAttribute[list[str]],
    values: Sequence[str],
    correlation: object,
    alias_name: str,
) -> ColumnElement[bool]:
    unnested = func.unnest(column).table_valued("value").render_derived(name=alias_name)
    return exists(
        select(1)
        .select_from(unnested)
        .where(func.lower(unnested.c.value).in_(list(values)))
        .correlate(correlation)  # type: ignore[arg-type]
    )


def build_base_conditions(
    filters: SearchFilters,
    dismissed_issue_ids: set[int],
) -> list[ColumnElement[bool]]:
    conditions: list[ColumnElement[bool]] = [
        Issue.state == "open",
        Issue.is_actionable.is_(True),
        Repository.is_archived.is_(False),
    ]
    if filters.languages:
        conditions.append(func.lower(Repository.primary_language).in_(filters.languages))
    if filters.repo_owners:
        conditions.append(func.lower(Repository.owner).in_(filters.repo_owners))
    if filters.repo_full_names:
        conditions.append(func.lower(Repository.full_name).in_(filters.repo_full_names))
    if filters.program_tags:
        conditions.append(Repository.program_tags.op("&&")(filters.program_tags))
    if filters.excluded_labels:
        conditions.append(
            not_(
                _array_contains_any_casefolded(
                    Issue.labels,
                    filters.excluded_labels,
                    Issue,
                    "issue_excluded_labels",
                )
            )
        )
    if filters.excluded_topics:
        conditions.extend(
            [
                not_(
                    _array_contains_any_casefolded(
                        Repository.topics,
                        filters.excluded_topics,
                        Repository,
                        "repository_excluded_topics",
                    )
                ),
                not_(
                    _array_contains_any_casefolded(
                        Issue.labels,
                        filters.excluded_topics,
                        Issue,
                        "issue_excluded_topics",
                    )
                ),
            ]
        )
    if dismissed_issue_ids:
        conditions.append(Issue.id.notin_(dismissed_issue_ids))
    return conditions
