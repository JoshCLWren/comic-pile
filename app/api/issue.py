"""Issue CRUD API endpoints."""

import logging
from datetime import UTC, datetime
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import func, or_, select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth import get_current_user
from app.database import get_db
from app.models import Event, Issue, Thread
from app.models.user import User
from app.schemas import (
    IssueCreateRange,
    IssueListResponse,
    IssueOrderValidationResponse,
    IssueResponse,
)
from app.utils.issue_parser import parse_issue_ranges
from comic_pile.dependencies import (
    refresh_user_blocked_status,
    validate_position_dependency_consistency,
)

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/v1", tags=["issues"])


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
    thread = await db.get(Thread, thread_id)
    if not thread or thread.user_id != current_user.id:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Thread {thread_id} not found",
        )

    query = select(Issue).where(Issue.thread_id == thread_id)

    if status_filter:
        query = query.where(Issue.status == status_filter)

    query = query.order_by(Issue.position)

    if page_token:
        try:
            parts = page_token.split(",")
            if len(parts) != 2:
                raise ValueError("Invalid format")
            cursor_position = int(parts[0])
            cursor_id = int(parts[1])
            query = query.where(
                or_(
                    Issue.position > cursor_position,
                    (Issue.position == cursor_position) & (Issue.id > cursor_id),
                )
            )
        except ValueError:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Invalid page_token format",
            ) from None

    query = query.limit(page_size + 1)

    result = await db.execute(query)
    issues = result.scalars().all()

    has_more = len(issues) > page_size
    issues_to_return = issues[:page_size]

    issue_responses = [issue_to_response(issue) for issue in issues_to_return]

    total_count_result = await db.execute(
        select(func.count()).select_from(Issue).where(Issue.thread_id == thread_id)
    )
    total_count = total_count_result.scalar() or 0

    next_token = None
    if has_more and issues_to_return:
        last = issues_to_return[-1]
        next_token = f"{last.position},{last.id}"

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
async def validate_issue_order(
    thread_id: int,
    current_user: Annotated[User, Depends(get_current_user)],
    db: AsyncSession = Depends(get_db),
) -> IssueOrderValidationResponse:
    """Report in-thread dependency edges that disagree with canonical issue positions."""
    thread = await db.get(Thread, thread_id)
    if not thread or thread.user_id != current_user.id:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Thread {thread_id} not found",
        )

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
    thread_result = await db.execute(
        select(Thread).where(Thread.id == thread_id).with_for_update()
    )
    thread = thread_result.scalar_one_or_none()
    if not thread or thread.user_id != current_user.id:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Thread {thread_id} not found",
        )

    try:
        issue_numbers = parse_issue_ranges(request.issue_range)
    except ValueError as e:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(e),
        ) from None

    if not issue_numbers:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Issue range cannot be empty",
        )

    existing_issues_result = await db.execute(
        select(Issue.id, Issue.issue_number, Issue.position)
        .where(Issue.thread_id == thread_id)
        .with_for_update()
        .order_by(Issue.position)
    )
    existing_issue_rows = existing_issues_result.all()
    existing_issues = {row.issue_number: row.position for row in existing_issue_rows}

    max_position = max((row.position for row in existing_issue_rows), default=0)
    insert_position = max_position

    if request.insert_after_issue_id is not None:
        insert_after_issue = next(
            (row for row in existing_issue_rows if row.id == request.insert_after_issue_id),
            None,
        )
        if insert_after_issue is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Issue {request.insert_after_issue_id} not found",
            )
        insert_position = insert_after_issue.position

    new_issues = []
    next_new_position = insert_position + 1

    for issue_number in issue_numbers:
        if issue_number not in existing_issues:
            issue = Issue(
                thread_id=thread_id,
                issue_number=issue_number,
                position=next_new_position,
                status="unread",
            )
            db.add(issue)
            new_issues.append(issue)
            next_new_position += 1

    if not new_issues:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="All issues in range already exist",
        )

    new_issues_count = len(new_issues)

    if request.insert_after_issue_id is not None:
        await db.execute(
            update(Issue)
            .where(Issue.thread_id == thread_id, Issue.position > insert_position)
            .values(position=Issue.position + new_issues_count)
        )

    position_values = [issue.position for issue in new_issues]
    if len(position_values) != len(set(position_values)):
        logger.error(
            "Position collision within new issues",
            extra={
                "thread_id": thread_id,
                "requested_positions": position_values,
            },
        )
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Internal error: Duplicate positions calculated",
        )

    reserved_positions = [
        row.position for row in existing_issue_rows if row.position <= insert_position
    ]
    conflicting_positions = [p for p in position_values if p in reserved_positions]
    if conflicting_positions:
        logger.error(
            "Position collision with existing issues",
            extra={
                "thread_id": thread_id,
                "requested_positions": position_values,
                "conflicting_positions": conflicting_positions,
            },
        )
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Internal error: Position conflict with existing issues",
        )

    try:
        await db.flush()
    except IntegrityError as e:
        await db.rollback()
        if _is_issue_thread_number_conflict(e):
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="Issue number already exists in this thread",
            ) from e
        logger.error(
            "Database integrity error during issue creation",
            extra={
                "thread_id": thread_id,
                "error": str(e),
                "position_values": position_values,
            },
        )
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Internal error: Database constraint violation",
        ) from e

    # Get existing issue count before new issues were added
    existing_count_result = await db.execute(
        select(func.count()).select_from(Issue).where(Issue.thread_id == thread_id)
    )
    existing_issue_count = existing_count_result.scalar() or 0

    first_unread_result = await db.execute(
        select(Issue)
        .where(Issue.thread_id == thread_id, Issue.status == "unread")
        .order_by(Issue.position)
        .limit(1)
    )
    first_unread_issue = first_unread_result.scalar_one_or_none()

    # Handle both initial migration and adding to existing migrated threads
    if thread.total_issues is None:
        # Initial thread migration - set up issue tracking from scratch
        thread.total_issues = existing_issue_count
        thread.issues_remaining = await thread.get_issues_remaining(db)
        if first_unread_issue is None:
            thread.next_unread_issue_id = None
            thread.reading_progress = "completed"
            thread.status = "completed"
        else:
            thread.next_unread_issue_id = first_unread_issue.id
            if thread.issues_remaining == thread.total_issues:
                thread.reading_progress = "not_started"
            else:
                thread.reading_progress = "in_progress"
            thread.status = "active"
    else:
        # Adding issues to existing migrated thread - update counts incrementally
        thread.total_issues += new_issues_count
        thread.issues_remaining += new_issues_count
        thread.reading_progress = "in_progress"
        existing_next_unread_issue_id = thread.next_unread_issue_id
        # If thread was completed (no next_unread), reactivate with first new issue
        if existing_next_unread_issue_id is None and new_issues:
            if thread.status == "completed":
                await db.execute(
                    update(Thread)
                    .where(Thread.user_id == current_user.id)
                    .where(Thread.status == "active")
                    .values(queue_position=Thread.queue_position + 1)
                )
                thread.queue_position = 1
            thread.next_unread_issue_id = new_issues[0].id
            thread.status = "active"
        elif (
            new_issues
            and existing_next_unread_issue_id is not None
            and await should_update_next_unread(
                new_issues[0].id, existing_next_unread_issue_id, db
            )
        ):
            thread.next_unread_issue_id = new_issues[0].id

    thread_id_val = thread.id

    event = Event(
        type="issues_created",
        timestamp=datetime.now(UTC),
        thread_id=thread_id_val,
    )
    db.add(event)

    issue_responses = [issue_to_response(issue) for issue in new_issues]

    await refresh_user_blocked_status(current_user.id, db)
    await db.commit()

    return IssueListResponse(
        issues=issue_responses,
        total_count=existing_issue_count,
        page_size=len(issue_responses),
        next_page_token=None,
    )


@router.get("/issues/{issue_id}", response_model=IssueResponse)
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
    issue = await db.get(Issue, issue_id)
    if not issue:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Issue {issue_id} not found",
        )

    thread = await db.get(Thread, issue.thread_id)
    if not thread or thread.user_id != current_user.id:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Issue {issue_id} not found",
        )

    return issue_to_response(issue)


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
    issue = await db.get(Issue, issue_id)
    if not issue:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Issue {issue_id} not found",
        )

    thread = await db.get(Thread, issue.thread_id)
    if not thread or thread.user_id != current_user.id:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Issue {issue_id} not found",
        )

    if issue.status == "read":
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Issue {issue_id} is already marked as read",
        )

    issue.status = "read"
    issue.read_at = datetime.now(UTC)

    thread_id = thread.id

    await db.flush()

    next_unread_result = await db.execute(
        select(Issue)
        .where(
            Issue.thread_id == thread_id,
            Issue.status == "unread",
        )
        .order_by(Issue.position)
        .limit(1)
    )
    next_unread = next_unread_result.scalar_one_or_none()

    if next_unread:
        thread.next_unread_issue_id = next_unread.id
        thread.reading_progress = "in_progress"
        thread.issues_remaining = await thread.get_issues_remaining(db)
    else:
        thread.next_unread_issue_id = None
        thread.reading_progress = "completed"
        thread.issues_remaining = 0
        thread.status = "completed"

    event = Event(
        type="issue_read",
        timestamp=datetime.now(UTC),
        thread_id=thread_id,
        issue_id=issue_id,
    )
    db.add(event)

    await refresh_user_blocked_status(current_user.id, db)
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
    issue = await db.get(Issue, issue_id)
    if not issue:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Issue {issue_id} not found",
        )

    thread = await db.get(Thread, issue.thread_id)
    if not thread or thread.user_id != current_user.id:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Issue {issue_id} not found",
        )

    if issue.status == "unread":
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Issue {issue_id} is already marked as unread",
        )

    issue.status = "unread"
    issue.read_at = None

    thread_id = thread.id
    thread_was_completed = thread.status == "completed"

    await db.flush()

    if thread.next_unread_issue_id is None or await should_update_next_unread(
        issue.id, thread.next_unread_issue_id, db
    ):
        thread.next_unread_issue_id = issue.id

    thread.reading_progress = "in_progress"
    thread.issues_remaining = await thread.get_issues_remaining(db)

    if thread_was_completed:
        thread.status = "active"

    event = Event(
        type="issue_unread",
        timestamp=datetime.now(UTC),
        thread_id=thread_id,
        issue_id=issue_id,
    )
    db.add(event)

    await refresh_user_blocked_status(current_user.id, db)
    await db.commit()


async def should_update_next_unread(
    issue_id: int, next_unread_issue_id: int, db: AsyncSession
) -> bool:
    """Check if next_unread_issue_id should be updated to the given issue.

    Returns True if the issue should become the next unread
    (i.e., its position is earlier than the current next unread).

    Args:
        issue_id: Issue ID to check.
        next_unread_issue_id: Current next unread issue ID.
        db: Database session.

    Returns:
        True if issue position is earlier than current next unread issue.
    """
    next_issue = await db.get(Issue, next_unread_issue_id)
    if not next_issue:
        return True

    issue = await db.get(Issue, issue_id)
    if not issue:
        return False

    return issue.position < next_issue.position
