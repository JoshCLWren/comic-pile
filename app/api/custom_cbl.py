"""Authenticated authoring and Reading Plan application for custom CBL lists."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Annotated

from fastapi import APIRouter, Depends, Query, Response, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.continuity_rule import _refresh_blocked_state
from app.auth import get_current_user
from app.database import get_db
from app.models.continuity_plan import ContinuityPlan
from app.models.custom_cbl import CustomCBLList
from app.models.user import User
from app.schemas.continuity_plan import ContinuityPlanResponse
from app.schemas.custom_cbl import (
    CustomCBLApplyRequest,
    CustomCBLApplyResponse,
    CustomCBLEntryResponse,
    CustomCBLIssueSearchResult,
    CustomCBLListItem,
    CustomCBLResponse,
    CustomCBLWrite,
)
from app.services.custom_cbl import (
    apply_custom_cbl_to_plan,
    export_custom_cbl_xml,
    get_owned_custom_cbl,
    list_custom_cbls,
    load_custom_cbl_entries,
    replace_custom_cbl_entries,
    search_owned_issues,
)

router = APIRouter(prefix="/custom-cbls", tags=["custom-cbls"])


def _plan_response(plan: ContinuityPlan) -> ContinuityPlanResponse:
    """Serialize one persisted Reading Plan."""
    return ContinuityPlanResponse(
        id=plan.id,
        user_id=plan.user_id,
        name=plan.name,
        ordering_mode=plan.ordering_mode,
        lanes=plan.lanes_json or [],
        nodes=plan.nodes_json or [],
        created_at=plan.created_at,
        updated_at=plan.updated_at,
    )


async def _full_response(db: AsyncSession, row: CustomCBLList) -> CustomCBLResponse:
    """Resolve list membership into a full API representation."""
    entries = await load_custom_cbl_entries(db, list_id=row.id)
    return CustomCBLResponse(
        id=row.id,
        user_id=row.user_id,
        name=row.name,
        description=row.description,
        issue_count=len(entries),
        created_at=row.created_at,
        updated_at=row.updated_at,
        entries=[
            CustomCBLEntryResponse(
                id=entry.id,
                position=entry.position,
                issue_id=entry.issue_id,
                thread_id=entry.thread_id,
                series_name=entry.series_name,
                issue_number=entry.issue_number,
                status=entry.status,
            )
            for entry in entries
        ],
    )


@router.get("", response_model=list[CustomCBLListItem])
async def list_custom_cbl_lists(
    current_user: Annotated[User, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> list[CustomCBLListItem]:
    """List the authenticated user's editable custom CBLs."""
    rows = await list_custom_cbls(db, user_id=current_user.id)
    return [
        CustomCBLListItem(
            id=row.id,
            name=row.name,
            description=row.description,
            issue_count=count,
            updated_at=row.updated_at,
        )
        for row, count in rows
    ]


@router.get("/issue-search", response_model=list[CustomCBLIssueSearchResult])
async def search_custom_cbl_issues(
    current_user: Annotated[User, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
    q: Annotated[str, Query(max_length=200)] = "",
    limit: Annotated[int, Query(ge=1, le=100)] = 30,
) -> list[CustomCBLIssueSearchResult]:
    """Search only the user's canonical issue library for custom-list membership."""
    rows = await search_owned_issues(db, user_id=current_user.id, query=q, limit=limit)
    return [
        CustomCBLIssueSearchResult(
            issue_id=issue.id,
            thread_id=thread.id,
            series_name=thread.title,
            issue_number=issue.issue_number,
            status=issue.status,
        )
        for issue, thread in rows
    ]


@router.post("", response_model=CustomCBLResponse, status_code=status.HTTP_201_CREATED)
async def create_custom_cbl(
    payload: CustomCBLWrite,
    current_user: Annotated[User, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> CustomCBLResponse:
    """Create an editable CBL from real issues without creating synthetic threads."""
    row = CustomCBLList(
        user_id=current_user.id,
        name=payload.name.strip(),
        description=payload.description.strip() if payload.description else None,
    )
    db.add(row)
    await db.flush()
    await replace_custom_cbl_entries(
        db,
        user_id=current_user.id,
        list_row=row,
        issue_ids=payload.issue_ids,
    )
    await db.commit()
    await db.refresh(row)
    return await _full_response(db, row)


@router.get("/{list_id}", response_model=CustomCBLResponse)
async def get_custom_cbl(
    list_id: int,
    current_user: Annotated[User, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> CustomCBLResponse:
    """Return one owned custom CBL."""
    row = await get_owned_custom_cbl(db, user_id=current_user.id, list_id=list_id)
    return await _full_response(db, row)


@router.put("/{list_id}", response_model=CustomCBLResponse)
async def update_custom_cbl(
    list_id: int,
    payload: CustomCBLWrite,
    current_user: Annotated[User, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> CustomCBLResponse:
    """Replace custom CBL metadata and exact ordered membership atomically."""
    row = await get_owned_custom_cbl(db, user_id=current_user.id, list_id=list_id)
    row.name = payload.name.strip()
    row.description = payload.description.strip() if payload.description else None
    row.updated_at = datetime.now(UTC)
    await replace_custom_cbl_entries(
        db,
        user_id=current_user.id,
        list_row=row,
        issue_ids=payload.issue_ids,
    )
    await db.commit()
    await db.refresh(row)
    return await _full_response(db, row)


@router.delete("/{list_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_custom_cbl(
    list_id: int,
    current_user: Annotated[User, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> Response:
    """Delete one user-owned custom CBL without touching its comics or Reading Plans."""
    row = await get_owned_custom_cbl(db, user_id=current_user.id, list_id=list_id)
    await db.delete(row)
    await db.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.get("/{list_id}/export")
async def export_custom_cbl(
    list_id: int,
    current_user: Annotated[User, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> Response:
    """Export one custom list as a portable .cbl XML document."""
    row = await get_owned_custom_cbl(db, user_id=current_user.id, list_id=list_id)
    entries = await load_custom_cbl_entries(db, list_id=row.id)
    content = export_custom_cbl_xml(row.name, entries)
    return Response(
        content=content,
        media_type="application/xml",
        headers={"Content-Disposition": f'attachment; filename="custom-cbl-{row.id}.cbl"'},
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
    row = await get_owned_custom_cbl(db, user_id=current_user.id, list_id=list_id)
    result = await apply_custom_cbl_to_plan(
        db,
        user_id=current_user.id,
        list_row=row,
        plan_id=plan_id,
        lane_id=payload.lane_id,
    )
    await db.commit()
    await db.refresh(result.plan)
    if result.plan.ordering_mode == "strict_sequential":
        await _refresh_blocked_state(current_user.id, db)
    plan = _plan_response(result.plan)
    return CustomCBLApplyResponse(
        **plan.model_dump(),
        added_issue_ids=list(result.added_issue_ids),
        skipped_existing_issue_ids=list(result.skipped_existing_issue_ids),
    )
