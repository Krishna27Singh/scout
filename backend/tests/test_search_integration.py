from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest
from httpx import AsyncClient
from sqlalchemy import delete, func, select

from app.api.routes.search import get_embedder
from app.db.models import DismissedIssue, Issue, Repository, UserProfile
from app.db.session import SessionFactory
from app.ingestion.embedder import DeterministicFakeEmbedder
from app.main import app

pytestmark = pytest.mark.integration


async def test_search_modes_hard_filters_and_profile_dismissal(
    client: AsyncClient,
) -> None:
    suffix = uuid4().hex[:12]
    repo_owner = f"search-{suffix}"
    now = datetime.now(UTC)
    embedder = DeterministicFakeEmbedder()
    query_vector = embedder.embed_query("rust vector index")
    profile_key = f"search-profile-{suffix}"
    repo_ids: list[int] = []
    profile_id = None
    app.dependency_overrides[get_embedder] = lambda: embedder
    try:
        async with SessionFactory() as session:
            gsoc_repo = Repository(
                github_id=int(uuid4().hex[:14], 16),
                owner=repo_owner,
                name="vector-gsoc",
                full_name=f"{repo_owner}/vector-gsoc",
                primary_language="Rust",
                topics=["vector-search"],
                program_tags=["gsoc"],
                priority=1,
                maintainer_activity_score=0.9,
            )
            excluded_repo = Repository(
                github_id=int(uuid4().hex[:14], 16),
                owner=repo_owner,
                name="vector-docs",
                full_name=f"{repo_owner}/vector-docs",
                primary_language="Rust",
                topics=["Docs-Only"],
                program_tags=["gsoc"],
                priority=1,
                maintainer_activity_score=0.7,
            )
            profile = UserProfile(session_key=profile_key)
            session.add_all([gsoc_repo, excluded_repo, profile])
            await session.flush()
            repo_ids = [gsoc_repo.id, excluded_repo.id]
            profile_id = profile.id

            relevant_issue = Issue(
                github_id=int(uuid4().hex[:14], 16),
                repo_id=gsoc_repo.id,
                number=1,
                title="Improve Rust vector index scanning",
                body="Optimize vector index scans while preserving nearest-neighbor recall.",
                html_url=f"https://example.test/{suffix}/issues/1",
                labels=["good first issue"],
                embedding=query_vector,
                github_created_at=now - timedelta(days=3),
                github_updated_at=now - timedelta(days=1),
            )
            excluded_label_issue = Issue(
                github_id=int(uuid4().hex[:14], 16),
                repo_id=gsoc_repo.id,
                number=2,
                title="Documentation for Rust vector index",
                body="Document the existing vector index behavior and parameters.",
                html_url=f"https://example.test/{suffix}/issues/2",
                labels=["Documentation"],
                embedding=query_vector,
                github_created_at=now - timedelta(days=3),
                github_updated_at=now - timedelta(days=1),
            )
            excluded_topic_issue = Issue(
                github_id=int(uuid4().hex[:14], 16),
                repo_id=excluded_repo.id,
                number=3,
                title="Improve Rust vector index predicate handling",
                body="The vector index predicate should retain stable search ordering.",
                html_url=f"https://example.test/{suffix}/issues/3",
                labels=["performance"],
                embedding=query_vector,
                github_created_at=now - timedelta(days=3),
                github_updated_at=now - timedelta(days=1),
            )
            session.add_all([relevant_issue, excluded_label_issue, excluded_topic_issue])
            await session.commit()
            issue_id = relevant_issue.id

        payload = {
            "query": "rust vector index",
            "filters": {
                "repo_owners": [repo_owner.upper()],
                "program_tags": ["GSOC"],
                "excluded_labels": ["documentation"],
                "excluded_topics": ["docs-only"],
            },
            "limit": 10,
        }
        for mode in ("hybrid_rerank", "vector_only", "fts_only"):
            response = await client.post("/api/v1/search", json={**payload, "mode": mode})

            assert response.status_code == 200
            body = response.json()
            assert body["mode"] == mode
            assert body["total_candidates"] == 1
            assert [result["id"] for result in body["results"]] == [issue_id]
            assert body["results"][0]["repo_full_name"] == f"{repo_owner}/vector-gsoc"

        dismiss_response = await client.post(
            f"/api/v1/profiles/{profile_key}/dismiss",
            json={"issue_id": issue_id, "reason": "Not a match"},
        )
        duplicate_dismiss_response = await client.post(
            f"/api/v1/profiles/{profile_key}/dismiss",
            json={"issue_id": issue_id, "reason": "Repeated dismissal"},
        )
        assert dismiss_response.status_code == 204
        assert duplicate_dismiss_response.status_code == 204

        dismissed_search = await client.post(
            "/api/v1/search",
            json={**payload, "session_key": profile_key},
        )
        assert dismissed_search.status_code == 200
        assert dismissed_search.json()["results"] == []

        async with SessionFactory() as session:
            dismissed_count = await session.scalar(
                select(func.count())
                .select_from(DismissedIssue)
                .where(
                    DismissedIssue.user_profile_id == profile_id,
                    DismissedIssue.issue_id == issue_id,
                )
            )
            assert dismissed_count == 1
    finally:
        app.dependency_overrides.pop(get_embedder, None)
        if repo_ids:
            async with SessionFactory() as session:
                await session.execute(delete(Repository).where(Repository.id.in_(repo_ids)))
                if profile_id is not None:
                    await session.execute(delete(UserProfile).where(UserProfile.id == profile_id))
                await session.commit()
