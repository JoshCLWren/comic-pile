"""Schemas for ComicVine identity resolution and metadata correction."""

from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field


class ComicVineSeriesResult(BaseModel):
    """One ComicVine series/volume from a search."""

    comicvine_volume_id: int
    name: str
    publisher: str | None = None
    start_year: int | None = None
    issue_count: int | None = None
    site_detail_url: str | None = None
    image_url: str | None = None


class ComicVineSeriesSearchResponse(BaseModel):
    """Paginated series search results using ComicVine offset semantics."""

    query: str
    results: list[ComicVineSeriesResult]
    total_available: int | None = None
    offset: int = 0
    limit: int = 10
    has_more: bool = False
    next_offset: int | None = None


class ComicVineResolvedIssue(BaseModel):
    """A ComicVine issue resolved directly from a pasted URL.

    Carries the owning series/volume metadata so the confirmation card can
    render without a separate volume search.
    """

    comicvine_issue_id: int
    series_name: str | None = None
    volume_id: int | None = None
    issue_number: str | None = None
    name: str | None = None
    cover_date: str | None = None
    store_date: str | None = None
    image_url: str | None = None
    site_detail_url: str | None = None


class ComicVineResolveResponse(BaseModel):
    """Result of resolving a correction input that may be a pasted URL.

    ``kind`` distinguishes an exact issue resolution, an exact volume
    resolution, or an ordinary title-search input. ``validation_error`` carries
    a clear inline message when the input is an unsupported/malformed URL or
    provider resolution failed, while leaving normal title search available.
    """

    input: str
    kind: Literal["issue", "volume", "search"]
    validation_error: str | None = None
    issue: ComicVineResolvedIssue | None = None
    volume: ComicVineSeriesResult | None = None
    issues: list[ComicVineIssueCandidate] = []


class ComicVineIssueCandidate(BaseModel):
    """One issue candidate from a series for identity mapping."""

    comicvine_issue_id: int
    issue_number: str | None = None
    name: str | None = None
    cover_date: str | None = None
    store_date: str | None = None
    image_url: str | None = None
    site_detail_url: str | None = None


class ComicVineSeriesIssuesResponse(BaseModel):
    """Issues within a ComicVine series."""

    comicvine_volume_id: int
    series_name: str
    issues: list[ComicVineIssueCandidate]


class IssueIdentityMapping(BaseModel):
    """One external identity mapping for a ComicPile issue."""

    external_identity_id: int
    provider: str
    comicvine_id: str
    status: str
    confidence: float | None = None
    evidence_source: str | None = None
    created_at: datetime | None = None


class IssueIdentityResponse(BaseModel):
    """Current identity state for one ComicPile issue."""

    issue_id: int
    thread_id: int
    thread_title: str
    has_confirmed_identity: bool
    comicvine_issue_id: str | None = None
    confirmed_mappings: list[IssueIdentityMapping]
    candidate_mappings: list[IssueIdentityMapping]
    has_unresolved: bool


class ConfirmIdentityRequest(BaseModel):
    """Request to confirm a specific ComicVine identity for an issue."""

    comicvine_issue_id: int = Field(..., description="ComicVine issue ID to confirm")


class ImportIssueRequest(BaseModel):
    """Request to import a ComicVine issue as a new identity-preserving thread.

    The optional reading-order placement is neighbor-anchored: the anchors are
    the thread IDs of the arc members immediately surrounding the imported
    issue in story-arc order. Anchors absent from the target order fall back
    per ``resolve_anchored_position`` rules.
    """

    title: str = Field(..., min_length=1, max_length=200)
    comicvine_issue_id: int = Field(..., gt=0, description="ComicVine issue ID to preserve")
    issue_number: str | None = Field(default=None, max_length=50)
    reading_order_id: int | None = Field(default=None, gt=0)
    anchor_before_thread_id: int | None = Field(default=None, gt=0)
    anchor_after_thread_id: int | None = Field(default=None, gt=0)


class ImportIssueResponse(BaseModel):
    """Result of an identity-preserving ComicVine issue import."""

    thread_id: int
    issue_id: int
    external_identity_id: int
    reading_order_id: int | None = None
    position: int | None = None
    total_items: int | None = None


class ReplaceIdentityRequest(BaseModel):
    """Request to replace the current confirmed identity with a new one."""

    comicvine_issue_id: int = Field(..., description="New ComicVine issue ID to confirm")
    reason: str | None = Field(
        None, max_length=500, description="Optional reason for replacement"
    )


class MetadataRefreshResponse(BaseModel):
    """Result of a provider metadata refresh request."""

    issue_id: int
    refreshed: bool
    comicvine_issue_id: str | None = None


class CanonicalCorrection(BaseModel):
    """A user-contributed canonical metadata override."""

    id: int
    field_name: str
    provider_value: str | None = None
    canonical_value: str
    provenance: str
    created_by: int
    created_at: datetime


class MetadataCorrectionRequest(BaseModel):
    """Request to apply a canonical metadata correction."""

    field_name: str = Field(..., description="Metadata field to correct")
    canonical_value: str = Field(..., description="Corrected canonical value")
    reason: str | None = Field(None, max_length=500, description="Reason for correction")


class MetadataCorrectionsResponse(BaseModel):
    """List of corrections for a ComicPile issue."""

    issue_id: int
    corrections: list[CanonicalCorrection]


class MetadataCorrectionRevertRequest(BaseModel):
    """Request to revert a canonical correction."""

    correction_id: int = Field(..., description="ID of the correction to revert")
