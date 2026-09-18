"""Authenticated user preferences API (issue #1398).

Exposes a small, durable settings contract scoped to the authenticated
principal so a user's visual theme follows them across browsers and devices.
The router validates auth and payloads and delegates to the preferences
service; query construction and persistence live in the repository layer.
"""

from typing import Annotated

from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth import get_current_user
from app.database import get_db
from app.models.user import User
from app.schemas.preferences import (
    UserPreferencesPatchRequest,
    UserPreferencesResponse,
)
from app.services.preferences_service import read_user_preferences, update_user_preferences

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
    return await read_user_preferences(db, current_user.id)


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
    return await update_user_preferences(db, current_user.id, payload)