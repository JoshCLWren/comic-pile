"""Issue CRUD API endpoints."""

import logging

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth import get_current_user
from app.cache import TTL, cached
from app.cache_invalidation import invalidate_user_view
from app.database import get_db
from app.models import Issue
from app.models.user import User
from app.schemas import (
    IssueBulkMarkReadRequest,
    IssueBulkMarkUnreadRequest,
    IssueCreateRange,
    IssueListResponse,
    IssueMoveRequest,
    IssueOrderValidationResponse,
    IssueReorderRequest,
    IssueResponse,
)
from app.schemas.comicvine import ComicVineIssueIntelligence
from app.schemas.reader_context import ReaderContextResponse
from app.services import issue as issue_service
from app.services.comicvine_intelligence import get_issue_intelligence
from app.services.reader_context import get_reader_context
from app.services.ownership import get_owned_issue_or_404, get_owned_thread_or_404
from comic_pile.dependencies import validate_position_dependency_consistency

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/v1", tags=["issues"])


@router.get(
    "/issues/{issue_id}/comicvine",
    response_model=ComicVineIssueIntelligence | None,
)
async def get_issue_comicvine_intelligence(
    issue_id: int,
    current_user: Annotated[User, Depends(get_current_user)],
    db: AsyncSession = Depends(get_db),
) -> ComicVineIssueIntelligence | None:
    """Return curated ComicVine intelligence for a user-owned ComicPile issue.

    Args:
        issue_id: ComicPile issue identifier.
        current_user: Authenticated owner of the requested issue.
        db: Async database session.

    Returns:
        Curated ComicVine intelligence, or ``None`` when no confirmed mapping exists.
    """
    await get_owned_issue_or_404(db, current_user.id, issue_id)
    return await get_issue_intelligence(db, issue_id, current_user.id)


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


async def _invalidate_issue_caches(user_id: int) -> None:
    """Invalidate issue-derived views with one bounded user generation bump."""
    await invalidate_user_view(user_id)


def issue_to_response(issue: Issue) -> IssueResponse:
    """Convert Issue model to IssueResponse.

    Args:
        issue: Issue model instance

    Returns:
        IssueResponse schema with position field for ordering
    """
    issue_id = issue.id
    thread_id = issue.thread_id
    issue_number = issue.issue_number
    issue_position = issue.position
    issue_status = issue.status
    read_at = issue.read_at
    created_at = issue.created_at

    return IssueResponse(
        id=issue_id,
        thread_id=thread_id,
        issue_number=issue_number,
        position=issue_position,
        status=issue_status,
        read_at=read_at,
        created_at=created_at,
    )


def _is_issue_thread_number_conflict(exc: IntegrityError) -> bool:
    """Return whether the integrity error came from issue thread/number uniqueness."""
    error_text = str(exc).lower()
    return "uq_issue_thread_number" in error_text or (
        "duplicate key value violates unique constraint" in error_text
        and "thread_id" in error_text
        and "issue_number" in error_text
    )


@router.get("/threads/{thread_id}/issues", response_model=IssueListResponse)
@cached(ttl=TTL.SHORT)
async def list_issues(
    thread_id: int,
    current_user: Annotated[User, Depends(get_current_user)],
    db: AsyncSession = Depends(get_db),
    status_filter: str | None = Query(None, pattern="^(unread|read)$", alias="status"),
    page_size: int = Query(50, ge=1, le=100),
    page_token: str | None = Query(None),
) -> IssueListResponse:
    """List all issues for a thread with optional status filter and pagination.

    Args:
        thread_id: The thread ID to list issues for.
        current_user: The authenticated user making the request.
        db: SQLAlchemy session for database operations.
        status_filter: Optional filter by issue status (read/unread).
        page_size: Number of issues to return per page.
        page_token: Token for pagination continuation.

    Returns:
        IssueListResponse with paginated issues.

    Raises:
        HTTPException: If thread not found.
    """
    issues, total_count, next_token = await issue_service.list_issues(
        db, thread_id, current_user.id, status_filter, page_size, page_token
    )

    issue_responses = [issue_to_response(issue) for issue in issues]

    return IssueListResponse(
        issues=issue_responses,
        total_count=total_count,
        page_size=page_size,
        next_page_token=next_token,
    )


@router.get(
    "/threads/{thread_id}/issues:validateOrder",
    response_model=IssueOrderValidationResponse,
)
@cached(ttl=TTL.SHORT)
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


@router.post(
    "/threads/{thread_id}/issues",
    response_model=IssueListResponse,
    status_code=status.HTTP_201_CREATED,
)
async def create_issues(
    thread_id: int,
    request: IssueCreateRange,
    current_user: Annotated[User, Depends(get_current_user)],
    db: AsyncSession = Depends(get_db),
) -> IssueListResponse:
    """Create issues from a range string and place them in thread order.

    By default new issues are appended after the last existing issue. When
    ``insert_after_issue_id`` is provided, existing issues later in the thread are
    shifted upward so the new issues are inserted immediately after that issue.

    Args:
        thread_id: The thread ID to create issues for.
        request: Request with issue range string.
        current_user: The authenticated user making the request.
        db: SQLAlchemy session for database operations.

    Returns:
        IssueListResponse with newly created issues only (not all issues).

    Raises:
        HTTPException: If thread not found, all issues already exist,
                      position collision detected, or issue range is invalid.
    """
    try:
        new_issues, total_issue_count = await issue_service.create_issues(
            db, thread_id, current_user.id, request.issue_range, request.insert_after_issue_id
        )
    except IntegrityError as e:
        await db.rollback()
        if _is_issue_thread_number_conflict(e):
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="Issue number already exists in this thread",
            ) from e
        logger.error(
            "Database integrity error during issue creation",
            extra={"thread_id": thread_id, "error": str(e)},
        )
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Internal error: Database constraint violation",
        ) from e

    issue_responses = [issue_to_response(issue) for issue in new_issues]

    await db.commit()
    await _invalidate_issue_caches(current_user.id)

    return IssueListResponse(
        issues=issue_responses,
        total_count=total_issue_count,
        page_size=len(issue_responses),
        next_page_token=None,
    )


@router.get("/issues/{issue_id}", response_model=IssueResponse)
@cached(ttl=TTL.SHORT)
async def get_issue(
    issue_id: int,
    current_user: Annotated[User, Depends(get_current_user)],
    db: AsyncSession = Depends(get_db),
) -> IssueResponse:
    """Get a single issue by ID.

    Args:
        issue_id: The issue ID to retrieve.
        current_user: The authenticated user making the request.
        db: SQLAlchemy session for database operations.

    Returns:
        IssueResponse with issue details.

    Raises:
        HTTPException: If issue not found.
    """
    issue = await get_owned_issue_or_404(db, current_user.id, issue_id)

    return issue_to_response(issue)


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
    await issue_service.move_issue(
        db, issue_id, current_user.id, request.after_issue_id
    )

    await db.commit()
    await _invalidate_issue_caches(current_user.id)


@router.post("/threads/{thread_id}/issues:reorder", status_code=status.HTTP_204_NO_CONTENT)
async def reorder_issues(
    thread_id: int,
    request: IssueReorderRequest,
    current_user: Annotated[User, Depends(get_current_user)],
    db: AsyncSession = Depends(get_db),
) -> None:
    """Rewrite all issue positions in a thread from an explicit ordered ID list.

    Args:
        thread_id: The thread whose issue order should be rewritten.
        request: Ordered issue IDs representing the desired canonical order.
        current_user: The authenticated user making the reorder request.
        db: SQLAlchemy session for database operations.

    Returns:
        None. The response is HTTP 204 on success.

    Raises:
        HTTPException: If the thread is not found or the issue IDs are invalid.
    """
    await issue_service.reorder_issues(
        db, thread_id, current_user.id, request.issue_ids
    )

    await db.commit()
    await _invalidate_issue_caches(current_user.id)


@router.delete("/issues/{issue_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_issue(
    issue_id: int,
    current_user: Annotated[User, Depends(get_current_user)],
    db: AsyncSession = Depends(get_db),
) -> None:
    """Delete one issue, compact later positions, and update thread issue metadata.

    Args:
        issue_id: The issue ID to delete.
        current_user: The authenticated user requesting the deletion.
        db: SQLAlchemy session for database operations.

    Returns:
        None. The response is HTTP 204 on success.

    Raises:
        HTTPException: If the issue does not exist or is not owned by the user.
    """
    await issue_service.delete_issue(db, issue_id, current_user.id)

    await db.commit()
    await _invalidate_issue_caches(current_user.id)


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
    await _invalidate_issue_caches(current_user.id)


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
    await _invalidate_issue_caches(current_user.id)


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
    await _invalidate_issue_caches(current_user.id)


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
    await _invalidate_issue_caches(current_user.id)

