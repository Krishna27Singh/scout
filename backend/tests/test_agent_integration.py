from collections.abc import AsyncIterator
from datetime import UTC, datetime, timedelta
from typing import Any
from uuid import uuid4

import pytest
from httpx import AsyncClient
from langgraph.checkpoint.postgres.aio import AsyncPostgresSaver
from psycopg import AsyncConnection
from psycopg.rows import dict_row
from psycopg_pool import AsyncConnectionPool
from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.agent.llm import DeterministicRuleBasedLLM
from app.api.routes.chat import get_llm_router, get_pipeline_factory
from app.api.routes.search import get_embedder
from app.core.config import Settings, get_settings
from app.db.models import Issue, Repository, UserProfile
from app.db.session import SessionFactory, get_db
from app.ingestion.embedder import DeterministicFakeEmbedder
from app.ingestion.github_client import FetchedIssue, FetchedRepoBatch, FetchedRepository
from app.ingestion.pipeline import IngestionPipeline
from app.ingestion.seed import RepoTarget
from app.main import app

pytestmark = pytest.mark.integration
_LONG_BODY = (
    "This issue describes a reproducible parser behavior and explains how it affects users. "
    "It includes enough detail for a contributor to investigate a practical fix."
)


class FakeGitHubClient:
    def __init__(self) -> None:
        self.batch: FetchedRepoBatch | None = None
        self.calls = 0

    async def fetch_repository_issues(
        self,
        owner: str,
        name: str,
        since: datetime | None = None,
        max_issues: int = 120,
    ) -> FetchedRepoBatch:
        del owner, name, since, max_issues
        self.calls += 1
        if self.batch is None:
            raise RuntimeError("No test repository batch was configured")
        return self.batch

    async def fetch_org_active_repos(self, org: str, limit: int = 10) -> list[RepoTarget]:
        del org, limit
        return []

    async def aclose(self) -> None:
        return None


async def _override_db() -> AsyncIterator[AsyncSession]:
    async with SessionFactory() as session:
        yield session


async def _postgres_checkpointer() -> tuple[
    AsyncConnectionPool[AsyncConnection[dict[str, Any]]],
    AsyncPostgresSaver,
]:
    settings = get_settings()
    conninfo = settings.database_url.replace("postgresql+psycopg://", "postgresql://")
    pool: AsyncConnectionPool[AsyncConnection[dict[str, Any]]] = AsyncConnectionPool(
        conninfo=conninfo,
        kwargs={
            "autocommit": True,
            "prepare_threshold": 0,
            "row_factory": dict_row,
        },
        open=False,
        min_size=1,
        max_size=2,
    )
    await pool.open()
    checkpointer = AsyncPostgresSaver(pool)
    await checkpointer.setup()
    return pool, checkpointer


async def test_chat_persists_preferences_and_checkpointer_history(
    client: AsyncClient,
) -> None:
    suffix = uuid4().hex[:12]
    session_key = f"agent-memory-{suffix}"
    owner = f"agent-{suffix}"
    now = datetime.now(UTC)
    embedder = DeterministicFakeEmbedder()
    repository_id: int | None = None
    pool, previous_checkpointer = await _postgres_checkpointer()
    old_checkpointer = app.state.checkpointer
    app.state.checkpointer = previous_checkpointer
    app.dependency_overrides[get_db] = _override_db
    app.dependency_overrides[get_embedder] = lambda: embedder
    app.dependency_overrides[get_llm_router] = lambda: DeterministicRuleBasedLLM()
    app.dependency_overrides[get_pipeline_factory] = lambda: _unused_pipeline_factory
    try:
        async with SessionFactory() as session:
            repository = Repository(
                github_id=int(uuid4().hex[:14], 16),
                owner=owner,
                name="parser",
                full_name=f"{owner}/parser",
                primary_language="Python",
                program_tags=["gsoc"],
                last_synced_at=now,
            )
            session.add(repository)
            await session.flush()
            repository_id = repository.id
            session.add_all(
                [
                    Issue(
                        github_id=int(uuid4().hex[:14], 16),
                        repo_id=repository.id,
                        number=1,
                        title="Fix parser math bug",
                        body=_LONG_BODY,
                        html_url=f"https://github.com/{owner}/parser/issues/1",
                        labels=["good first issue"],
                        embedding=embedder.embed_query("Fix parser math bug"),
                        github_created_at=now - timedelta(days=2),
                        github_updated_at=now,
                    ),
                    Issue(
                        github_id=int(uuid4().hex[:14], 16),
                        repo_id=repository.id,
                        number=2,
                        title="Document parser behavior",
                        body=_LONG_BODY,
                        html_url=f"https://github.com/{owner}/parser/issues/2",
                        labels=["documentation"],
                        embedding=embedder.embed_query("Document parser behavior"),
                        github_created_at=now - timedelta(days=2),
                        github_updated_at=now,
                    ),
                ]
            )
            await session.commit()

        first = await client.post(
            "/api/v1/chat",
            json={
                "session_key": session_key,
                "message": "I want Python GSoC issues, never documentation",
            },
        )
        second = await client.post(
            "/api/v1/chat",
            json={
                "session_key": session_key,
                "message": "Show me parser or math bugs",
            },
        )
        history = await client.get(f"/api/v1/chat/{session_key}/history")

        assert first.status_code == second.status_code == history.status_code == 200
        second_body = second.json()
        assert "python" in second_body["applied_filters"]["languages"]
        assert "documentation" in second_body["applied_filters"]["excluded_labels"]
        assert all(
            "documentation" not in [label.casefold() for label in match["issue"]["labels"]]
            for match in second_body["matches"]
        )
        assert len(history.json()["turns"]) == 2
        async with SessionFactory() as session:
            profile = await session.scalar(
                select(UserProfile).where(UserProfile.session_key == session_key)
            )
            assert profile is not None
            assert profile.preferred_languages == ["python"]
            assert profile.excluded_labels == ["documentation"]
    finally:
        app.dependency_overrides.pop(get_db, None)
        app.dependency_overrides.pop(get_embedder, None)
        app.dependency_overrides.pop(get_llm_router, None)
        app.dependency_overrides.pop(get_pipeline_factory, None)
        app.state.checkpointer = old_checkpointer
        await pool.close()
        if repository_id is not None:
            async with SessionFactory() as session:
                await session.execute(delete(Repository).where(Repository.id == repository_id))
                await session.execute(
                    delete(UserProfile).where(UserProfile.session_key == session_key)
                )
                await session.commit()


async def test_chat_hydrates_unknown_repo_once_and_returns_new_issue(
    client: AsyncClient,
) -> None:
    suffix = uuid4().hex[:12]
    owner = f"jit-{suffix}"
    name = "parser-project"
    full_name = f"{owner}/{name}"
    session_key = f"agent-jit-{suffix}"
    github = FakeGitHubClient()
    now = datetime.now(UTC)
    github.batch = FetchedRepoBatch(
        repository=FetchedRepository(
            github_id=int(uuid4().hex[:14], 16),
            owner=owner,
            name=name,
            name_with_owner=full_name,
            primary_language="Python",
            topics=["parser"],
            stars=42,
            is_archived=False,
            last_commit_at=now - timedelta(days=1),
            merged_prs_90d=3,
        ),
        issues=[
            FetchedIssue(
                github_id=int(uuid4().hex[:14], 16),
                number=1,
                title="Fix Python parser diagnostics",
                body=_LONG_BODY,
                url=f"https://github.com/{full_name}/issues/1",
                state="open",
                created_at=now - timedelta(days=2),
                updated_at=now,
                labels=["good first issue"],
            )
        ],
    )
    settings = Settings(_env_file=None, github_token="test-token")
    pool, checkpointer = await _postgres_checkpointer()
    old_checkpointer = app.state.checkpointer
    old_get_settings = get_settings
    app.state.checkpointer = checkpointer
    app.dependency_overrides[get_db] = _override_db
    app.dependency_overrides[get_embedder] = lambda: DeterministicFakeEmbedder()
    app.dependency_overrides[get_llm_router] = lambda: DeterministicRuleBasedLLM()
    app.dependency_overrides[get_pipeline_factory] = lambda: (
        lambda: IngestionPipeline(
            github,
            embedder=DeterministicFakeEmbedder(),
            settings=settings,
        )
    )
    import app.api.routes.chat as chat_routes

    chat_routes.get_settings = lambda: settings
    try:
        first = await client.post(
            "/api/v1/chat",
            json={
                "session_key": session_key,
                "message": f"Find Python parser issues in {full_name}",
            },
        )
        second = await client.post(
            "/api/v1/chat",
            json={
                "session_key": session_key,
                "message": f"Show parser bugs in {full_name}",
            },
        )

        assert first.status_code == second.status_code == 200
        assert first.json()["hydration"]["status"] == "hydrated"
        assert first.json()["hydration"]["triggered"] is True
        assert first.json()["hydration"]["repos_synced"] == [full_name]
        assert first.json()["hydration"]["issues_added"] == 1
        assert first.json()["matches"][0]["issue"]["repo_full_name"] == full_name
        assert second.json()["hydration"]["status"] == "not_needed"
        assert second.json()["hydration"]["triggered"] is False
        assert github.calls == 1
    finally:
        app.dependency_overrides.pop(get_db, None)
        app.dependency_overrides.pop(get_embedder, None)
        app.dependency_overrides.pop(get_llm_router, None)
        app.dependency_overrides.pop(get_pipeline_factory, None)
        chat_routes.get_settings = old_get_settings
        app.state.checkpointer = old_checkpointer
        await pool.close()
        async with SessionFactory() as session:
            await session.execute(delete(Repository).where(Repository.full_name == full_name))
            await session.execute(delete(UserProfile).where(UserProfile.session_key == session_key))
            await session.commit()


def _unused_pipeline_factory() -> IngestionPipeline:
    raise AssertionError("Hydration should not run in this test")
