"""Pydantic schemas for CBL adoption preview and planning API."""

from __future__ import annotations

from datetime import datetime
from typing import Annotated

from pydantic import BaseModel, Field

from app.schemas.shared_types import SourceBackedDecision, SourceBackedStatus


class CBLPreviewEntry(BaseModel):
    """One CBL source position with resolution and read context."""

    cbl_position: int = Field(..., ge=0, description="Source position in CBL order")
    series_name: str = Field(..., min_length=1, description="Series name from CBL")
    issue_number: str = Field(..., min_length=1, description="Issue number from CBL")
    comicvine_issue_id: str | None = Field(
        None, description="ComicVine issue ID if available"
    )
    external_issue_identity_id: int | None = Field(
        None, description="External identity reference ID"
    )
    external_series_identity_id: int | None = Field(
        None, description="External series identity reference ID"
    )

    resolved_issue_id: int | None = Field(
        None, description="Canonical Issue ID if resolved"
    )
    canonical_issue_id: int | None = Field(
        None, description="Canonical Issue ID for duplicate identities"
    )
    resolution_status: SourceBackedStatus = Field(
        ..., description="Resolution status for this CBL entry"
    )
    is_duplicate_identity: bool = Field(
        False, description="Whether this is a duplicate identity"
    )

    read_status: str = Field("unread", description="Read status (read/unread)")
    read_at: datetime | None = Field(None, description="When the issue was read")
    rating: float | None = Field(None, ge=0, le=5, description="User rating")
    events: list[dict[str, object]] = Field(
        default_factory=list, description="Historical events for this issue"
    )

    cbl_entry_id: int = Field(..., description="Internal CBL source entry ID")
    volume_year: int | None = Field(None, description="Volume year from CBL")
    publication_year: int | None = Field(None, description="Publication year from CBL")


class CBLPreviewResponse(BaseModel):
    """Read-only preview of a CBL source list for a user."""

    list_id: int = Field(..., description="CBL source list ID")
    list_name: str = Field(..., min_length=1, description="Name of the CBL list")
    source_path: str = Field(..., description="Path to the source CBL file")
    declared_issue_count: int | None = Field(
        None, description="Number of issues declared in the source"
    )
    source_repository: str | None = Field(None, description="Repository URL")

    positions: list[CBLPreviewEntry] = Field(
        ..., description="All CBL positions in source order"
    )

    total_positions: int = Field(..., ge=0, description="Total number of source positions")
    resolved_count: int = Field(..., ge=0, description="Number of resolved entries")
    unresolved_count: int = Field(..., ge=0, description="Number of unresolved entries")
    ambiguous_count: int = Field(..., ge=0, description="Number of ambiguous entries")
    duplicate_identity_groups: int = Field(..., ge=0, description="Number of duplicate identity groups")

    first_unread_position: int | None = Field(
        None, description="Position of the first unread entry"
    )
    first_unread_entry: CBLPreviewEntry | None = Field(
        None, description="First unread entry in source order"
    )


class SeriesDecision(BaseModel):
    """Series-level decision for CBL adoption."""

    series_name: str = Field(..., min_length=1, description="Series name")
    decision: SourceBackedDecision = Field(
        ..., description="Include or exclude this entire series"
    )


class EntryOverride(BaseModel):
    """Individual entry override of a series decision."""

    cbl_position: int = Field(..., ge=0, description="Position to override")
    decision: SourceBackedDecision = Field(
        ..., description="Decision for this specific entry"
    )


class CBLPlanCalculationRequest(BaseModel):
    """Reader decisions for selective CBL adoption."""

    entry_decisions: dict[int, SourceBackedDecision] = Field(
        default_factory=dict,
        description="Decisions per entry (cbl_position -> decision)",
    )

    series_decisions: list[SeriesDecision] = Field(
        default_factory=list,
        description="Series-level inclusion/exclusion decisions",
    )

    series_overrides: list[EntryOverride] = Field(
        default_factory=list,
        description="Individual entry overrides of series decisions",
    )


class CBLProposedEntry(BaseModel):
    """Entry that will be included in the adopted source order."""

    cbl_position: int = Field(..., ge=0, description="Source position in CBL")
    series_name: str = Field(..., min_length=1, description="Series name")
    issue_number: str = Field(..., min_length=1, description="Issue number")
    resolved_issue_id: int | None = Field(
        None, description="Resolved canonical Issue ID (None for missing)"
    )
    existing_issue_id: int | None = Field(
        None, description="Existing issue to reuse (None if new issue)"
    )


class CBLPlannedAction(BaseModel):
    """Planned action for a CBL entry during adoption."""

    action_type: str = Field(..., description="Type of action (create_issue, reuse_issue, exclude)")
    cbl_position: int = Field(..., ge=0, description="Source position")
    series_name: str = Field(..., min_length=1, description="Series name")
    issue_number: str = Field(..., min_length=1, description="Issue number")
    target_issue_id: int | None = Field(None, description="Target issue ID if applicable")


class CBLPlanCalculationResponse(BaseModel):
    """Adoption plan without materializing changes."""

    proposed_entries: list[CBLProposedEntry] = Field(
        ..., description="Entries to be adopted"
    )

    planned_actions: list[CBLPlannedAction] = Field(
        ..., description="Actions that would occur on commit"
    )

    adopted_count: int = Field(..., ge=0, description="Number of entries to adopt")
    adopted_positions: list[int] = Field(..., description="Positions of adopted entries")
    excluded_positions: list[int] = Field(..., description="Positions of excluded entries")
    unresolved_positions: list[int] = Field(..., description="Positions of unresolved entries")

    warnings: list[str] = Field(default_factory=list, description="Validation warnings")

    source_backed_order: list[CBLProposedEntry] = Field(
        ..., description="Source-backed order for adopted entries"
    )