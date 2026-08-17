"""User preferences schemas for request/response validation."""

from enum import StrEnum

from pydantic import BaseModel, Field


class ThemeId(StrEnum):
    """Supported theme identifiers."""

    CLASSIC = "classic"
    INK_GOLD = "ink-gold"
    COMMAND_CENTER = "command-center"


DEFAULT_THEME = ThemeId.CLASSIC


class UserPreferencesResponse(BaseModel):
    """Response schema for user preferences."""

    theme: ThemeId = Field(default=DEFAULT_THEME, description="Current theme identifier")


class UserPreferencesUpdate(BaseModel):
    """Request schema for updating user preferences."""

    theme: ThemeId = Field(description="Theme identifier to apply")
