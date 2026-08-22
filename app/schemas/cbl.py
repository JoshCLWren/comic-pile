"""Pydantic schemas for CBL API operations."""

from __future__ import annotations

from datetime import datetime
from typing import Optional

from pydantic import BaseModel, Field, field_validator


class CBLSourceResponse(BaseModel):
    """Schema for a CBL source (repository)."""

    id: int = Field(..., description="Database ID of the CBL source")
    repository: str = Field(..., description="Repository name or URL")
    revision_sha: str = Field(..., description="Git revision SHA")
    synced_at: datetime = Field(..., description="Last sync timestamp")
    created_at: datetime = Field(..., description="Creation timestamp")
    updated_at: datetime = Field(..., description="Last update timestamp")


class CBLSourceListResponse(BaseModel):
    """Schema for a CBL source list (reading list within a source)."""

    id: int = Field(..., description="Database ID of the CBL source list")
    source_id: int = Field(..., description="Foreign key to the CBL source")
    source_path: str = Field(..., description="Path within the source repository")
    name: str = Field(..., description="Human-readable name of the list")
    declared_issue_count: Optional[int] = Field(
        default=None, description="Declared issue count from the list, if known"
    )
    content_hash: str = Field(..., description="Hash of the list content")
    revision_sha: str = Field(..., description="Git revision SHA of the list")
    active: bool = Field(..., description="Whether the list is currently active")
    created_at: datetime = Field(..., description="Creation timestamp")
    updated_at: datetime = Field(..., description="Last update timestamp")


class CBLSourceWithListsResponse(CBLSourceResponse):
    """CBL source with its active lists."""

    lists: list[CBLSourceListResponse] = Field(
        default_factory=list, description="Active CBL lists in this source"
    )


class CBLUploadResponse(BaseModel):
    """Response for uploading and parsing a CBL file."""

    # We'll return a temporary identifier and the parsed entries for preview
    # For simplicity, we can return the list of books with their ComicVine IDs
    # and let the caller use them to derive a template.
    # However, we need to map to ComicPile issues for preview.
    # Instead, we can return the parsed CBLList in a serializable form.
    source_path: str = Field(..., description="Identifier for the uploaded file (filename)")
    name: str = Field(..., description="Name of the reading list")
    declared_issue_count: Optional[int] = Field(
        default=None, description="Declared issue count from the list"
    )
    content_hash: str = Field(..., description="Hash of the file content")
    books: list["CBLBookResponse"] = Field(..., description="Ordered book entries")


class CBLBookResponse(BaseModel):
    """Schema for a book entry in a CBL list."""

    position: int = Field(..., description="1-based position in the list")
    series: str = Field(..., description="Series name")
    issue_number: str = Field(..., description="Issue number within the series")
    volume_year: Optional[int] = Field(
        default=None, description="Volume year, if known"
    )
    publication_year: Optional[int] = Field(
        default=None, description="Publication year, if known"
    )
    comicvine_series_id: Optional[str] = Field(
        default=None, description="ComicVine series ID, if present in the file"
    )
    comicvine_issue_id: Optional[str] = Field(
        default=None, description="ComicVine issue ID, if present in the file"
    )


# Update forward references
CBLUploadResponse.model_rebuild()