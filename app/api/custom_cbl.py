"""Authenticated authoring and Reading Plan application for custom CBL lists."""

from __future__ import annotations

from datetime import datetime
from typing import Annotated

from fastapi import APIRouter, Depends, Query, Response, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth import get_current_user
from app.database import get_db
from app.models.user import User
from app.schemas.custom_cbl import (
    CustomCBLApplyRequest,
    CustomCBLApplyResponse,
    CustomCBLIssueSearchResult,
    CustomCBLListItem,
    CustomCBLResponse,
    CustomCBLWrite,
    OverlapDecisionSetResponse,
    OverlapDecisionWrite,
)
from app.schemas.reading_list_reader import ReadingListReaderResponse
from app.services.reading_list_reader import get_reading_list_reader
from app.services.reading_overlap_decisions import (
    get_overlap_decision_set,
    remove_overlap_decision,
    save_overlap_decision,
)
from app.services.custom_cbl import (
    apply_custom_cbl_for_user,
    create_custom_cbl_for_user,
    delete_custom_cbl_for_user,
    export_custom_cbl_for_user,
    get_custom_cbl_response,
    list_custom_cbl_responses,
    search_custom_cbl_issue_responses,
    update_custom_cbl_for_user,
)

router = APIRouter(prefix="/custom-cbls", tags=["custom-cbls"])


@router.get("", response_model=list[CustomCBLListItem])
async def list_custom_cbl_lists(
    current_user: Annotated[User, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> list[CustomCBLListItem]:
    """List the authenticated user's editable custom CBLs."""
    return await list_custom_cbl_responses(db, user_id=current_user.id)


@router.get("/issue-search", response_model=list[CustomCBLIssueSearchResult])
async def search_custom_cbl_issues(
    current_user: Annotated[User, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
    q: Annotated[str, Query(max_length=200)] = "",
    limit: Annotated[int, Query(ge=1, le=100)] = 30,
) -> list[CustomCBLIssueSearchResult]:
    """Search only the user's canonical issue library for custom-list membership."""
    return await search_custom_cbl_issue_responses(
        db,
        user_id=current_user.id,
        query=q,
        limit=limit,
    )


@router.post("", response_model=CustomCBLResponse, status_code=status.HTTP_201_CREATED)
async def create_custom_cbl(
    payload: CustomCBLWrite,
    current_user: Annotated[User, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> CustomCBLResponse:
    """Create an editable CBL from real issues without creating synthetic threads."""
    return await create_custom_cbl_for_user(
        db,
        user_id=current_user.id,
        name=payload.name,
        description=payload.description,
        issue_ids=payload.issue_ids,
        checkpoint_issue_ids=payload.checkpoint_issue_ids,
        checkpoint_targets=payload.checkpoint_targets,
        mode=payload.mode,
        entry_intents=payload.entry_intents,
        confirmed_predecessor_changes=payload.confirmed_predecessor_changes,
    )


@router.get("/{list_id}", response_model=CustomCBLResponse)
async def get_custom_cbl(
    list_id: int,
    current_user: Annotated[User, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> CustomCBLResponse:
    """Return one owned custom CBL."""
    return await get_custom_cbl_response(
        db,
        user_id=current_user.id,
        list_id=list_id,
    )


@router.put("/{list_id}", response_model=CustomCBLResponse)
async def update_custom_cbl(
    list_id: int,
    payload: CustomCBLWrite,
    current_user: Annotated[User, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> CustomCBLResponse:
    """Replace custom CBL metadata and exact ordered membership atomically."""
    return await update_custom_cbl_for_user(
        db,
        user_id=current_user.id,
        list_id=list_id,
        name=payload.name,
        description=payload.description,
        issue_ids=payload.issue_ids,
        checkpoint_issue_ids=payload.checkpoint_issue_ids,
        checkpoint_targets=payload.checkpoint_targets,
        mode=payload.mode,
        entry_intents=payload.entry_intents,
        confirmed_predecessor_changes=payload.confirmed_predecessor_changes,
    )


@router.delete("/{list_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_custom_cbl(
    list_id: int,
    current_user: Annotated[User, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> Response:
    """Delete one user-owned custom CBL without touching its comics or Reading Plans."""
    await delete_custom_cbl_for_user(
        db,
        user_id=current_user.id,
        list_id=list_id,
    )
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.get("/{list_id}/export")
async def export_custom_cbl(
    list_id: int,
    current_user: Annotated[User, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> Response:
    """Export one custom list as a portable .cbl XML document."""
    exported = await export_custom_cbl_for_user(
        db,
        user_id=current_user.id,
        list_id=list_id,
    )
    return Response(
        content=exported.content,
        media_type="application/xml",
        headers={"Content-Disposition": f'attachment; filename="{exported.filename}"'},
    )


@router.post(
    "/{list_id}/reading-plans/{plan_id}:apply",
    response_model=CustomCBLApplyResponse,
)
async def apply_custom_cbl(
    list_id: int,
    plan_id: int,
    payload: CustomCBLApplyRequest,
    current_user: Annotated[User, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> CustomCBLApplyResponse:
    """Explicitly merge one custom CBL into an existing canonical Reading Plan."""
    return await apply_custom_cbl_for_user(
        db,
        user_id=current_user.id,
        list_id=list_id,
        plan_id=plan_id,
        lane_id=payload.lane_id,
        expected_updated_at=payload.expected_updated_at,
    )


@router.get("/{list_id}/reader")
async def read_custom_cbl(
    list_id: int,
    current_user: Annotated[User, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> ReadingListReaderResponse:
    """Explain the complete current list using the same authority as Roll."""
    return await get_reading_list_reader(db, user_id=current_user.id, list_id=list_id)


@router.get("/{list_id}/overlap-decisions", response_model=OverlapDecisionSetResponse)
async def read_custom_cbl_overlap_decisions(
    list_id: int,
    current_user: Annotated[User, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> OverlapDecisionSetResponse:
    """Return one owned Reading List's overlap decisions and version token.

    Args:
        list_id: Identifier of the Reading List to read.
        current_user: Authenticated reader making the request.
        db: Database session for the request.

    Returns:
        The list's saved overlap decisions, the current version token, and
        the reader's selectable volume candidates for new decisions.

    Raises:
        HTTPException: With status 404 when the reader does not own the list.
    """
    return await get_overlap_decision_set(db, user_id=current_user.id, list_id=list_id)


@router.put("/{list_id}/overlap-decisions", response_model=OverlapDecisionSetResponse)
async def save_custom_cbl_overlap_decision(
    list_id: int,
    payload: OverlapDecisionWrite,
    current_user: Annotated[User, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> OverlapDecisionSetResponse:
    """Save one reader-approved overlap choice inside an owned Reading List.

    Args:
        list_id: Identifier of the Reading List to update.
        payload: The overlap choice to save, naming two exact Comic Vine volumes.
        current_user: Authenticated reader making the request.
        db: Database session for the request.

    Returns:
        The list's updated decision set and version token.

    Raises:
        HTTPException: With status 404 for a foreign list, 409 for a stale
            version token, and 422 for an unusable or cyclic choice.
    """
    return await save_overlap_decision(
        db,
        user_id=current_user.id,
        list_id=list_id,
        continuing_volume_id=payload.continuing_volume_id,
        waiting_volume_id=payload.waiting_volume_id,
        expected_updated_at=payload.expected_updated_at,
    )


@router.delete(
    "/{list_id}/overlap-decisions/{decision_id}",
    response_model=OverlapDecisionSetResponse,
)
async def delete_custom_cbl_overlap_decision(
    list_id: int,
    decision_id: int,
    current_user: Annotated[User, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
    expected_updated_at: Annotated[datetime | None, Query()] = None,
) -> OverlapDecisionSetResponse:
    """Remove one reader-approved overlap choice from an owned Reading List.

    Args:
        list_id: Identifier of the Reading List to update.
        decision_id: Identifier of the overlap decision to remove.
        current_user: Authenticated reader making the request.
        db: Database session for the request.
        expected_updated_at: Decision version token the client last read. None
            skips the concurrency check.

    Returns:
        The list's updated decision set and version token.

    Raises:
        HTTPException: With status 404 for a foreign list or unknown decision,
            409 for a stale version token, and 422 when removing the choice
            would make the reader's constraint graph cyclic.
    """
    return await remove_overlap_decision(
        db,
        user_id=current_user.id,
        list_id=list_id,
        decision_id=decision_id,
        expected_updated_at=expected_updated_at,
    )
