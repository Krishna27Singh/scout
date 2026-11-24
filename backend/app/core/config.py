from functools import lru_cache
from typing import Literal

from pydantic import field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
        case_sensitive=False,
    )

    app_env: str = "development"
    log_level: str = "INFO"
    database_url: str = "postgresql+psycopg://scout:scout@localhost:5432/scout"
    embedding_dim: int = 384
    github_token: str = ""
    embedding_model: str = "BAAI/bge-small-en-v1.5"
    embedding_cache_dir: str = ".cache/fastembed"
    ingestion_max_issues_per_repo: int = 120
    closed_issue_retention_days: int = 14
    on_demand_repo_retention_days: int = 30
    llm_provider: Literal["groq", "gemini"] = "groq"
    groq_api_key: str = ""
    groq_model: str = "llama-3.3-70b-versatile"
    gemini_api_key: str = ""
    gemini_model: str = "gemini-2.5-flash"
    llm_timeout_seconds: float = 20.0
    jit_hydration_max_issues: int = 60
    jit_hydration_max_org_repos: int = 3
    jit_hydration_stale_hours: int = 24
    cors_origins: list[str] = [
        "http://localhost:3000",
        "http://127.0.0.1:3000",
    ]

    @field_validator("database_url", mode="before")
    @classmethod
    def normalize_database_url(cls, value: str) -> str:
        if not isinstance(value, str):
            raise ValueError("database_url must be a string")
        if value.startswith("postgres://"):
            return value.replace("postgres://", "postgresql+psycopg://", 1)
        if value.startswith("postgresql://"):
            return value.replace("postgresql://", "postgresql+psycopg://", 1)
        return value

    @field_validator("log_level")
    @classmethod
    def normalize_log_level(cls, value: str) -> str:
        return value.upper()

    @field_validator(
        "llm_timeout_seconds",
        "jit_hydration_max_issues",
        "jit_hydration_max_org_repos",
        "jit_hydration_stale_hours",
    )
    @classmethod
    def require_positive_agent_limits(cls, value: float | int) -> float | int:
        if value <= 0:
            raise ValueError("agent timeout and hydration limits must be positive")
        return value


@lru_cache
def get_settings() -> Settings:
    return Settings()
