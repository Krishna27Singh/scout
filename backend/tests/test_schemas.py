import pytest
from pydantic import ValidationError

from app.schemas.preferences import (
    PreferenceUpdateRequest,
    UserPreferencesSchema,
)


def test_preferences_normalize_and_deduplicate_values() -> None:
    preferences = UserPreferencesSchema(
        preferred_languages=["Python", " python ", "Java"],
        preferred_topics=["Web", "WEB", "  "],
        preferred_orgs=[" FastAPI ", "fastapi"],
    )

    assert preferences.preferred_languages == ["python", "java"]
    assert preferences.preferred_topics == ["web"]
    assert preferences.preferred_orgs == ["fastapi"]


def test_update_request_only_serializes_supplied_fields() -> None:
    request = PreferenceUpdateRequest(preferred_topics=["Databases"])

    assert request.model_dump(exclude_unset=True) == {"preferred_topics": ["databases"]}


@pytest.mark.parametrize(
    "payload",
    [
        {"preferred_languages": [1]},
        {"unexpected": "field"},
        {"experience_level": "expert"},
        {"raw_notes": 123},
    ],
)
def test_preferences_reject_invalid_or_unknown_values(
    payload: dict[str, object],
) -> None:
    with pytest.raises(ValidationError):
        UserPreferencesSchema.model_validate(payload)
