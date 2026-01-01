"""Pydantic schemas for settings API."""

from datetime import datetime

from pydantic import BaseModel, Field


class SettingsResponse(BaseModel):
    """Schema for settings response."""

    id: int
    session_gap_hours: int
    start_die: int
    rating_min: float
    rating_max: float
    rating_step: float
    rating_threshold: float
    created_at: datetime
    updated_at: datetime


class UpdateSettingsRequest(BaseModel):
    """Schema for updating settings."""

    session_gap_hours: int | None = Field(None, ge=1, le=168)
    start_die: int | None = Field(None, ge=4, le=20)
    rating_min: float | None = Field(None, ge=0.0, le=5.0)
    rating_max: float | None = Field(None, ge=0.0, le=10.0)
    rating_step: float | None = Field(None, gt=0.0, le=1.0)
    rating_threshold: float | None = Field(None, ge=0.0, le=10.0)
