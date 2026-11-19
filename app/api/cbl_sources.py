"""Read-only discovery of persisted CBL source lists for Reading Plans."""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth import get_current_user
from app.database import get_db
from app.models.user import User
from app.schemas.cbl_source import (
    CBLSourceEntryDetail,
    CBLSourceListDetail,
    CBLSourceListDiscoveryItem,
)
from app.schemas.reading_graph_preview import (
    ReadingGraphPreview,
    ReadingGraphPreviewRequest,
)
from app.services.cbl_source_service import (
    get_cbl_source_list_preview,
    list_cbl_source_previews,
)
from app.services.reading_graph_preview_service import preview_reading_graph

router = APIRouter(prefix="/issue-identity", tags=["issue-identity"])

DEFAULT_SOURCE_LIST_ENTRY_LIMIT = 1000
MAX_SOURCE_LIST_ENTRY_LIMIT = 2000


@router.get("/cbl-sources", response_model=list[CBLSourceListDiscoveryItem])
async def discover_cbl_source_lists(
    current_user: Annotated[User, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
    q: Annotated[str | None, Query(max_length=200)] = None,
    limit: Annotated[int, Query(ge=1, le=100)] = 25,
) -> list[CBLSourceListDiscoveryItem]:
    """Return bounded active CBL lists for the Reading Plan Add-material flow.

    Args:
        current_user: Authenticated reader.
        db: Async database session.
        q: Optional case-insensitive match against list name or source path.
        limit: Maximum number of lists to return.

    Returns:
        Bounded summaries of the matching active CBL source lists.
    """
    del current_user
    summaries = await list_cbl_source_previews(db, query_text=q, limit=limit)
    return [
        CBLSourceListDiscoveryItem(
            id=summary.id,
            name=summary.name,
            source_path=summary.source_path,
            source_repository=summary.source_repository,
            declared_issue_count=summary.declared_issue_count,
            content_hash=summary.content_hash,
            revision_sha=summary.revision_sha,
        )
        for summary in summaries
    ]


@router.get("/cbl-sources/{list_id}", response_model=CBLSourceListDetail)
async def get_cbl_source_list(
    list_id: int,
    current_user: Annotated[User, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
    offset: Annotated[int, Query(ge=0)] = 0,
    limit: Annotated[int, Query(ge=1, le=MAX_SOURCE_LIST_ENTRY_LIMIT)] = (
        DEFAULT_SOURCE_LIST_ENTRY_LIMIT
    ),
) -> CBLSourceListDetail:
    """Return every ordered source occurrence for one CBL list (read-only).

    Source occurrences keep their original position, including repeated
    positions for duplicated issues. Large lists are returned as a bounded page
    so no list is silently truncated; ``entries_total`` reports the full count
    so callers can page through every occurrence.

    Args:
        list_id: CBL source list identifier.
        current_user: Authenticated reader.
        db: Async database session.
        offset: Zero-based index of the first returned source occurrence.
        limit: Maximum number of source occurrences to return.

    Returns:
        One CBL source list with its ordered source occurrences.

    Raises:
        HTTPException: 404 when the list does not exist or is inactive.
    """
    del current_user
    preview = await get_cbl_source_list_preview(
        db,
        list_id=list_id,
        offset=offset,
        limit=limit,
    )
    if preview is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="CBL source list not found",
        )
    return CBLSourceListDetail(
        id=preview.id,
        name=preview.name,
        source_path=preview.source_path,
        source_repository=preview.source_repository,
        source_ref=preview.source_ref,
        declared_issue_count=preview.declared_issue_count,
        content_hash=preview.content_hash,
        revision_sha=preview.revision_sha,
        entries_total=preview.entries_total,
        entries_offset=preview.entries_offset,
        entries_limit=preview.entries_limit,
        entries=[
            CBLSourceEntryDetail(
                position=entry.position,
                series_name=entry.series_name,
                issue_number=entry.issue_number,
                volume_year=entry.volume_year,
                publication_year=entry.publication_year,
                comicvine_issue_id=entry.comicvine_issue_id,
                comicvine_volume_id=entry.comicvine_volume_id,
            )
            for entry in preview.entries
        ],
    )


@router.post(
    "/cbl/{list_id}/reading-graph-preview",
    response_model=ReadingGraphPreview,
)
async def preview_cbl_reading_graph(
    list_id: int,
    payload: ReadingGraphPreviewRequest,
    current_user: Annotated[User, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> ReadingGraphPreview:
    """Preview the prospective reading graph for a CBL selection (read-only).

    The graph comes from the same Option E evaluator and cycle validator that
    execute the reader's saved lists. It never writes list membership, issue
    status, or an overlap decision.

    Args:
        list_id: Shared CBL source list being adopted or updated.
        payload: Included source positions, prior answers, and optional list
            to preview as updated instead of newly added.
        current_user: Authenticated reader whose existing lists are included.
        db: Async database session for the request.

    Returns:
        Prospective series nodes, overlap questions with both choice effects,
        the issue directory with active blockers, and any cycle rejection.
    """
    return await preview_reading_graph(
        db,
        user_id=current_user.id,
        source_list_id=list_id,
        request=payload,
    )
