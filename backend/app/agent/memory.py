from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import DismissedIssue, Issue, UserProfile
from app.schemas.chat import PreferenceDelta


async def _get_or_create_profile(session: AsyncSession, session_key: str) -> UserProfile:
    profile = await session.scalar(
        select(UserProfile).where(UserProfile.session_key == session_key)
    )
    if profile is not None:
        return profile

    await session.execute(
        insert(UserProfile)
        .values(session_key=session_key)
        .on_conflict_do_nothing(index_elements=[UserProfile.session_key])
    )
    profile = await session.scalar(
        select(UserProfile).where(UserProfile.session_key == session_key)
    )
    if profile is None:
        raise RuntimeError("Unable to create or load user profile")
    return profile


async def load_user_context(
    session: AsyncSession,
    session_key: str,
) -> tuple[UserProfile, set[int]]:
    profile = await _get_or_create_profile(session, session_key)
    dismissed_ids = set(
        (
            await session.scalars(
                select(DismissedIssue.issue_id).where(DismissedIssue.user_profile_id == profile.id)
            )
        ).all()
    )
    await session.commit()
    await session.refresh(profile)
    return profile, dismissed_ids


async def apply_preference_delta(
    session: AsyncSession,
    session_key: str,
    delta: PreferenceDelta,
) -> UserProfile:
    profile = await _get_or_create_profile(session, session_key)
    profile.preferred_languages = _merge_values(
        profile.preferred_languages, delta.add_languages, delta.remove_languages
    )
    profile.preferred_topics = _merge_values(profile.preferred_topics, delta.add_topics)
    profile.preferred_orgs = _merge_values(profile.preferred_orgs, delta.add_orgs)
    profile.excluded_labels = _merge_values(profile.excluded_labels, delta.add_excluded_labels)
    profile.excluded_topics = _merge_values(profile.excluded_topics, delta.add_excluded_topics)
    if delta.experience_level is not None:
        profile.experience_level = delta.experience_level
    if delta.raw_notes:
        notes = [part for part in profile.raw_notes.splitlines() if part]
        if delta.raw_notes.casefold() not in {part.casefold() for part in notes}:
            notes.append(delta.raw_notes)
            profile.raw_notes = "\n".join(notes)
    await session.commit()
    await session.refresh(profile)
    return profile


async def record_dismissal(
    session: AsyncSession,
    session_key: str,
    issue_id: int,
    reason: str | None,
) -> None:
    profile = await _get_or_create_profile(session, session_key)
    if await session.scalar(select(Issue.id).where(Issue.id == issue_id)) is None:
        raise ValueError(f"Issue {issue_id} does not exist")
    statement = insert(DismissedIssue).values(
        user_profile_id=profile.id,
        issue_id=issue_id,
        reason=reason,
    )
    await session.execute(
        statement.on_conflict_do_nothing(
            index_elements=[DismissedIssue.user_profile_id, DismissedIssue.issue_id]
        )
    )
    await session.commit()


def _merge_values(
    existing: list[str],
    additions: list[str],
    removals: list[str] | None = None,
) -> list[str]:
    remove_keys = {item.strip().casefold() for item in (removals or [])}
    values: dict[str, str] = {}
    for item in [*existing, *additions]:
        normalized = item.strip()
        key = normalized.casefold()
        if normalized and key not in remove_keys:
            values.setdefault(key, normalized.casefold())
    return list(values.values())
