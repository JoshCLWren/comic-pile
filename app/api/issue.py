"""Issue CRUD API endpoints."""

from typing import Annotated

from fastapi import APIRouter, Depends, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth import get_current_user
from app.database import get_db
from app.models.user import User
from app.schemas import (
    IssueBulkMarkReadRequest,
    IssueBulkMarkUnreadRequest,
    IssueMoveRequest,
    IssueOrderValidationResponse,
)
from app.schemas.reader_context import ReaderContextResponse
from app.services import issue as issue_service
from app.services.reader_context import get_reader_context
from app.services.ownership import get_owned_thread_or_404
from comic_pile.dependencies import validate_position_dependency_consistency

router = APIRouter(prefix="/api/v1", tags=["issues"])


@router.get("/issues/{issue_id}/reader-context", response_model=ReaderContextResponse)
async def get_issue_reader_context(
    issue_id: int,
    current_user: Annotated[User, Depends(get_current_user)],
    db: AsyncSession = Depends(get_db),
) -> ReaderContextResponse:
    """Return bounded reading analytics and local neighborhood for an owned issue.

    The response is decorative context for the Roll experience and must never
    be a prerequisite for rating. It is computed with bounded, user-scoped
    queries that do not traverse the full library or hydrate ComicVine.

    Args:
        issue_id: ComicPile issue identifier.
        current_user: Authenticated owner of the requested issue.
        db: Async database session.

    Returns:
        Bounded reader-context payload for the requested issue.

    Raises:
        HTTPException: If the issue does not belong to the user.
    """
    return await get_reader_context(db, current_user.id, issue_id)


@router.get(
    "/threads/{thread_id}/issues:validateOrder",
    response_model=IssueOrderValidationResponse,
)
async def validate_issue_order(
    thread_id: int,
    current_user: Annotated[User, Depends(get_current_user)],
    db: AsyncSession = Depends(get_db),
) -> IssueOrderValidationResponse:
    """Report dependency edges that disagree with canonical issue positions.

    Args:
        thread_id: The thread ID whose in-thread ordering should be validated.
        current_user: The authenticated user requesting the validation report.
        db: SQLAlchemy session for database operations.

    Returns:
        IssueOrderValidationResponse containing human-readable ordering warnings.

    Raises:
        HTTPException: If the thread does not exist or is not owned by the user.
    """
    await get_owned_thread_or_404(db, current_user.id, thread_id)

    warnings = await validate_position_dependency_consistency(thread_id, current_user.id, db)
    return IssueOrderValidationResponse(warnings=warnings)


@router.post("/issues/{issue_id}:move", status_code=status.HTTP_204_NO_CONTENT)
async def move_issue(
    issue_id: int,
    request: IssueMoveRequest,
    current_user: Annotated[User, Depends(get_current_user)],
    db: AsyncSession = Depends(get_db),
) -> None:
    """Move a single issue within its thread.

    Args:
        issue_id: The issue ID to move.
        request: Move request containing the issue that should come before it.
        current_user: The authenticated user making the move request.
        db: SQLAlchemy session for database operations.

    Returns:
        None. The response is HTTP 204 on success.

    Raises:
        HTTPException: If the issue or requested target issue is not found.
    """
    await issue_service.move_issue(db, issue_id, current_user.id, request.after_issue_id)

    await db.commit()


@router.post("/issues/{issue_id}:markRead", status_code=status.HTTP_204_NO_CONTENT)
async def mark_issue_read(
    issue_id: int,
    current_user: Annotated[User, Depends(get_current_user)],
    db: AsyncSession = Depends(get_db),
) -> None:
    """Mark an issue as read and update thread's next_unread_issue_id.

    Args:
        issue_id: The issue ID to mark as read.
        current_user: The authenticated user making the request.
        db: SQLAlchemy session for database operations.

    Raises:
        HTTPException: If issue not found, thread not found, or issue already read.
    """
    await issue_service.mark_issue_read(db, issue_id, current_user.id)
    await db.commit()


@router.post("/issues/{issue_id}:markUnread", status_code=status.HTTP_204_NO_CONTENT)
async def mark_issue_unread(
    issue_id: int,
    current_user: Annotated[User, Depends(get_current_user)],
    db: AsyncSession = Depends(get_db),
) -> None:
    """Mark an issue as unread and update thread's next_unread_issue_id.

    Reactivates thread if it was completed.

    Args:
        issue_id: The issue ID to mark as unread.
        current_user: The authenticated user making the request.
        db: SQLAlchemy session for database operations.

    Raises:
        HTTPException: If issue not found, thread not found, or issue already unread.
    """
    await issue_service.mark_issue_unread(db, issue_id, current_user.id)
    await db.commit()


@router.post("/issues:bulkMarkRead", status_code=status.HTTP_204_NO_CONTENT)
async def bulk_mark_issue_read(
    request: IssueBulkMarkReadRequest,
    current_user: Annotated[User, Depends(get_current_user)],
    db: AsyncSession = Depends(get_db),
) -> None:
    """Bulk mark issues as read.

    Args:
        request: Bounded list of issue IDs.
        current_user: Authenticated user.
        db: Database session.

    Raises:
        HTTPException: If any issue is invalid or already read.
    """
    await issue_service.bulk_mark_issue_read(db, request.issue_ids, current_user.id)
    await db.commit()


@router.post("/issues:bulkMarkUnread", status_code=status.HTTP_204_NO_CONTENT)
async def bulk_mark_issue_unread(
    request: IssueBulkMarkUnreadRequest,
    current_user: Annotated[User, Depends(get_current_user)],
    db: AsyncSession = Depends(get_db),
) -> None:
    """Bulk mark issues as unread.

    Args:
        request: Bounded list of issue IDs.
        current_user: Authenticated user.
        db: Database session.

    Raises:
        HTTPException: If any issue is invalid or already unread.
    """
    await issue_service.bulk_mark_issue_unread(db, request.issue_ids, current_user.id)
    await db.commit()
