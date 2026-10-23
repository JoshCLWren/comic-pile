"""Business logic for read-only CBL source catalog browsing.

The service normalizes and validates folder/search input, derives breadcrumbs,
and maps repository rows to public response data. It never consults the current
reader: the CBL catalog is shared source data, not a per-reader index.
"""

from __future__ import annotations

from math import ceil

from sqlalchemy.ext.asyncio import AsyncSession

from app.models.cbl_reference import CBLSourceList
from app.repositories.cbl_catalog_repository import (
    browse_cbl_source_lists,
    read_cbl_catalog_folder,
)
from app.schemas.cbl_catalog import (
    CBLBreadcrumb,
    CBLCatalogBrowseResponse,
    CBLCatalogListItem,
    CBLFolderListingResponse,
    CBLSourceFolder,
)
from app.services.cbl_source_public import public_cbl_repository

MAX_FOLDER_LENGTH = 1000
MAX_SEARCH_LENGTH = 200
ROOT_BREADCRUMB_NAME = "All CBLs"


class InvalidCBLFolderPathError(ValueError):
    """Raised when a requested catalog folder path is malformed."""


class InvalidCBLSearchQueryError(ValueError):
    """Raised when a catalog search term exceeds the contract bound."""


class CBLFolderNotFoundError(LookupError):
    """Raised when a catalog folder has no active CBLs or subfolders."""


def normalize_cbl_folder_path(raw: str | None) -> str:
    """Validate and normalize a source-relative folder path.

    Args:
        raw: Folder path from the request; ``None`` means the catalog root.

    Returns:
        The canonical folder path without leading, trailing, or duplicate
        separators. Inner spaces are preserved so folder names containing
        spaces (including a trailing space) round-trip through lookups.

    Raises:
        InvalidCBLFolderPathError: If the path is too long, contains control
            characters or backslashes, or has an empty, ``.``, or ``..`` segment.
    """
    if raw is None:
        return ""
    folder = raw
    if not folder.strip():
        return ""
    if len(folder) > MAX_FOLDER_LENGTH:
        raise InvalidCBLFolderPathError(f"folder must be at most {MAX_FOLDER_LENGTH} characters")
    if "\\" in folder:
        raise InvalidCBLFolderPathError("folder must use '/' separators, not backslashes")
    if any(ord(character) < 32 for character in folder):
        raise InvalidCBLFolderPathError("folder must not contain control characters")
    segments = folder.split("/")
    if any(segment in {"", ".", ".."} for segment in segments):
        raise InvalidCBLFolderPathError("folder must not contain empty, '.' or '..' path segments")
    return folder


def build_cbl_breadcrumbs(folder: str) -> list[CBLBreadcrumb]:
    """Build root-through-folder breadcrumbs for a normalized folder path.

    Args:
        folder: Normalized source-relative folder path; ``""`` is the root.

    Returns:
        Breadcrumb entries whose ``path`` values are the cumulative folders.
    """
    breadcrumbs = [CBLBreadcrumb(name=ROOT_BREADCRUMB_NAME, path="")]
    segments = [segment for segment in folder.split("/") if segment]
    cumulative: list[str] = []
    for segment in segments:
        cumulative.append(segment)
        breadcrumbs.append(CBLBreadcrumb(name=segment, path="/".join(cumulative)))
    return breadcrumbs


def _folder_schema(folder: str, row_name: str, direct: int, total: int) -> CBLSourceFolder:
    return CBLSourceFolder(
        name=row_name,
        path=f"{folder}/{row_name}" if folder else row_name,
        direct_list_count=direct,
        total_list_count=total,
    )


def _item_schema(source_list: CBLSourceList, repository: str) -> CBLCatalogListItem:
    """Map one repository row to the public catalog item contract."""
    return CBLCatalogListItem(
        id=source_list.id,
        name=source_list.name,
        source_path=source_list.source_path,
        source_repository=public_cbl_repository(repository),
        declared_issue_count=source_list.declared_issue_count,
        content_hash=source_list.content_hash,
        revision_sha=source_list.revision_sha,
    )


async def list_cbl_catalog_folders(
    db: AsyncSession,
    *,
    folder: str | None,
) -> CBLFolderListingResponse:
    """Return immediate subfolders and active CBL counts for one folder.

    Args:
        db: Database session.
        folder: Raw source-relative folder path; ``None`` is the catalog root.

    Returns:
        The folder listing, including breadcrumbs and recursive counts.

    Raises:
        InvalidCBLFolderPathError: If the folder path is malformed.
        CBLFolderNotFoundError: If the folder contains no active CBLs or subfolders.
    """
    normalized = normalize_cbl_folder_path(folder)
    summary = await read_cbl_catalog_folder(db, folder=normalized)
    if normalized and not summary.folders and summary.direct_list_count == 0:
        raise CBLFolderNotFoundError(f"CBL folder not found: {normalized}")
    return CBLFolderListingResponse(
        folder=normalized,
        breadcrumbs=build_cbl_breadcrumbs(normalized),
        folders=[
            _folder_schema(
                normalized,
                child.name,
                child.direct_list_count,
                child.total_list_count,
            )
            for child in summary.folders
        ],
        direct_list_count=summary.direct_list_count,
        total_list_count=summary.total_list_count,
    )


async def browse_cbl_catalog(
    db: AsyncSession,
    *,
    folder: str | None,
    query: str | None,
    page: int,
    page_size: int,
) -> CBLCatalogBrowseResponse:
    """Return one page of folder contents or catalog-wide search results.

    A non-blank ``query`` searches the whole shared catalog regardless of
    ``folder``; the response then reports ``scope="search"`` with no subfolders.

    Args:
        db: Database session.
        folder: Raw source-relative folder path; ``None`` is the catalog root.
        query: Optional name/path substring search.
        page: One-based page number.
        page_size: Rows per page, bounded by the router contract.

    Returns:
        A paginated, deterministic catalog page with truthful totals.

    Raises:
        InvalidCBLFolderPathError: If the folder path is malformed.
        InvalidCBLSearchQueryError: If the search term is longer than the bound.
        CBLFolderNotFoundError: If a requested folder does not exist.
    """
    normalized = normalize_cbl_folder_path(folder)
    term = query.strip() if query else ""
    if len(term) > MAX_SEARCH_LENGTH:
        raise InvalidCBLSearchQueryError(f"query must be at most {MAX_SEARCH_LENGTH} characters")

    folders: list[CBLSourceFolder] = []
    breadcrumbs = build_cbl_breadcrumbs(normalized if not term else "")
    if not term:
        summary = await read_cbl_catalog_folder(db, folder=normalized)
        if normalized and not summary.folders and summary.direct_list_count == 0:
            raise CBLFolderNotFoundError(f"CBL folder not found: {normalized}")
        folders = [
            _folder_schema(
                normalized,
                child.name,
                child.direct_list_count,
                child.total_list_count,
            )
            for child in summary.folders
        ]

    page_result = await browse_cbl_source_lists(
        db,
        folder=normalized,
        query_text=term or None,
        page=page,
        page_size=page_size,
    )
    total_pages = ceil(page_result.total / page_size) if page_result.total else 0
    return CBLCatalogBrowseResponse(
        scope="search" if term else "folder",
        folder="" if term else normalized,
        query=term or None,
        breadcrumbs=breadcrumbs,
        folders=folders,
        items=[
            _item_schema(source_list, repository) for source_list, repository in page_result.rows
        ],
        page=page,
        page_size=page_size,
        total=page_result.total,
        total_pages=total_pages,
        has_next=page < total_pages,
        has_previous=page > 1,
    )
