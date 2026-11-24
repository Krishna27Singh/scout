from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator

ExperienceLevel = Literal["beginner", "intermediate", "advanced"]
_PREFERENCE_LIST_FIELDS = (
    "preferred_languages",
    "preferred_topics",
    "preferred_orgs",
    "excluded_labels",
    "excluded_topics",
)


class _PreferenceFields(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)

    preferred_languages: list[str] = Field(default_factory=list)
    preferred_topics: list[str] = Field(default_factory=list)
    preferred_orgs: list[str] = Field(default_factory=list)
    excluded_labels: list[str] = Field(default_factory=list)
    excluded_topics: list[str] = Field(default_factory=list)
    experience_level: ExperienceLevel = "intermediate"
    raw_notes: str = ""

    @field_validator(*_PREFERENCE_LIST_FIELDS, mode="before")
    @classmethod
    def normalize_preferences(cls, value: object) -> object:
        if not isinstance(value, list):
            return value
        normalized: list[str] = []
        seen: set[str] = set()
        for item in value:
            if not isinstance(item, str):
                return value
            tag = item.strip().lower()
            if tag and tag not in seen:
                normalized.append(tag)
                seen.add(tag)
        return normalized


class UserPreferencesSchema(_PreferenceFields):
    model_config = ConfigDict(extra="forbid", strict=True, from_attributes=True)


class PreferenceUpdateRequest(_PreferenceFields):
    """Fields are optional-by-omission; supplied values replace stored preferences."""
