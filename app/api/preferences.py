"""User preferences API endpoints."""

from typing import Annotated

from fastapi import APIRouter, Depends
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


def _extract_theme(preferences: dict | None) -> ThemeId:
    """Extract the theme from a preferences dict, falling back to default.

    Args:
        preferences: The user's preferences dict, or None.

    Returns:
        The parsed ThemeId, defaulting to ThemeId.CLASSIC.
    """
    raw_theme = (preferences or {}).get("theme")
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
    return UserPreferencesResponse(theme=_extract_theme(getattr(current_user, "preferences", None)))


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
    """
    existing_prefs = getattr(current_user, "preferences", None) or {}
    updated_prefs = {**existing_prefs, "theme": body.theme.value}
    final_theme = body.theme

    current_user.preferences = updated_prefs
    db.add(current_user)
    await db.commit()

    return UserPreferencesResponse(theme=final_theme)
