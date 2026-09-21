"""Batched issue-dependency API endpoints."""

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth import get_current_user
from app.database import get_db
from app.models.user import User
from app.schemas.issue_dependency_batch import ThreadIssueDependenciesResponse
from app.services import dependency_service

router = APIRouter(tags=["dependencies"])


@router.get(
    "/threads/{thread_id}/issue-dependencies",
    response_model=ThreadIssueDependenciesResponse,
)
async def list_thread_issue_dependencies(
    thread_id: int,
    current_user: Annotated[User, Depends(get_current_user)],
    db: AsyncSession = Depends(get_db),
) -> ThreadIssueDependenciesResponse:
    """Return dependency edges for every issue in one thread using bulk queries.

    This endpoint replaces the frontend's previous one-request-per-issue pattern.
    Empty dependency payloads are included so clients can distinguish a complete
    response from missing data without issuing fallback requests.
    """
    result = await dependency_service.get_thread_issue_dependencies_batch(
        thread_id, current_user.id, db
    )
    if result is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Thread {thread_id} not found",
        )
    return result
