"""Issue CRUD API endpoints."""

from typing import Annotated

from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth import get_current_user
from app.database import get_db
from app.models.user import User
from app.schemas import ThreadIssueCreatorsResponse
from app.services.comicvine_intelligence import (
    get_thread_issue_creators,
)

router = APIRouter(prefix="/api/v1", tags=["issues"])


@router.get(
    "/threads/{thread_id}/issues/creators",
    response_model=ThreadIssueCreatorsResponse,
)
async def list_thread_issue_creators(
    thread_id: int,
    current_user: Annotated[User, Depends(get_current_user)],
    db: AsyncSession = Depends(get_db),
) -> ThreadIssueCreatorsResponse:
    """Return stored ComicVine creator credits for every mapped issue in a thread.

    One bulk read serves the whole issue list's creator column, so expanding
    a full page never fans out into one provider-intelligence request per
    row. Issues without a confirmed ComicVine mapping (or without stored
    credits) are omitted; clients fall back to the series' manual creator
    credits for those rows.

    Args:
        thread_id: ComicPile thread whose issue credits are returned.
        current_user: Authenticated owner of the requested thread.
        db: Async database session.

    Returns:
        Per-issue stored ComicVine creator credits for the owned thread.
    """
    return await get_thread_issue_creators(db, thread_id, current_user.id)
