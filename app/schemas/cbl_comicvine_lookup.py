"""Pydantic schemas for the CBL reverse lookup by exact Comic Vine issue identity.

These schemas describe shared catalog provenance only. They never expose
reader-owned adoption, reconciliation, or read state.
"""

from __future__ import annotations

from pydantic import BaseModel, Field


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
