"""Authenticated user preferences API (issue #1398).

Exposes a small, durable settings contract scoped to the authenticated
principal so a user's visual theme follows them across browsers and devices.
"""

from typing import Annotated

from fastapi import APIRouter, Depends
from sqlalchemy import select
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

    Args:
        payload: Validated preference fields to update.
        current_user: The authenticated user making the request.
        db: Async database session.

    Returns:
        The user's preferences after the update.
    """
    result = await db.execute(
        select(UserPreferences).where(UserPreferences.user_id == current_user.id)
    )
    preferences = result.scalar_one_or_none()
    if preferences is None:
        preferences = UserPreferences(user_id=current_user.id, theme=DEFAULT_THEME)
        db.add(preferences)

    if payload.theme is not None:
        preferences.theme = payload.theme

    # Materialize the scalar before commit to avoid MissingGreenlet when
    # reading attributes after the session expires/committed state.
    persisted_theme = preferences.theme
    await db.commit()
    return UserPreferencesResponse(theme=persisted_theme, user_id=current_user.id)
