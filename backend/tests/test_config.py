import pytest

from app.core.config import Settings


@pytest.mark.parametrize(
    ("url", "expected"),
    [
        (
            "postgres://user:pass@db.example/scout",
            "postgresql+psycopg://user:pass@db.example/scout",
        ),
        (
            "postgresql://user:pass@db.example/scout",
            "postgresql+psycopg://user:pass@db.example/scout",
        ),
        (
            "postgresql+psycopg://user:pass@db.example/scout",
            "postgresql+psycopg://user:pass@db.example/scout",
        ),
    ],
)
def test_database_url_uses_psycopg_driver(url: str, expected: str) -> None:
    settings = Settings(_env_file=None, database_url=url)

    assert settings.database_url == expected
