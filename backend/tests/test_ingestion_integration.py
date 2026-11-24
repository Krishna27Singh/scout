from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest
from sqlalchemy import select

from app.core.config import Settings
from app.db.models import Issue, Repository
from app.db.session import SessionFactory
from app.ingestion.embedder import DeterministicFakeEmbedder
from app.ingestion.github_client import FetchedIssue, FetchedRepoBatch, FetchedRepository
from app.ingestion.pipeline import IngestionPipeline

pytestmark = pytest.mark.integration
LONG_BODY = (
    "This issue describes a reproducible behavior and outlines how it affects users. "
    "It includes sufficient detail for a contributor to investigate a practical fix."
)


class QueuedGitHubClient:
    def __init__(self, batches: list[FetchedRepoBatch]) -> None:
        self.batches = batches
        self.since_values: list[datetime | None] = []
        self.calls: list[tuple[str, str, datetime | None, int]] = []

    async def fetch_repository_issues(
        self,
        owner: str,
        name: str,
        since: datetime | None = None,
        max_issues: int = 120,
    ) -> FetchedRepoBatch:
        self.since_values.append(since)
        self.calls.append((owner, name, since, max_issues))
        return self.batches.pop(0)


def _issue(
    github_id: int,
    number: int,
    updated_at: datetime,
    *,
    state: str = "open",
    assignees: int = 0,
) -> FetchedIssue:
    return FetchedIssue(
        github_id=github_id,
        number=number,
        title=f"Useful contribution {number}",
        body=LONG_BODY,
        url=f"https://github.com/scout-integration/project/issues/{number}",
        state=state,
        created_at=updated_at - timedelta(days=1),
        updated_at=updated_at,
        labels=[],
        assignees_count=assignees,
        comments_count=0,
        has_linked_pr=False,
    )


def _batch(
    github_id: int,
    name: str,
    issues: list[FetchedIssue],
) -> FetchedRepoBatch:
    return FetchedRepoBatch(
        repository=FetchedRepository(
            github_id=github_id,
            owner="scout-integration",
            name=name,
            name_with_owner=f"scout-integration/{name}",
            primary_language="Python",
            topics=["testing"],
            stars=10,
            is_archived=False,
            last_commit_at=datetime.now(UTC) - timedelta(days=2),
            merged_prs_90d=3,
        ),
        issues=issues,
    )


async def test_incremental_sync_and_stale_pruning_are_idempotent() -> None:
    suffix = uuid4().hex[:12]
    repo_github_id = int(uuid4().hex[:14], 16)
    issue_github_id = int(uuid4().hex[:14], 16)
    nonactionable_github_id = int(uuid4().hex[:14], 16)
    on_demand_github_id = int(uuid4().hex[:14], 16)
    active_updated = datetime.now(UTC) - timedelta(minutes=5)
    closed_updated = datetime.now(UTC) - timedelta(minutes=2)
    repo_name = f"project-{suffix}"
    on_demand_name = f"temporary-{suffix}"
    first_batch = _batch(
        repo_github_id,
        repo_name,
        [
            _issue(issue_github_id, 1, active_updated),
            _issue(nonactionable_github_id, 2, active_updated, assignees=1),
        ],
    )
    second_batch = _batch(
        repo_github_id,
        repo_name,
        [_issue(issue_github_id, 1, closed_updated, state="closed")],
    )
    client = QueuedGitHubClient([first_batch, second_batch])
    pipeline = IngestionPipeline(
        client,
        embedder=DeterministicFakeEmbedder(),
        settings=Settings(_env_file=None),
    )
    async with SessionFactory() as session:
        first = await pipeline.sync_repository(
            session,
            "scout-integration",
            repo_name,
            priority=1,
            program_tags=["gsoc"],
        )
        assert first.fetched == 2
        assert first.actionable == 1
        assert first.embedded == 1
        assert first.skipped == 1

        repository = await session.scalar(
            select(Repository).where(Repository.github_id == repo_github_id)
        )
        assert repository is not None
        assert repository.last_synced_at is not None
        assert repository.program_tags == ["gsoc"]
        assert repository.priority == 1

        stored_actionable = await session.scalar(
            select(Issue).where(Issue.github_id == issue_github_id)
        )
        stored_nonactionable = await session.scalar(
            select(Issue).where(Issue.github_id == nonactionable_github_id)
        )
        assert stored_actionable is not None
        assert stored_actionable.embedding is not None
        assert len(stored_actionable.embedding) == 384
        assert stored_nonactionable is not None
        assert stored_nonactionable.embedding is None

        second = await pipeline.sync_repository(
            session,
            "scout-integration",
            repo_name,
            priority=1,
            program_tags=["gsoc"],
        )
        assert second.closed_marked == 1
        assert second.embedded == 0
        assert client.since_values[0] is None
        assert client.since_values[1] is not None
        assert client.calls[0][0:2] == ("scout-integration", repo_name)
        assert client.calls[0][3] == 120
        await session.refresh(stored_actionable)
        assert stored_actionable.state == "closed"
        assert stored_actionable.is_actionable is False
        assert stored_actionable.embedding is None
        assert await session.scalar(select(Issue.id).where(Issue.github_id == issue_github_id))
        assert (
            len(
                (
                    await session.scalars(select(Issue).where(Issue.github_id == issue_github_id))
                ).all()
            )
            == 1
        )

        old = datetime.now(UTC) - timedelta(days=40)
        stored_actionable.updated_at = old
        stale_repo = Repository(
            github_id=on_demand_github_id,
            owner="scout-integration",
            name=on_demand_name,
            full_name=f"scout-integration/{on_demand_name}",
            source="on_demand",
            last_queried_at=old,
        )
        active_issue = Issue(
            github_id=int(uuid4().hex[:14], 16),
            repo_id=repository.id,
            number=3,
            title="Old closed issue",
            body=LONG_BODY,
            html_url=f"https://github.com/scout-integration/{repo_name}/issues/3",
            state="closed",
            is_actionable=False,
            github_created_at=old,
            github_updated_at=old,
            updated_at=old,
        )
        session.add_all([stale_repo, active_issue])
        await session.flush()
        stale_child = Issue(
            github_id=int(uuid4().hex[:14], 16),
            repo_id=stale_repo.id,
            number=1,
            title="Temporary repository issue",
            body=LONG_BODY,
            html_url=f"https://github.com/scout-integration/{on_demand_name}/issues/1",
            state="open",
            github_created_at=old,
            github_updated_at=old,
        )
        session.add(stale_child)
        await session.commit()

        prune_stats = await pipeline.prune_stale_data(session, closed_days=14, on_demand_days=30)

        assert prune_stats.closed_issues_deleted == 2
        assert prune_stats.on_demand_repositories_deleted == 1
        assert await session.scalar(
            select(Repository.id).where(Repository.github_id == repo_github_id)
        )
        assert (
            await session.scalar(
                select(Repository.id).where(Repository.github_id == on_demand_github_id)
            )
            is None
        )
        assert await session.scalar(
            select(Issue.id).where(Issue.github_id == nonactionable_github_id)
        )
