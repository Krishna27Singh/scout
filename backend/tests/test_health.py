import pytest
from httpx import AsyncClient

from app._version import __version__
from app.api.routes import health as health_routes


async def test_health_returns_liveness_payload(client: AsyncClient) -> None:
    response = await client.get("/health")

    assert response.status_code == 200
    assert response.json() == {
        "status": "ok",
        "service": "scout",
        "version": __version__,
    }
    assert response.headers["x-request-id"]


async def test_ready_returns_503_when_database_is_degraded(
    client: AsyncClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def unavailable() -> tuple[bool, bool]:
        return False, False

    monkeypatch.setattr(health_routes, "check_db_readiness", unavailable)

    response = await client.get("/ready")

    assert response.status_code == 503
    assert response.json()["detail"]["status"] == "degraded"
