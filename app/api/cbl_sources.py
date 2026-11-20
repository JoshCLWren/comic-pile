"""Legacy Python CBL reading-graph preview handler (retired in favor of native Rust same-path)."""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth import get_current_user
from app.database import get_db
from app.models.user import User
from app.schemas.reading_graph_preview import (
    ReadingGraphPreview,
    ReadingGraphPreviewRequest,
)
from app.services.reading_graph_preview_service import preview_reading_graph

router = APIRouter(prefix="/issue-identity", tags=["issue-identity"])

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
