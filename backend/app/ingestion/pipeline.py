import logging
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Protocol

from sqlalchemy import delete, select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import Settings, get_settings
from app.db.models import Issue, Repository
from app.ingestion.embedder import Embedder, FastEmbedder
from app.ingestion.github_client import (
    FetchedIssue,
    FetchedRepoBatch,
    GitHubGraphQLClient,
)
from app.ingestion.quality_gate import (
    build_embedding_text,
    compute_maintainer_activity_score,
    evaluate_issue_actionability,
)
from app.ingestion.seed import (
    RepoTarget,
    SeedCatalog,
    load_seed_catalog,
    merge_repo_targets,
)

logger = logging.getLogger(__name__)


class IssueFetcher(Protocol):
    async def fetch_repository_issues(
        self,
        owner: str,
        name: str,
        since: datetime | None = None,
        max_issues: int = 120,
    ) -> FetchedRepoBatch:
        """Fetch repository metadata and recent issues."""

    async def fetch_org_active_repos(self, org: str, limit: int = 10) -> list[RepoTarget]:
        """Fetch recently updated, non-archived repositories for an organization."""


def _matches_program(tags: list[str], program: str | None) -> bool:
    return program is None or program.casefold() in tags


async def resolve_seed_targets(
    catalog: SeedCatalog,
    github_client: IssueFetcher,
    *,
    program: str | None = None,
    max_repos: int | None = None,
) -> list[RepoTarget]:
    if max_repos is not None and max_repos < 1:
        raise ValueError("max_repos must be positive")
    normalized_program = program.strip().casefold() if program is not None else None
    if normalized_program == "":
        raise ValueError("program cannot be empty")

    candidates = [
        target
        for target in catalog.repositories
        if _matches_program(target.program_tags, normalized_program)
    ]
    for organization in catalog.organizations:
        if not _matches_program(organization.program_tags, normalized_program):
            continue
        remaining = getattr(github_client, "rate_limit_remaining", None)
        if isinstance(remaining, int) and remaining < 200:
            logger.warning(
                "Stopping organization discovery below the GitHub rate-limit safety threshold",
                extra={"remaining": remaining, "organization": organization.org},
            )
            break
        try:
            discovered = await github_client.fetch_org_active_repos(
                organization.org, limit=organization.max_repos
            )
        except Exception:
            logger.exception(
                "Failed to discover organization repositories",
                extra={"organization": organization.org},
            )
            continue
        for target in discovered:
            candidates.append(
                target.model_copy(
                    update={
                        "priority": organization.priority,
                        "program_tags": sorted(
                            set(target.program_tags) | set(organization.program_tags)
                        ),
                    }
                )
            )

    resolved = merge_repo_targets(candidates)
    return resolved[:max_repos] if max_repos is not None else resolved


@dataclass(frozen=True)
class RepoSyncStats:
    repository: str
    fetched: int
    actionable: int
    embedded: int
    skipped: int
    closed_marked: int


@dataclass(frozen=True)
class SyncRunSummary:
    synced: int
    failed: int
    fetched: int
    actionable: int
    embedded: int
    skipped: int
    closed_marked: int
    errors: dict[str, str]
    stopped_for_rate_limit: bool = False


@dataclass(frozen=True)
class PruneStats:
    closed_issues_deleted: int
    on_demand_repositories_deleted: int


class IngestionPipeline:
    def __init__(
        self,
        github_client: IssueFetcher | GitHubGraphQLClient | None,
        embedder: Embedder | None = None,
        settings: Settings | None = None,
    ) -> None:
        self.github_client = github_client
        self.embedder = embedder or FastEmbedder()
        self.settings = settings or get_settings()

    async def sync_repository(
        self,
        session: AsyncSession,
        owner: str,
        name: str,
        source: str = "curated",
        max_issues: int | None = None,
        priority: int = 100,
        program_tags: list[str] | None = None,
    ) -> RepoSyncStats:
        full_name = f"{owner}/{name}"
        existing_repo = await session.scalar(
            select(Repository).where(Repository.full_name == full_name)
        )
        since = existing_repo.last_synced_at if existing_repo is not None else None
        if self.github_client is None:
            raise RuntimeError("GitHub client is required to sync repositories")
        cursor_time = datetime.now(UTC)
        fetched_batch = await self.github_client.fetch_repository_issues(
            owner,
            name,
            since=since,
            max_issues=(
                self.settings.ingestion_max_issues_per_repo if max_issues is None else max_issues
            ),
        )
        now = datetime.now(UTC)
        repo = fetched_batch.repository
        last_commit_days = (
            max(0, (now - _as_utc(repo.last_commit_at)).days)
            if repo.last_commit_at is not None
            else None
        )
        repository_values = {
            "github_id": repo.github_id,
            "owner": repo.owner,
            "name": repo.name,
            "full_name": repo.name_with_owner,
            "primary_language": repo.primary_language,
            "topics": repo.topics,
            "stars": repo.stars,
            "is_archived": repo.is_archived,
            "maintainer_activity_score": compute_maintainer_activity_score(
                last_commit_days, repo.merged_prs_90d, repo.is_archived
            ),
            "source": source,
            "priority": priority,
            "program_tags": program_tags or [],
            "last_synced_at": cursor_time,
            "updated_at": now,
        }

        fetched_issues = fetched_batch.issues
        existing_by_github_id: dict[int, Issue] = {}
        if fetched_issues:
            existing_result = await session.scalars(
                select(Issue).where(
                    Issue.github_id.in_([issue.github_id for issue in fetched_issues])
                )
            )
            existing_by_github_id = {issue.github_id: issue for issue in existing_result.all()}

        actionable: list[FetchedIssue] = []
        issue_values: list[dict[str, object]] = []
        to_embed: list[FetchedIssue] = []
        for issue in fetched_issues:
            is_actionable, rejection_reasons = evaluate_issue_actionability(
                issue, repo.is_archived, now
            )
            previous = existing_by_github_id.get(issue.github_id)
            previous_embedding: list[float] | None = (
                list(previous.embedding) if previous and previous.embedding is not None else None
            )
            unchanged = previous is not None and _as_utc(previous.github_updated_at) == _as_utc(
                issue.updated_at
            )
            embedding = previous_embedding if is_actionable and unchanged else None
            if is_actionable:
                actionable.append(issue)
                if not unchanged or previous_embedding is None:
                    to_embed.append(issue)
            elif rejection_reasons:
                logger.debug(
                    "Issue rejected by quality gate",
                    extra={
                        "repository": full_name,
                        "issue_number": issue.number,
                        "reasons": rejection_reasons,
                    },
                )
            issue_values.append(_issue_values(issue, embedding, repo.is_archived, is_actionable))

        vectors = self.embedder.embed_documents(
            [build_embedding_text(repo, issue) for issue in to_embed]
        )
        if len(vectors) != len(to_embed):
            raise ValueError(
                f"Embedder returned {len(vectors)} vectors for {len(to_embed)} documents"
            )
        embeddings_by_id = {
            issue.github_id: vector for issue, vector in zip(to_embed, vectors, strict=True)
        }
        for issue, values in zip(fetched_issues, issue_values, strict=True):
            if issue.github_id in embeddings_by_id:
                values["embedding"] = embeddings_by_id[issue.github_id]
            elif issue.github_id in existing_by_github_id and values["is_actionable"]:
                values["embedding"] = existing_by_github_id[issue.github_id].embedding

        repository_insert = insert(Repository).values(**repository_values)
        repository_upsert = repository_insert.on_conflict_do_update(
            index_elements=[Repository.github_id],
            set_={key: value for key, value in repository_values.items() if key != "github_id"},
        ).returning(Repository.id)
        repository_id = await session.scalar(repository_upsert)
        if repository_id is None:
            raise RuntimeError(f"Failed to upsert repository {full_name}")

        if issue_values:
            for values in issue_values:
                values["repo_id"] = repository_id
            issue_insert = insert(Issue).values(issue_values)
            await session.execute(
                issue_insert.on_conflict_do_update(
                    index_elements=[Issue.github_id],
                    set_={
                        "repo_id": issue_insert.excluded.repo_id,
                        "number": issue_insert.excluded.number,
                        "title": issue_insert.excluded.title,
                        "body": issue_insert.excluded.body,
                        "html_url": issue_insert.excluded.html_url,
                        "state": issue_insert.excluded.state,
                        "labels": issue_insert.excluded.labels,
                        "assignees_count": issue_insert.excluded.assignees_count,
                        "comments_count": issue_insert.excluded.comments_count,
                        "has_linked_pr": issue_insert.excluded.has_linked_pr,
                        "is_actionable": issue_insert.excluded.is_actionable,
                        "embedding": issue_insert.excluded.embedding,
                        "github_created_at": issue_insert.excluded.github_created_at,
                        "github_updated_at": issue_insert.excluded.github_updated_at,
                        "updated_at": now,
                    },
                )
            )
        await session.commit()

        return RepoSyncStats(
            repository=repo.name_with_owner,
            fetched=len(fetched_issues),
            actionable=len(actionable),
            embedded=len(to_embed),
            skipped=len(fetched_issues) - len(actionable),
            closed_marked=sum(1 for issue in fetched_issues if issue.state.casefold() == "closed"),
        )

    async def sync_seed_repos(
        self,
        session: AsyncSession,
        repos_file: Path,
        max_issues_per_repo: int | None = None,
        program: str | None = None,
        max_repos: int | None = None,
    ) -> SyncRunSummary:
        catalog = load_seed_catalog(repos_file)
        if self.github_client is None:
            raise RuntimeError("GitHub client is required to resolve seed targets")
        targets = await resolve_seed_targets(
            catalog,
            self.github_client,
            program=program,
            max_repos=max_repos,
        )
        stats: list[RepoSyncStats] = []
        errors: dict[str, str] = {}
        stopped_for_rate_limit = False
        for target in targets:
            remaining = getattr(self.github_client, "rate_limit_remaining", None)
            if isinstance(remaining, int) and remaining < 200:
                logger.warning(
                    "Stopping repository sync below the GitHub rate-limit safety threshold",
                    extra={
                        "remaining": remaining,
                        "repositories_synced": len(stats),
                        "next_repository": target.full_name,
                    },
                )
                stopped_for_rate_limit = True
                break
            try:
                stats.append(
                    await self.sync_repository(
                        session,
                        target.owner,
                        target.name,
                        source="curated",
                        max_issues=max_issues_per_repo,
                        priority=target.priority,
                        program_tags=target.program_tags,
                    )
                )
            except Exception as exc:
                await session.rollback()
                errors[target.full_name] = str(exc)
                logger.exception(
                    "Failed to sync repository",
                    extra={"repository": target.full_name},
                )
        return SyncRunSummary(
            synced=len(stats),
            failed=len(errors),
            fetched=sum(item.fetched for item in stats),
            actionable=sum(item.actionable for item in stats),
            embedded=sum(item.embedded for item in stats),
            skipped=sum(item.skipped for item in stats),
            closed_marked=sum(item.closed_marked for item in stats),
            errors=errors,
            stopped_for_rate_limit=stopped_for_rate_limit,
        )

    async def prune_stale_data(
        self,
        session: AsyncSession,
        closed_days: int = 14,
        on_demand_days: int = 30,
    ) -> PruneStats:
        if closed_days < 0 or on_demand_days < 0:
            raise ValueError("retention periods cannot be negative")
        now = datetime.now(UTC)
        closed_result = await session.execute(
            delete(Issue)
            .where(
                Issue.state == "closed",
                Issue.updated_at < now - timedelta(days=closed_days),
            )
            .execution_options(synchronize_session=False)
            .returning(Issue.id)
        )
        repo_result = await session.execute(
            delete(Repository)
            .where(
                Repository.source == "on_demand",
                Repository.last_queried_at.is_not(None),
                Repository.last_queried_at < now - timedelta(days=on_demand_days),
            )
            .execution_options(synchronize_session=False)
            .returning(Repository.id)
        )
        await session.commit()
        return PruneStats(
            closed_issues_deleted=len(closed_result.scalars().all()),
            on_demand_repositories_deleted=len(repo_result.scalars().all()),
        )


def _issue_values(
    issue: FetchedIssue,
    embedding: list[float] | None,
    repo_archived: bool,
    is_actionable: bool,
) -> dict[str, object]:
    return {
        "github_id": issue.github_id,
        "number": issue.number,
        "title": issue.title,
        "body": issue.body,
        "html_url": issue.url,
        "state": issue.state.casefold(),
        "labels": issue.labels,
        "assignees_count": issue.assignees_count,
        "comments_count": issue.comments_count,
        "has_linked_pr": issue.has_linked_pr,
        "is_actionable": is_actionable and not repo_archived,
        "embedding": embedding if is_actionable and not repo_archived else None,
        "github_created_at": issue.created_at,
        "github_updated_at": issue.updated_at,
    }


def _as_utc(value: datetime) -> datetime:
    return value.replace(tzinfo=UTC) if value.tzinfo is None else value.astimezone(UTC)
