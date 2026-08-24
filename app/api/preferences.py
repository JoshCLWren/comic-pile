"""Authenticated user preferences API (issue #1398).

Exposes a small, durable settings contract scoped to the authenticated
principal so a user's visual theme follows them across browsers and devices.
"""

from datetime import UTC, datetime
from typing import Annotated

from fastapi import APIRouter, Depends
from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth import get_current_user
from app.constants import DEFAULT_THEME
from app.database import get_db
from app.models import UserPreferences
from app.models.user import User
from app.schemas.preferences import (
    UserPreferencesPatchRequest,
    UserPreferencesResponse,
)

router = APIRouter(prefix="/users/me", tags=["users"])


@router.get(
    "/preferences",
    response_model=UserPreferencesResponse,
    summary="Read the authenticated user's preferences.",
    description=(
        "Return the authenticated user's persisted preferences. When no "
        "preference row exists yet, server defaults (currently ``classic``) "
        "are resolved so existing and new users need no backfill step."
    ),
)
async def get_user_preferences(
    current_user: Annotated[User, Depends(get_current_user)],
    db: AsyncSession = Depends(get_db),
) -> UserPreferencesResponse:
    """Read the authenticated user's preferences.

    Args:
        current_user: The authenticated user making the request.
        db: Async database session.

    Returns:
        The user's preferences, with unset values resolved to repository
        defaults.
    """
    result = await db.execute(
        select(UserPreferences).where(UserPreferences.user_id == current_user.id)
    )
    preferences = result.scalar_one_or_none()
    theme = preferences.theme if preferences is not None else DEFAULT_THEME
    return UserPreferencesResponse(theme=theme, user_id=current_user.id)


def _upsert_theme_statement(user_id: int, theme: str):
    """Build an atomic insert-or-update statement for one user's theme.

    Args:
        user_id: Owning user id for the preference row.
        theme: Theme id to persist when the row is inserted or updated.

    Returns:
        A PostgreSQL upsert returning the persisted theme value.
    """
    now = datetime.now(UTC)
    return (
        pg_insert(UserPreferences)
        .values(user_id=user_id, theme=theme, updated_at=now)
        .on_conflict_do_update(
            index_elements=[UserPreferences.__table__.c.user_id],
            set_={"theme": theme, "updated_at": now},
        )
        .returning(UserPreferences.theme)
    )


@router.patch(
    "/preferences",
    response_model=UserPreferencesResponse,
    summary="Apply a partial update to the authenticated user's preferences.",
    description=(
        "Update the authenticated user's preferences. The current request "
        "shape supports the ``theme`` field; unknown theme ids are rejected."
    ),
)
async def patch_user_preferences(
    payload: UserPreferencesPatchRequest,
    current_user: Annotated[User, Depends(get_current_user)],
    db: AsyncSession = Depends(get_db),
) -> UserPreferencesResponse:
    """Apply a partial update to the authenticated user's preferences.

    A theme change is applied as a single atomic upsert so overlapping writes
    (for example a user clicking through themes faster than round-trips
    complete, issue #1872) can never race on the select-then-insert path and
    surface a unique-violation failure as an unexpected 503. When ``theme`` is
    omitted, an existing row is left unchanged and a missing row is seeded
    with the repository default.

    Args:
        payload: Validated preference fields to update.
        current_user: The authenticated user making the request.
        db: Async database session.

    Returns:
        The user's preferences after the update.
    """
    if payload.theme is not None:
        result = await db.execute(_upsert_theme_statement(current_user.id, payload.theme))
        persisted_theme = result.scalar_one()
        await db.commit()
        return UserPreferencesResponse(theme=persisted_theme, user_id=current_user.id)

    # No theme supplied: seed the default row only when absent, then read back
    # whatever is persisted without ever clobbering an existing choice.
    now = datetime.now(UTC)
    await db.execute(
        pg_insert(UserPreferences)
        .values(
            user_id=current_user.id,
            theme=DEFAULT_THEME,
            updated_at=now,
        )
        .on_conflict_do_nothing(index_elements=[UserPreferences.__table__.c.user_id])
    )
    result = await db.execute(
        select(UserPreferences.theme).where(UserPreferences.user_id == current_user.id)
    )
    persisted_theme = result.scalar_one()
    await db.commit()
    return UserPreferencesResponse(theme=persisted_theme, user_id=current_user.id)
