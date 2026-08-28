"""Pydantic schemas for identity reconciliation inbox."""

from __future__ import annotations

from pydantic import BaseModel, Field


class IdentityInboxCandidate(BaseModel):
    """One candidate match for an unresolved external identity."""

    external_identity_id: int
    provider: str
    comicvine_id: str | None = None
    external_url: str | None = None
    metadata_json: dict[str, object] = Field(default_factory=dict)
    status: str
    confidence: float | None = None
    evidence_source: str | None = None
    evidence_json: dict[str, object] = Field(default_factory=dict)
    rejection_reason: str | None = None


class IdentityInboxItem(BaseModel):
    """One unresolved or ambiguous external identity mapping in the inbox."""

    mapping_id: int
    issue_id: int
    thread_id: int
    thread_title: str
    issue_number: str
    status: str
    provider: str | None = None
    source_entry_summary: str = ""
    why_stopped: str = ""
    candidates: list[IdentityInboxCandidate] = Field(default_factory=list)
    created_at: float | None = None
    updated_at: float | None = None


class IdentityInboxResponse(BaseModel):
    """Paginated list of unresolved identity inbox items."""

    items: list[IdentityInboxItem] = Field(default_factory=list)
    total: int = 0
    offset: int = 0
    limit: int = 50


class IdentityInboxActionRequest(BaseModel):
    """Request to confirm, reject, defer, or skip an inbox item."""

    external_identity_id: int | None = Field(
        default=None,
        description="External identity ID to confirm (required for confirm action)",
    )
    rejection_reason: str | None = Field(
        default=None,
        max_length=500,
        description="Reason when rejecting a candidate",
    )
    search_query: str | None = Field(
        default=None,
        min_length=1,
        max_length=200,
        description="Manual search query for unresolved issues",
    )


class IdentityInboxActionResponse(BaseModel):
    """Response after performing an inbox action."""

    success: bool
    message: str
    updated_item: IdentityInboxItem | None = None


class IdentityInboxSearchResult(BaseModel):
    """One result from a manual ComicVine search for an unresolved issue."""

    comicvine_issue_id: int
    comicvine_volume_id: int | None = None
    volume_name: str | None = None
    issue_number: str | None = None
    issue_name: str | None = None
    publisher: str | None = None
    start_year: int | None = None
    site_detail_url: str | None = None
    image_url: str | None = None
    score: float | None = None
    evidence: list[str] = Field(default_factory=list)


class IdentityInboxSearchResponse(BaseModel):
    """Results from a manual ComicVine search for an unresolved issue."""

    issue_id: int
    query: str
    results: list[IdentityInboxSearchResult] = Field(default_factory=list)
    total_available: int | None = None
