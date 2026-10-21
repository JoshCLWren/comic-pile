"""Query helpers for the shared, ownership-free CBL catalog folder tree.

Every function in this module reads only ``cbl_source_lists`` (optionally joined
to ``cbl_sources`` for the public repository label). No reader-owned table is
joined and no network call is made, so two empty accounts always receive the
same folder tree, search results, and totals.

Folder paths are source-relative and ``/``-separated. A folder is not stored as
a row: it is derived from the path prefixes of active lists. The SQL below uses
``split_part``/``strpos`` so folder listing stays a single aggregate query even
when the catalog contains thousands of paths.

The plain source-list discovery query lives in
:mod:`app.repositories.cbl_source_repository`; this module owns only the
catalog folder navigation and paginated search used by the shared catalog API.
"""

from __future__ import annotations

from dataclasses import dataclass

from sqlalchemy import ColumnElement, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.cbl_reference import CBLSource, CBLSourceList

_LIKE_ESCAPE = "\\"


def _escape_like(value: str) -> str:
    """Escape SQL ``LIKE`` metacharacters in a literal folder or search term."""
    return (
        value.replace(_LIKE_ESCAPE, _LIKE_ESCAPE * 2)
        .replace("%", f"{_LIKE_ESCAPE}%")
        .replace("_", f"{_LIKE_ESCAPE}_")
    )


def _folder_conditions(folder: str) -> tuple[list[ColumnElement[bool]], int]:
    """Return ``WHERE`` conditions selecting one folder's subtree.

    Args:
        folder: Normalized source-relative folder path; ``""`` is the root.

    Returns:
        The active-list conditions for the folder and the zero-based prefix
        length used to inspect the remaining path.
    """
    conditions: list[ColumnElement[bool]] = [CBLSourceList.active.is_(True)]
    if not folder:
        return conditions, 0
    prefix = f"{_escape_like(folder)}/"
    conditions.append(CBLSourceList.source_path.like(f"{prefix}%", escape=_LIKE_ESCAPE))
    return conditions, len(folder) + 1


def _path_has_more_segments(folder: str) -> ColumnElement[bool]:
    """Return a predicate that is true when a path continues below ``folder``."""
    _, prefix_length = _folder_conditions(folder)
    remainder = func.substr(CBLSourceList.source_path, prefix_length + 1)
    return func.strpos(remainder, "/") > 0


@dataclass(frozen=True)
class CatalogFolderRow:
    """One immediate child folder with direct and recursive active-list counts."""

    name: str
    direct_list_count: int
    total_list_count: int


@dataclass(frozen=True)
class CatalogFolderSummary:
    """Immediate children plus counts for the requested folder itself."""

    folders: list[CatalogFolderRow]
    direct_list_count: int
    total_list_count: int


@dataclass(frozen=True)
class CatalogListPage:
    """One page of active source lists with the truthful catalog total."""

    rows: list[tuple[CBLSourceList, str]]
    total: int


async def read_cbl_catalog_folder(
    db: AsyncSession,
    *,
    folder: str,
) -> CatalogFolderSummary:
    """List immediate subfolders and active CBL counts for one folder.

    Args:
        db: Database session.
        folder: Normalized source-relative folder path; ``""`` is the root.

    Returns:
        Child folders ordered case-insensitively by name, plus direct and
        recursive list counts for the requested folder.
    """
    conditions, prefix_length = _folder_conditions(folder)
    child_segment = folder.count("/") + 2 if folder else 1
    remainder = func.substr(CBLSourceList.source_path, prefix_length + 1)
    has_more_segments = func.strpos(remainder, "/") > 0
    next_segment = func.split_part(CBLSourceList.source_path, "/", child_segment)
    path_segment_count = func.array_length(func.string_to_array(CBLSourceList.source_path, "/"), 1)

    folder_statement = (
        select(
            next_segment.label("name"),
            func.count().filter(path_segment_count == child_segment + 1).label("direct_list_count"),
            func.count().label("total_list_count"),
        )
        .where(*conditions, has_more_segments)
        .group_by(next_segment)
        .order_by(func.lower(next_segment).asc(), next_segment.asc())
    )
    folder_rows = (await db.execute(folder_statement)).all()

    direct_statement = (
        select(func.count()).select_from(CBLSourceList).where(*conditions, ~has_more_segments)
    )
    direct_list_count = int(await db.scalar(direct_statement) or 0)

    folders = [
        CatalogFolderRow(
            name=str(row.name),
            direct_list_count=int(row.direct_list_count),
            total_list_count=int(row.total_list_count),
        )
        for row in folder_rows
    ]
    return CatalogFolderSummary(
        folders=folders,
        direct_list_count=direct_list_count,
        total_list_count=direct_list_count + sum(child.total_list_count for child in folders),
    )


async def browse_cbl_source_lists(
    db: AsyncSession,
    *,
    folder: str,
    query_text: str | None,
    page: int,
    page_size: int,
) -> CatalogListPage:
    """Return one deterministic page of active lists from a folder or search.

    Args:
        db: Database session.
        folder: Normalized folder path; ignored when ``query_text`` is set.
        query_text: Optional case-insensitive name/path substring search.
        page: One-based page number.
        page_size: Maximum rows in this page.

    Returns:
        The page rows paired with their source repository, plus the total number
        of matching active lists across all pages.
    """
    conditions: list[ColumnElement[bool]] = [CBLSourceList.active.is_(True)]
    term = query_text.strip() if query_text else ""
    if term:
        pattern = f"%{_escape_like(term)}%"
        conditions.append(
            or_(
                CBLSourceList.name.ilike(pattern, escape=_LIKE_ESCAPE),
                CBLSourceList.source_path.ilike(pattern, escape=_LIKE_ESCAPE),
            )
        )
    else:
        folder_conditions, _ = _folder_conditions(folder)
        conditions.extend(folder_conditions[1:])
        conditions.append(~_path_has_more_segments(folder))

    total_statement = select(func.count()).select_from(CBLSourceList).where(*conditions)
    total = int(await db.scalar(total_statement) or 0)

    statement = (
        select(CBLSourceList, CBLSource.repository)
        .join(CBLSource, CBLSource.id == CBLSourceList.source_id)
        .where(*conditions)
        .order_by(
            CBLSourceList.name.asc(),
            CBLSourceList.source_path.asc(),
            CBLSourceList.id.asc(),
        )
        .offset((page - 1) * page_size)
        .limit(page_size)
    )
    rows = (await db.execute(statement)).all()
    return CatalogListPage(rows=[(row[0], row[1]) for row in rows], total=total)
