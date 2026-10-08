"""Pydantic schemas for Reading Plan release sources."""

from datetime import datetime

from pydantic import BaseModel, Field


class ReleaseSourceCreate(BaseModel):
    """Create a release source subscription."""

    plan_id: int = Field(..., gt=0)
    thread_id: int = Field(..., gt=0)
    external_identity_id: int = Field(..., gt=0)


class ReleaseSourceUpdate(BaseModel):
    """Update a release source (enable/disable)."""

    enabled: bool


class ReleaseSourceResponse(BaseModel):
    """A release source with provider display metadata."""

    id: int
    plan_id: int
    thread_id: int
    external_identity_id: int
    provider: str
    provider_volume_id: str
    provider_title: str | None
    enabled: bool
    last_synced_at: datetime | None
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}
