"""Authenticated authoring and Reading Plan application for custom CBL lists."""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, Query, Response
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth import get_current_user
from app.database import get_db
from app.models.user import User
from app.schemas.custom_cbl import (
    CustomCBLApplyRequest,
    CustomCBLApplyResponse,
    CustomCBLIssueSearchResult,
)
from app.services.custom_cbl import (
    apply_custom_cbl_for_user,
    export_custom_cbl_for_user,
    search_custom_cbl_issue_responses,
)

router = APIRouter(prefix="/custom-cbls", tags=["custom-cbls"])


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


