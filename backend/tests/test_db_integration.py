from datetime import UTC, datetime
from uuid import uuid4

import pytest
from httpx import AsyncClient
from sqlalchemy import select, text

from app.db.models import Issue, Repository
from app.db.session import SessionFactory, engine

pytestmark = pytest.mark.integration


async def test_pgvector_schema_and_cosine_search() -> None:
    async with engine.connect() as connection:
        extension_installed = await connection.scalar(
            text("SELECT EXISTS (SELECT 1 FROM pg_extension WHERE extname = 'vector')")
        )
    assert extension_installed is True

    suffix = uuid4().hex
    now = datetime.now(UTC)
    vector = [0.125] * 384
    async with SessionFactory() as session:
        repository = Repository(
            github_id=int(suffix[:15], 16),
            owner="scout-tests",
            name=f"vector-{suffix}",
            full_name=f"scout-tests/vector-{suffix}",
            primary_language="Python",
        )
        session.add(repository)
        await session.flush()

        issue = Issue(
            github_id=int(suffix[15:30], 16),
            repo_id=repository.id,
            number=1,
            title="Improve vector search",
            body="A useful test issue.",
            html_url=f"https://github.com/scout-tests/vector-{suffix}/issues/1",
            labels=["good first issue"],
            embedding=vector,
            github_created_at=now,
            github_updated_at=now,
        )
        session.add(issue)
        await session.commit()
        await session.refresh(issue)

        assert issue.search_tsv is not None
        result = await session.execute(
            select(Issue.id).order_by(Issue.embedding.cosine_distance(vector)).limit(1)
        )
        assert result.scalar_one() == issue.id
        await session.delete(issue)
        await session.delete(repository)
        await session.commit()


async def test_profile_put_get_round_trip(client: AsyncClient) -> None:
    session_key = f"phase1-{uuid4().hex}"
    put_response = await client.put(
        f"/api/v1/profiles/{session_key}",
        json={
            "preferred_languages": ["Python", "python"],
            "preferred_topics": ["Documentation"],
            "experience_level": "beginner",
        },
    )
    assert put_response.status_code == 200
    assert put_response.json()["preferred_languages"] == ["python"]

    get_response = await client.get(f"/api/v1/profiles/{session_key}")

    assert get_response.status_code == 200
    assert get_response.json()["preferred_topics"] == ["documentation"]
    assert get_response.json()["experience_level"] == "beginner"


async def test_profile_get_missing_returns_404(client: AsyncClient) -> None:
    response = await client.get(f"/api/v1/profiles/missing-{uuid4().hex}")

    assert response.status_code == 404
