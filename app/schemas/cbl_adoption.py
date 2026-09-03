"""Schemas for read-only CBL adoption preview and adoption-plan calculation.

These schemas carry the stable API contract that Child B (transactional
materialization) and Child C (browser UI) consume. The preview/plan path
never creates or mutates user-owned reading state.
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field, field_validator

EntryState = Literal[
    "existing",
    "missing",
    "ambiguous",
    "excluded",
    "skipped",
    "resolved",
]

ReadStatus = Literal["read", "unread"]

AdoptionDecisionType = Literal[
    "include_entry",
    "exclude_entry",
    "exclude_series",
    "include_series",
    "override_entry",
]


class CBLSourceMetadata(BaseModel):
    """Provenance for the CBL source backing a preview."""

    source_list_id: int
    source_repository: str | None = None
    source_path: str
    declared_issue_count: int | None = None
    content_hash: str | None = None
    revision_sha: str | None = None


class CBLReadStatus(BaseModel):
    """Read state overlay from the canonical physical-issue identity."""

    read_status: ReadStatus
    read_at: str | None = None


class CBLSeriesRunGroup(BaseModel):
    """Stable grouping key so UI can apply whole-series decisions without
    stringly rebuilding identity client-side.

    ``comicvine_series_id`` is the authoritative key when available; when the
    CBL carries no ComicVine series evidence, the normalized series name plus
    volume year serve as a stable fallback.
    """

    group_key: str
    series_name: str
    volume_year: int | None = None
    comicvine_series_id: str | None = None
    entry_count: int


class CBLSourceEntryPreview(BaseModel):
    """One CBL source position with its canonical resolution and state."""

    position: int
    series_name: str
    issue_number: str
    volume_year: int | None = None
    publication_year: int | None = None
    series_run_group_key: str

    comicvine_issue_id: str | None = None
    comicvine_series_id: str | None = None

    state: EntryState
    read_status: ReadStatus | None = None
    read_at: str | None = None
    resolved_issue_id: int | None = None
    canonical_issue_id: int | None = None
    resolution_status: str | None = None
    is_duplicate_identity: bool = False


class CBLPreviewResponse(BaseModel):
    """Full read-only preview of one CBL source list for the current user."""

    source: CBLSourceMetadata
    total_positions: int
    entries: list[CBLSourceEntryPreview] = Field(default_factory=list)
    series_run_groups: list[CBLSeriesRunGroup] = Field(default_factory=list)
    first_unread_position: int | None = None
    first_unread_entry_id: int | None = None


class CBLAdoptionDecision(BaseModel):
    """One decision applied to an entry or a series/run within a source."""

    decision_type: AdoptionDecisionType
    position: int | None = None
    series_run_group_key: str | None = None

    @field_validator("position", "series_run_group_key", mode="before")
    @classmethod
    def _validate_decision_target(cls, v: object) -> object:
        """Reject None for fields that should carry a value when used."""
        if v is None:
            return None
        return v


class CBLAdoptionPlanRequest(BaseModel):
    """Decisions to apply to one CBL source list for adoption planning."""

    decisions: list[CBLAdoptionDecision] = Field(default_factory=list)


class CBLSummaryEntry(BaseModel):
    """One adopted entry in the final adopted order."""

    position: int
    series_name: str
    issue_number: str
    series_run_group_key: str
    comicvine_issue_id: str | None = None
    resolved_issue_id: int | None = None
    canonical_issue_id: int | None = None
    is_new: bool = False

    model_config = {"from_attributes": False}


class CBLMutationSummary(BaseModel):
    """Read-only mutation summary returned by the adoption-plan calculation.

    No rows are created, mutated, or deleted by the plan calculation. This
    model describes what *would* happen if the decisions were committed
    transactionally by Child B.
    """

    source_list_id: int
    total_source_positions: int
    existing_issues_reused: list[int] = Field(default_factory=list)
    missing_issues_to_be_created: list[CBLSummaryEntry] = Field(default_factory=list)
    excluded_entries: list[CBLSummaryEntry] = Field(default_factory=list)
    unresolved_skipped_entries: list[CBLSummaryEntry] = Field(default_factory=list)
    adopted_entries: list[CBLSummaryEntry] = Field(default_factory=list)
    adopted_count: int
    final_adopted_order: list[int] = Field(default_factory=list)
