import logging
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from app.schemas.preferences import ExperienceLevel, UserPreferencesSchema
from app.schemas.search import RetrievedIssue, SearchFilters

logger = logging.getLogger(__name__)

_DELTA_LIST_FIELDS = (
    "add_languages",
    "remove_languages",
    "add_topics",
    "add_orgs",
    "add_excluded_labels",
    "add_excluded_topics",
)


def normalize_target_scope(
    target_org: str | None,
    target_repo: str | None,
) -> tuple[str | None, str | None]:
    normalized_org = target_org.strip().strip("/").strip() if target_org is not None else None
    if not normalized_org:
        normalized_org = None
    elif "/" in normalized_org:
        logger.warning(
            "Ignoring invalid organization target",
            extra={"target_org": target_org},
        )
        normalized_org = None

    normalized_repo = None
    if target_repo is not None:
        candidate = target_repo.strip().strip("/")
        if candidate and "/" not in candidate and normalized_org:
            candidate = f"{normalized_org}/{candidate}"
        parts = candidate.split("/") if candidate else []
        if len(parts) == 2:
            owner, name = (part.strip().strip("/") for part in parts)
        else:
            owner, name = "", ""
        if owner and name and "/" not in owner and "/" not in name:
            normalized_repo = f"{owner}/{name}"
        else:
            logger.warning(
                "Ignoring invalid repository target",
                extra={"target_org": normalized_org, "target_repo": target_repo},
            )
    return normalized_org, normalized_repo


class PreferenceDelta(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)

    add_languages: list[str] = Field(default_factory=list)
    remove_languages: list[str] = Field(default_factory=list)
    add_topics: list[str] = Field(default_factory=list)
    add_orgs: list[str] = Field(default_factory=list)
    add_excluded_labels: list[str] = Field(default_factory=list)
    add_excluded_topics: list[str] = Field(default_factory=list)
    experience_level: ExperienceLevel | None = None
    raw_notes: str | None = Field(default=None, max_length=1000)

    @field_validator(*_DELTA_LIST_FIELDS, mode="before")
    @classmethod
    def normalize_values(cls, value: object) -> object:
        if not isinstance(value, list):
            return value
        normalized: list[str] = []
        seen: set[str] = set()
        for item in value:
            if not isinstance(item, str):
                return value
            item = item.strip().casefold()
            if item and item not in seen:
                normalized.append(item)
                seen.add(item)
        return normalized


class AgentPlan(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)

    intent: Literal["search", "update_preferences", "dismiss", "clarify"]
    search_query: str = Field(default="", max_length=1000)
    preference_delta: PreferenceDelta = Field(default_factory=PreferenceDelta)
    target_org: str | None = Field(default=None, max_length=128)
    target_repo: str | None = Field(default=None, max_length=256)
    program_tags: list[str] = Field(default_factory=list)
    override_languages: list[str] = Field(default_factory=list)
    dismiss_issue_id: int | None = Field(default=None, gt=0)
    dismiss_reason: str | None = None
    clarifying_question: str | None = None

    @field_validator("program_tags", mode="before")
    @classmethod
    def normalize_program_tags(cls, value: object) -> object:
        if not isinstance(value, list):
            return value
        if any(not isinstance(item, str) for item in value):
            return value
        return sorted({item.strip().casefold() for item in value if item.strip()})

    @field_validator("override_languages", mode="before")
    @classmethod
    def normalize_override_languages(cls, value: object) -> object:
        if not isinstance(value, list):
            return value
        if any(not isinstance(item, str) for item in value):
            return value
        return sorted({item.strip().casefold() for item in value if item.strip()})

    @model_validator(mode="before")
    @classmethod
    def normalize_target_scope_fields(cls, value: object) -> object:
        if not isinstance(value, dict):
            return value
        data = value.copy()
        target_org = data.get("target_org")
        target_repo = data.get("target_repo")
        if (target_org is not None and not isinstance(target_org, str)) or (
            target_repo is not None and not isinstance(target_repo, str)
        ):
            return value
        data["target_org"], data["target_repo"] = normalize_target_scope(
            target_org,
            target_repo,
        )
        return data


class GroundedMatch(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)

    issue: RetrievedIssue
    match_reason: str = Field(min_length=1, max_length=500)


class IssueRationale(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)

    issue_id: int = Field(gt=0)
    match_reason: str = Field(min_length=1, max_length=500)


class AgentSynthesis(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)

    assistant_message: str = Field(min_length=1, max_length=1000)
    rationales: list[IssueRationale] = Field(default_factory=list)


class HydrationReport(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)

    triggered: bool = False
    scope: str | None = None
    repos_synced: list[str] = Field(default_factory=list)
    issues_added: int = Field(default=0, ge=0)
    status: Literal["not_needed", "hydrated", "skipped_no_token", "failed"] = "not_needed"


class ChatRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)

    session_key: str = Field(min_length=2, max_length=128)
    message: str = Field(min_length=2, max_length=1000)
    limit: int = Field(default=5, ge=1, le=15)
    prioritize_gsoc: bool = True


class ScoutChatResponse(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)

    session_key: str
    intent: str
    assistant_message: str
    matches: list[GroundedMatch] = Field(default_factory=list)
    applied_filters: SearchFilters
    preferences: UserPreferencesSchema
    hydration: HydrationReport
    tool_trace: list[str] = Field(default_factory=list)
    provider_used: str
    latency_ms: float


class ChatHistoryItem(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)

    user_message: str
    assistant_message: str
    intent: str


class ChatHistoryResponse(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)

    session_key: str
    turns: list[ChatHistoryItem] = Field(default_factory=list)
