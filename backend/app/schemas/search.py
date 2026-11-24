from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator

from app.schemas.preferences import ExperienceLevel

SearchMode = Literal["hybrid_rerank", "vector_only", "fts_only"]
_FILTER_LIST_FIELDS = (
    "languages",
    "repo_owners",
    "repo_full_names",
    "program_tags",
    "excluded_labels",
    "excluded_topics",
)


class SearchFilters(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)

    languages: list[str] = Field(default_factory=list)
    repo_owners: list[str] = Field(default_factory=list)
    repo_full_names: list[str] = Field(default_factory=list)
    program_tags: list[str] = Field(default_factory=list)
    excluded_labels: list[str] = Field(default_factory=list)
    excluded_topics: list[str] = Field(default_factory=list)
    experience_level: ExperienceLevel = "intermediate"
    prioritize_gsoc: bool = True

    @field_validator(*_FILTER_LIST_FIELDS, mode="before")
    @classmethod
    def normalize_filter_values(cls, value: object) -> object:
        if not isinstance(value, list):
            return value
        normalized: list[str] = []
        seen: set[str] = set()
        for item in value:
            if not isinstance(item, str):
                return value
            normalized_item = item.strip().casefold()
            if normalized_item and normalized_item not in seen:
                normalized.append(normalized_item)
                seen.add(normalized_item)
        return normalized


class SearchRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)

    query: str = Field(min_length=2, max_length=500)
    session_key: str | None = Field(default=None, min_length=1, max_length=128)
    filters: SearchFilters | None = None
    limit: int = Field(default=10, ge=1, le=25)
    mode: SearchMode = "hybrid_rerank"


class ScoreBreakdown(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)

    vector_score: float
    fts_score: float
    rrf_score: float
    maintainer_score: float
    freshness_score: float
    program_boost: float
    experience_boost: float
    final_score: float


class RetrievedIssue(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)

    id: int
    repo_full_name: str
    repo_owner: str
    repo_topics: list[str] = Field(default_factory=list)
    primary_language: str | None
    program_tags: list[str] = Field(default_factory=list)
    number: int
    title: str
    html_url: str
    labels: list[str] = Field(default_factory=list)
    comments_count: int
    maintainer_activity_score: float
    github_updated_at: datetime
    snippet: str
    scores: ScoreBreakdown


class SearchResponse(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)

    query: str
    mode: SearchMode
    applied_filters: SearchFilters
    total_candidates: int
    latency_ms: float
    results: list[RetrievedIssue] = Field(default_factory=list)
