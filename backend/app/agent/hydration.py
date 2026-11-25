from __future__ import annotations

import asyncio
import logging
from collections.abc import Callable, Sequence
from datetime import UTC, datetime, timedelta

import httpx
from sqlalchemy import exists, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import Settings, get_settings
from app.db.models import Issue, Repository
from app.ingestion.github_client import GitHubGraphQLClient, GitHubGraphQLError
from app.ingestion.pipeline import IngestionPipeline
from app.ingestion.seed import RepoTarget
from app.schemas.chat import HydrationReport, normalize_target_scope

logger = logging.getLogger(__name__)
PipelineFactory = Callable[[], IngestionPipeline]


async def maybe_hydrate_target_scope(
    session: AsyncSession,
    target_org: str | None,
    target_repo: str | None,
    pipeline_factory: PipelineFactory,
    settings: Settings | None = None,
) -> HydrationReport:
    settings = settings or get_settings()
    target_org, target_repo = normalize_target_scope(target_org, target_repo)
    scope = target_repo or target_org
    if scope is None:
        return HydrationReport(triggered=False, status="not_needed")

    client: object | None = None
    try:
        now = datetime.now(UTC)
        stale_before = now - timedelta(hours=settings.jit_hydration_stale_hours)
        fresh_repositories = await _fresh_repositories(
            session,
            target_org,
            target_repo,
            stale_before,
        )
        if fresh_repositories:
            for repository in fresh_repositories:
                repository.last_queried_at = now
            await session.commit()
            return HydrationReport(scope=scope, status="not_needed")

        if not settings.github_token:
            return HydrationReport(scope=scope, status="skipped_no_token")
        if settings.jit_hydration_stale_hours < 0:
            raise ValueError("jit_hydration_stale_hours cannot be negative")

        pipeline = pipeline_factory()
        client = pipeline.github_client

        async def hydrate() -> HydrationReport:
            if target_repo is not None:
                owner, name = target_repo.split("/")
                targets = [RepoTarget(owner=owner, name=name)]
            else:
                fetch_org = getattr(client, "fetch_org_active_repos", None)
                if fetch_org is None:
                    raise RuntimeError("The configured ingestion client cannot discover org repos")
                targets = await fetch_org(
                    target_org,
                    limit=settings.jit_hydration_max_org_repos,
                )
            targets = _deduplicate_targets(targets)
            if not targets:
                return HydrationReport(
                    triggered=True,
                    scope=scope,
                    status="hydrated",
                )

            repos_synced: list[str] = []
            issues_added = 0
            for target in targets:
                full_name = f"{target.owner}/{target.name}"
                before_count = await _issue_count(session, full_name)
                await pipeline.sync_repository(
                    session,
                    target.owner,
                    target.name,
                    source="on_demand",
                    max_issues=settings.jit_hydration_max_issues,
                )
                synced_repository = await session.scalar(
                    select(Repository).where(
                        func.lower(Repository.full_name) == full_name.casefold()
                    )
                )
                if synced_repository is None:
                    raise RuntimeError(f"Synced repository was not persisted: {full_name}")
                synced_repository.last_queried_at = datetime.now(UTC)
                await session.commit()
                after_count = await _issue_count(session, full_name)
                issues_added += max(0, after_count - before_count)
                repos_synced.append(synced_repository.full_name)
            return HydrationReport(
                triggered=True,
                scope=scope,
                repos_synced=repos_synced,
                issues_added=issues_added,
                status="hydrated",
            )

        return await asyncio.wait_for(hydrate(), timeout=25.0)
    except TimeoutError:
        logger.warning("On-demand repository hydration timed out", extra={"scope": scope})
        return HydrationReport(triggered=True, scope=scope, status="failed")
    except (GitHubGraphQLError, httpx.HTTPError):
        logger.exception("On-demand repository hydration failed", extra={"scope": scope})
        return HydrationReport(triggered=True, scope=scope, status="failed")
    except Exception:
        logger.exception(
            "Unexpected on-demand repository hydration failure",
            extra={"scope": scope},
        )
        return HydrationReport(triggered=True, scope=scope, status="failed")
    finally:
        if client is not None:
            try:
                if isinstance(client, GitHubGraphQLClient):
                    await client.aclose()
                else:
                    close = getattr(client, "aclose", None)
                    if close is not None:
                        await close()
            except Exception:
                logger.exception("Failed to close hydration GitHub client", extra={"scope": scope})


async def _fresh_repositories(
    session: AsyncSession,
    target_org: str | None,
    target_repo: str | None,
    stale_before: datetime,
) -> list[Repository]:
    has_actionable_open_issue = exists(
        select(Issue.id).where(
            Issue.repo_id == Repository.id,
            Issue.state == "open",
            Issue.is_actionable.is_(True),
        )
    )
    conditions = [
        Repository.last_synced_at.is_not(None),
        Repository.last_synced_at >= stale_before,
        has_actionable_open_issue,
    ]
    if target_repo is not None:
        conditions.append(func.lower(Repository.full_name) == target_repo.casefold())
    elif target_org is not None:
        conditions.append(func.lower(Repository.owner) == target_org.casefold())
    else:
        return []
    return list((await session.scalars(select(Repository).where(*conditions))).all())


async def _issue_count(session: AsyncSession, full_name: str) -> int:
    count = await session.scalar(
        select(func.count(Issue.id))
        .join(Repository, Repository.id == Issue.repo_id)
        .where(func.lower(Repository.full_name) == full_name.casefold())
    )
    return int(count or 0)


def _deduplicate_targets(targets: Sequence[RepoTarget]) -> list[RepoTarget]:
    unique: dict[tuple[str, str], RepoTarget] = {}
    for target in targets:
        unique.setdefault((target.owner.casefold(), target.name.casefold()), target)
    return list(unique.values())
