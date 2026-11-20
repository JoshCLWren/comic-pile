"""Pydantic schemas for read-only CBL source discovery and detail APIs.

These schemas describe persisted CBL provenance only. They never expose
reader-owned adoption or reconciliation state.
"""

from __future__ import annotations

from pydantic import BaseModel, Field


class CBLSourceListDiscoveryItem(BaseModel):
    """One active persisted source list that may be previewed by Add material."""

    id: int = Field(..., description="CBL source list ID")
    name: str = Field(..., description="Display name of the CBL source list")
    source_path: str = Field(..., description="Stored path of the CBL source file")
    source_repository: str = Field(..., description="Reader-safe source repository identity")
    declared_issue_count: int | None = Field(
        None, description="Issue count declared by the source list"
    )
    content_hash: str = Field(..., description="Content hash of the imported source list")
    revision_sha: str = Field(..., description="Source revision the list was imported from")


class CBLSourceEntryDetail(BaseModel):
    """One ordered source occurrence in a CBL list."""

    position: int = Field(..., ge=0, description="Source position in original CBL order")
    series_name: str = Field(..., description="Series name recorded in the CBL source")
    issue_number: str = Field(..., description="Issue number recorded in the CBL source")
    volume_year: int | None = Field(None, description="Volume year recorded in the CBL source")
    publication_year: int | None = Field(
        None, description="Publication year recorded in the CBL source"
    )
    comicvine_issue_id: str | None = Field(
        None, description="Comic Vine issue ID when the source entry has one"
    )
    comicvine_volume_id: str | None = Field(
        None, description="Comic Vine volume ID when the source entry has one"
    )


class CBLSourceListDetail(BaseModel):
    """Read-only detail for one CBL source list."""

    id: int = Field(..., description="CBL source list ID")
    name: str = Field(..., description="Display name of the CBL source list")
    source_path: str = Field(..., description="Reader-safe path of the CBL source file")
    source_repository: str = Field(..., description="Reader-safe source repository identity")
    source_ref: str = Field(..., description="Reader-safe ``repository:path`` source identity")
    declared_issue_count: int | None = Field(
        None, description="Issue count declared by the source list"
    )
    content_hash: str = Field(..., description="Content hash of the imported source list")
    revision_sha: str = Field(..., description="Source revision the list was imported from")
    entries_total: int = Field(..., ge=0, description="Total source occurrences in the list")
    entries_offset: int = Field(..., ge=0, description="Zero-based offset of the returned page")
    entries_limit: int = Field(..., ge=1, description="Maximum source occurrences per page")
    entries: list[CBLSourceEntryDetail] = Field(
        default_factory=list, description="Ordered source occurrences in this page"
    )
