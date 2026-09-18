"""Preferences business logic.

Owns the durable, per-user settings contract (issue #1398): transaction
boundaries and response construction live here, while query construction and
persistence live in ``app.repositories.preferences_repository``.
"""

from sqlalchemy.ext.asyncio import AsyncSession

from app.constants import DEFAULT_THEME
from app.repositories.preferences_repository import (
    get_theme,
    seed_default_theme,
    upsert_theme,
)
from app.schemas.preferences import (
    UserPreferencesPatchRequest,
    UserPreferencesResponse,
)


async def read_user_preferences(
    db: AsyncSession, user_id: int
) -> UserPreferencesResponse:
    """Read the authenticated user's preferences.

    When no preference row exists yet, server defaults (currently ``classic``)
    are resolved so existing and new users need no backfill step.

    Args:
        db: Database session.
        user_id: Owning user id for the preference row.

    Returns:
        The user's preferences, with unset values resolved to repository
        defaults.
    """
    theme = await get_theme(db, user_id)
    return UserPreferencesResponse(theme=theme or DEFAULT_THEME, user_id=user_id)


async def update_user_preferences(
    db: AsyncSession,
    user_id: int,
    payload: UserPreferencesPatchRequest,
) -> UserPreferencesResponse:
    """Apply a partial update to the authenticated user's preferences.

    A theme change is applied as a single atomic upsert so overlapping writes
    (for example a user clicking through themes faster than round-trips
    complete, issue #1872) can never race on the select-then-insert path and
    surface a unique-violation failure as an unexpected 503. When ``theme`` is
    omitted, an existing row is left unchanged and a missing row is seeded
    with the repository default.

    Args:
        db: Database session.
        user_id: Owning user id for the preference row.
        payload: Validated preference fields to update.

    Returns:
        The user's preferences after the update.
    """
    if payload.theme is not None:
        persisted_theme = await upsert_theme(db, user_id, payload.theme)
        await db.commit()
        return UserPreferencesResponse(theme=persisted_theme, user_id=user_id)

    persisted_theme = await seed_default_theme(db, user_id, DEFAULT_THEME)
    await db.commit()
    return UserPreferencesResponse(theme=persisted_theme, user_id=user_id)