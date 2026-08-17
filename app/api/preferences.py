"""User preferences API endpoints."""

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import ValidationError
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth import get_current_user
from app.database import get_db
from app.models.user import User
from app.schemas.preferences import (
    DEFAULT_THEME,
    ThemeId,
    UserPreferencesResponse,
    UserPreferencesUpdate,
)

router = APIRouter()

PREFERENCES_KEY = "preferences"


def _extract_theme(user: User) -> ThemeId:
    """Extract the theme from a user's preferences dict, falling back to default."""
    prefs = getattr(user, "preferences", None) or {}
    raw_theme = prefs.get("theme")
    if raw_theme is None:
        return DEFAULT_THEME
    try:
        return ThemeId(raw_theme)
    except ValueError:
        return DEFAULT_THEME


@router.get("/me/preferences", response_model=UserPreferencesResponse)
async def get_preferences(
    current_user: Annotated[User, Depends(get_current_user)],
) -> UserPreferencesResponse:
    """Read the authenticated user's persisted preferences.

    Args:
        current_user: The authenticated user making the request.

    Returns:
        UserPreferencesResponse with the current theme.
    """
    return UserPreferencesResponse(theme=_extract_theme(current_user))


@router.patch("/me/preferences", response_model=UserPreferencesResponse)
async def update_preferences(
    body: UserPreferencesUpdate,
    current_user: Annotated[User, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> UserPreferencesResponse:
    """Update the authenticated user's persisted preferences.

    Args:
        body: The preference fields to update.
        current_user: The authenticated user making the request.
        db: Database session.

    Returns:
        UserPreferencesResponse with the updated theme.

    Raises:
        HTTPException: On invalid theme identifier.
    """
    if body.theme not in ThemeId:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=f"Invalid theme: {body.theme!r}",
        )

    existing_prefs = getattr(current_user, "preferences", None) or {}
    updated_prefs = {**existing_prefs, "theme": body.theme.value}

    current_user.preferences = updated_prefs
    db.add(current_user)
    await db.commit()
    await db.refresh(current_user)

    return UserPreferencesResponse(theme=_extract_theme(current_user))
