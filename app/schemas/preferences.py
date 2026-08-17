"""Schemas for the authenticated user preferences API (issue #1398)."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict

from app.constants import DEFAULT_THEME

ThemeId = Literal["classic", "ink-gold", "command-center"]


class UserPreferencesResponse(BaseModel):
    """Current preference values for the authenticated user.

    Attributes:
        theme: The user's selected visual theme id. Resolves to ``classic``
            when no preference row has been persisted yet.
        user_id: Owning user id, always matching the authenticated principal.
    """

    model_config = ConfigDict(from_attributes=True)

    theme: ThemeId = DEFAULT_THEME
    user_id: int


class UserPreferencesPatchRequest(BaseModel):
    """Partial update of the authenticated user's preferences.

    Attributes:
        theme: Optional theme id to apply. When omitted, the current theme
            is left unchanged. Unknown values are rejected by validation.
    """

    theme: ThemeId | None = None
