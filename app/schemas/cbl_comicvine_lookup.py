"""Pydantic schemas for the CBL reverse lookup by exact Comic Vine issue identity.

These schemas describe shared catalog provenance only. They never expose
reader-owned adoption, reconciliation, or read state.
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field, field_validator


class CBLComicvineOccurrenceDetail(BaseModel):
    """One source position that contains an exact Comic Vine issue identity."""

    list_id: int = Field(..., description="CBL source list ID")
    list_name: str = Field(..., description="Display name of the CBL source list")
    source_path: str = Field(..., description="Reader-safe path of the CBL source file")
    source_repository: str = Field(
        ..., description="Reader-safe source repository identity"
    )
    source_ref: str = Field(
        ..., description="Reader-safe ``repository:path`` source identity"
    )
    revision_sha: str = Field(..., description="Source revision the list was imported from")
    position: int = Field(..., ge=0, description="Source position in original CBL order")
    series_name: str = Field(..., description="Series name recorded in the CBL source")
    issue_number: str = Field(..., description="Issue number recorded in the CBL source")
    volume_year: int | None = Field(None, description="Volume year recorded in the CBL source")
    publication_year: int | None = Field(
        None, description="Publication year recorded in the CBL source"
    )
    comicvine_issue_id: str = Field(..., description="Exact Comic Vine issue ID that matched")
    comicvine_volume_id: str | None = Field(
        None,
        description="Comic Vine volume identity of the occurrence when the source has one",
    )


class CBLComicvineOccurrencePage(BaseModel):
    """One page of CBL source occurrences for an exact Comic Vine issue identity."""

    comicvine_issue_id: str = Field(..., description="Exact Comic Vine issue ID queried")
    occurrences_total: int = Field(
        ..., ge=0, description="Total matching source occurrences in the shared catalog"
    )
    lists_total: int = Field(
        ..., ge=0, description="Number of distinct source lists containing the identity"
    )
    occurrences_offset: int = Field(..., ge=0, description="Zero-based offset of the returned page")
    occurrences_limit: int = Field(..., ge=1, description="Maximum source occurrences per page")
    occurrences: list[CBLComicvineOccurrenceDetail] = Field(
        default_factory=list, description="Matching source occurrences in this page"
    )


class CBLSourceComparisonRequest(BaseModel):
    """Distinct confirmed Comic Vine issue IDs to compare against shared CBL sources."""

    comicvine_issue_ids: list[str] = Field(
        ...,
        min_length=1,
        max_length=1000,
        description="Confirmed Comic Vine issue IDs in the caller's intended order",
    )

    @field_validator("comicvine_issue_ids")
    @classmethod
    def normalize_issue_ids(cls, value: list[str]) -> list[str]:
        """Trim, reject blank IDs, and de-duplicate while preserving caller order."""
        normalized: list[str] = []
        seen: set[str] = set()
        for raw in value:
            issue_id = raw.strip()
            if not issue_id:
                raise ValueError("comicvine_issue_ids must not contain blank values")
            if len(issue_id) > 100:
                raise ValueError("comicvine_issue_ids entries must be at most 100 characters")
            if issue_id in seen:
                continue
            seen.add(issue_id)
            normalized.append(issue_id)
        return normalized


class CBLSourceComparisonMatch(BaseModel):
    """Coverage and order comparison for one shared CBL source list."""

    list_id: int = Field(..., description="CBL source list ID")
    list_name: str = Field(..., description="Display name of the CBL source list")
    source_path: str = Field(..., description="Reader-safe path of the CBL source file")
    source_repository: str = Field(
        ..., description="Reader-safe source repository identity"
    )
    source_ref: str = Field(
        ..., description="Reader-safe ``repository:path`` source identity"
    )
    revision_sha: str = Field(..., description="Source revision the list was imported from")
    declared_issue_count: int | None = Field(
        None, description="Issue count declared by the source list"
    )
    entries_total: int = Field(..., ge=0, description="Every occurrence in the source list")
    distinct_source_issues: int = Field(
        ..., ge=0, description="Distinct confirmed Comic Vine issues in the source list"
    )
    matched_input_count: int = Field(
        ..., ge=0, description="Distinct input comics found in this source list"
    )
    input_total: int = Field(..., ge=0, description="Distinct input comics compared")
    matched_occurrence_count: int = Field(
        ..., ge=0, description="Source positions that hold a matching input comic"
    )
    duplicate_match_count: int = Field(
        ...,
        ge=0,
        description="Matched positions beyond the first occurrence of each distinct input comic",
    )
    source_only_issue_count: int = Field(
        ...,
        ge=0,
        description="Distinct source comics whose exact ID is not in the input list",
    )
    input_coverage_percentage: int = Field(
        ..., ge=0, le=100, description="Percentage of distinct input comics covered"
    )
    source_coverage_percentage: int = Field(
        ..., ge=0, le=100, description="Percentage of this source's distinct comics that matched"
    )
    order_status: Literal["same_order", "reordered", "not_comparable"] = Field(
        ..., description="Relative order of matched distinct comics"
    )
    order_pair_count: int = Field(..., ge=0, description="Comparable matched comic pairs")
    order_disagreement_count: int = Field(
        ..., ge=0, description="Matched pairs whose relative order differs from the input order"
    )
    matched_input_ids: list[str] = Field(
        default_factory=list, description="Matched distinct IDs in input order"
    )
    missing_input_ids: list[str] = Field(
        default_factory=list, description="Input IDs absent from this source list"
    )
    score: int = Field(
        ..., ge=0, le=100, description="Relevance score balancing coverage, precision, and order"
    )


class CBLSourceComparisonResponse(BaseModel):
    """Ranked shared CBL source lists for one confirmed input set."""

    comicvine_issue_ids: list[str] = Field(
        default_factory=list, description="Distinct input IDs that were compared"
    )
    input_total: int = Field(..., ge=0, description="Distinct input comics compared")
    candidates_total: int = Field(
        ..., ge=0, description="Number of source lists containing at least one input comic"
    )
    candidates: list[CBLSourceComparisonMatch] = Field(
        default_factory=list, description="Ranked source list comparisons in this page"
    )


class CBLReadingListInputEntry(BaseModel):
    """One current Reading List entry and its confirmed Comic Vine identity state."""

    position: int = Field(..., ge=0, description="Current order position in the Reading List")
    issue_id: int = Field(..., description="ComicPile issue ID")
    series_name: str = Field(..., description="Reader-facing series name")
    issue_number: str = Field(..., description="Reader-facing issue number")
    comicvine_issue_id: str | None = Field(
        None, description="Confirmed Comic Vine issue ID when exactly one is confirmed"
    )
    comicvine_issue_ids: list[str] = Field(
        default_factory=list,
        description="Every confirmed Comic Vine issue ID, including conflicting IDs",
    )
    identity_status: Literal["confirmed", "missing", "conflict"] = Field(
        ..., description="Whether this entry has one usable confirmed exact identity"
    )


class CBLReadingListCandidatesResponse(BaseModel):
    """Confirmed-comic gaps plus ranked shared CBL sources for one Reading List."""

    list_id: int = Field(..., description="Owned Reading List ID")
    list_name: str = Field(..., description="Owned Reading List name")
    input_entry_count: int = Field(..., ge=0, description="Every current list entry")
    input_confirmed_total: int = Field(
        ..., ge=0, description="Distinct confirmed Comic Vine issue IDs compared"
    )
    input_missing_count: int = Field(
        ..., ge=0, description="List entries without a confirmed Comic Vine issue ID"
    )
    input_conflict_count: int = Field(
        ..., ge=0, description="List entries with conflicting confirmed Comic Vine issue IDs"
    )
    input_ids: list[str] = Field(
        default_factory=list, description="Distinct confirmed input IDs in list order"
    )
    entries: list[CBLReadingListInputEntry] = Field(
        default_factory=list, description="Every current list entry and its identity gap"
    )
    candidates_total: int = Field(
        ..., ge=0, description="Number of source lists containing at least one input comic"
    )
    candidates: list[CBLSourceComparisonMatch] = Field(
        default_factory=list, description="Ranked source list comparisons in this page"
    )
