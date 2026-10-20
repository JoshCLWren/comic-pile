"""Pydantic schemas for Reading Plan release sources."""

from datetime import datetime
from typing import Literal

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


class ReadingPlanReleaseCandidate(BaseModel):
    """One ComicVine volume a reader may follow for a Reading Plan thread.

    ``enableable`` is true only for a confirmed series mapping that is not
    already followed. Ambiguous and unmapped threads are reported so the
    reader is routed to mapping repair instead of being offered a volume
    whose identity is still undecided.
    """

    thread_id: int
    thread_title: str
    mapping_state: Literal["confirmed", "ambiguous", "unmapped"]
    external_identity_id: int | None = None
    provider_volume_id: str | None = None
    provider_title: str | None = None
    provider_publisher: str | None = None
    provider_start_year: int | None = None
    provider_issue_count: int | None = None
    mapping_status: str | None = None
    enableable: bool = False
    followed: bool = False
