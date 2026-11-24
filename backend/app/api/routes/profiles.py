from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Path, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import UserProfile
from app.db.session import get_db
from app.schemas.preferences import PreferenceUpdateRequest, UserPreferencesSchema

router = APIRouter(prefix="/api/v1/profiles", tags=["profiles"])
SessionKey = Annotated[str, Path(min_length=1, max_length=128)]


@router.get("/{session_key}", response_model=UserPreferencesSchema)
async def get_profile(
    session_key: SessionKey,
    db: Annotated[AsyncSession, Depends(get_db)],
) -> UserPreferencesSchema:
    result = await db.execute(select(UserProfile).where(UserProfile.session_key == session_key))
    profile = result.scalar_one_or_none()
    if profile is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Profile not found")
    return UserPreferencesSchema.model_validate(profile)


@router.put("/{session_key}", response_model=UserPreferencesSchema)
async def update_profile(
    session_key: SessionKey,
    preferences: PreferenceUpdateRequest,
    db: Annotated[AsyncSession, Depends(get_db)],
) -> UserPreferencesSchema:
    result = await db.execute(select(UserProfile).where(UserProfile.session_key == session_key))
    profile = result.scalar_one_or_none()
    updates = preferences.model_dump(exclude_unset=True)
    if profile is None:
        profile = UserProfile(session_key=session_key, **updates)
        db.add(profile)
    else:
        for field, value in updates.items():
            setattr(profile, field, value)
    await db.commit()
    await db.refresh(profile)
    return UserPreferencesSchema.model_validate(profile)
