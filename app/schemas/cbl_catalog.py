"""Schemas for read-only CBL source catalog browsing.

The catalog is shared source data: every query reads ``cbl_sources`` /
``cbl_source_lists`` only and never joins a reader-owned table. Responses are
therefore identical for every account that can read the catalog.
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field


class CBLCatalogListItem(BaseModel):
    """One active persisted source list shown in a catalog folder or search page.

    The shape mirrors the Add-material discovery item, but it is a distinct
    model so the catalog browsing surface never shares a schema title with the
    discovery surface: two same-named models would collapse into one entry in
    the generated OpenAPI components.
    """

    id: int
    name: str
    source_path: str
    source_repository: str
    declared_issue_count: int | None
    content_hash: str
    revision_sha: str


class CBLSourceFolder(BaseModel):
    """One immediate child folder of the requested catalog folder."""

    name: str = Field(..., description="Folder name (one path segment).")
    path: str = Field(..., description="Full source-relative folder path.")
    direct_list_count: int = Field(
        ..., ge=0, description="Active CBLs stored directly in this folder."
    )
    total_list_count: int = Field(..., ge=0, description="Active CBLs anywhere below this folder.")


class CBLBreadcrumb(BaseModel):
    """One step in the folder breadcrumb, from the catalog root to the folder."""

    name: str
    path: str


class CBLFolderListingResponse(BaseModel):
    """Response for browsing one catalog folder's immediate subfolders."""

    folder: str
    breadcrumbs: list[CBLBreadcrumb]
    folders: list[CBLSourceFolder]
    direct_list_count: int = Field(
        ..., ge=0, description="Active CBLs stored directly in the requested folder."
    )
    total_list_count: int = Field(
        ..., ge=0, description="Active CBLs anywhere below the requested folder."
    )


class CBLCatalogBrowseResponse(BaseModel):
    """Paginated CBL results for one folder or one catalog-wide search."""

    scope: Literal["folder", "search"]
    folder: str
    query: str | None = None
    breadcrumbs: list[CBLBreadcrumb]
    folders: list[CBLSourceFolder]
    items: list[CBLCatalogListItem]
    page: int = Field(..., ge=1)
    page_size: int = Field(..., ge=1)
    total: int = Field(..., ge=0)
    total_pages: int = Field(..., ge=0)
    has_next: bool
    has_previous: bool


class CBLErrorDetail(BaseModel):
    """Machine-readable error code and message for a catalog failure."""

    code: str = Field(..., description="Stable machine-readable error code.")
    message: str = Field(..., description="Human-readable error message.")


class CBLErrorResponse(BaseModel):
    """Envelope for catalog error responses: ``{"detail": {"code": ..., "message": ...}}``."""

    detail: CBLErrorDetail


class CBLDatabaseUnavailableDetail(BaseModel):
    """Application-wide database acquisition error, before route execution."""

    code: Literal["database_unavailable"]
    message: str
    status: Literal["SERVICE_UNAVAILABLE"]


class CBLDatabaseUnavailableResponse(BaseModel):
    """Global retryable outage envelope used when a dependency cannot connect."""

    error: CBLDatabaseUnavailableDetail
