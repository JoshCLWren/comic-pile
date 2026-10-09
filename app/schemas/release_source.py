"""Request and response schemas for Reading Plan release sources (#3116)."""

from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, Field


class ReadingPlanReleaseSourceCreate(BaseModel):
    """Request to create or upsert one release-source subscription.

    ``external_identity_id`` must reference a *series* ``ExternalIdentity``
    that is already linked to ``thread_id`` through a confirmed
    ``ThreadExternalSeriesMapping``. ``enabled`` defaults to ``False`` so an
    ambiguous/candidate mapping can never become an automatic release source.
    """

    plan_id: int = Field(..., gt=0)
    thread_id: int = Field(..., gt=0)
    external_identity_id: int = Field(..., gt=0)
    enabled: bool = False


class ReadingPlanReleaseSourceUpdate(BaseModel):
    """Partial update for one release-source subscription.

    Only the supplied fields change; ``plan_id``, ``thread_id``, and
    ``external_identity_id`` are immutable after creation because they define
    the subscription's identity (enforced by ``uq_reading_plan_release_source``).
    """

    enabled: bool | None = None
    last_synced_at: datetime | None = None


class ReadingPlanReleaseSourceDisplay(BaseModel):
    """Non-authoritative display metadata copied from the provider identity.

    These strings are presentation hints only. They are never persisted as
    authority: the canonical identity remains the referenced
    ``ExternalIdentity`` row, and any future provider correction flows
    through the identity-repair path, not through this table.
    """

    series_name: str | None = None
    publisher: str | None = None
    start_year: int | None = None
    issue_count: int | None = None
    site_detail_url: str | None = None
    image_url: str | None = None


class ReadingPlanReleaseSourceResponse(BaseModel):
    """One persisted release-source subscription with provider identity."""

    id: int
    plan_id: int
    thread_id: int
    external_identity_id: int
    provider: str
    comicvine_volume_id: str
    enabled: bool
    last_synced_at: datetime | None
    created_at: datetime
    updated_at: datetime
    display: ReadingPlanReleaseSourceDisplay | None = None


class ReadingPlanReleaseSourceListResponse(BaseModel):
    """Paginated list of release-source subscriptions for one plan."""

    items: list[ReadingPlanReleaseSourceResponse]
    total: int
    offset: int
    limit: int
    has_next: bool
    has_prev: bool