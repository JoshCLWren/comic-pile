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
from app.schemas import IssueCreateRange, IssueListResponse, IssueResponse
from app.utils.issue_parser import parse_issue_ranges
from comic_pile.dependencies import refresh_user_blocked_status

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
    """Create issues from range format (e.g., "1-25" or "1, 3, 5-7").

    Supports both initial thread migration and adding issues to existing migrated threads.
    Deduplicates existing issues - only creates issues that don't already exist.
    Updates thread metadata (total_issues, issues_remaining, next_unread_issue_id).

    Position Calculation Algorithm:
    New issues are ALWAYS appended at the end of ALL existing issues to avoid collisions
    and maintain data integrity. The algorithm:
    1. Find max_position among all existing issues (not just referenced ones)
    2. Start new issue positions at max_position + 1
    3. Assign positions sequentially to new issues in request order

    Examples:
    - Existing: Issues 1-10 at positions 1-10
      Request: "1-5, Annual 2"
      Result: Annual 2 at position 11 (after ALL existing issues, including 6-10)

    - Existing: Issues 1-10 at positions 1-10
      Request: "11-15"
      Result: Issues 11-15 at positions 11-15

    - Existing: Empty
      Request: "Annual 1, 1-3"
      Result: Annual 1 at position 1, then 1-3 at positions 2-4

    Rationale:
    Inserting new issues between existing issues would require shifting all subsequent
    issues, which is error-prone and computationally expensive. Appending at the end
    is simple, deterministic, and prevents position collisions.

    Data Integrity Strategy:
    - Position duplicates within new_issues: Detected and logged as ERROR
    - Position conflicts with existing issues: Detected and logged as ERROR
    - All collisions return HTTP 500 to prevent data corruption
    - Logs include thread_id, positions, and conflicts for production monitoring

    Row-Level Locking Strategy:
    Uses SELECT FOR UPDATE to prevent race conditions when multiple requests
    add issues to the same thread concurrently:

    1. Read thread row (without lock, just for permission check)
    2. Lock all issue rows for this thread (prevents concurrent issue adds creating position conflicts)
    3. Calculate new positions atomically (max_position read while holding locks)
    4. Write new issues (position assignment is deterministic under lock)
    5. Commit releases all locks

    Lock strategy (minimal locking to prevent deadlocks):
    - Thread row: NOT locked (read-only for permission check)
    - Issue rows: Locked with SELECT FOR UPDATE (prevents concurrent modifications)
    - Events table: No lock needed (inserts after commit or in same transaction)

    This ensures concurrent requests to add issues are serialized at the database level,
    preventing position collisions without application-level mutexes.

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
    thread_result = await db.execute(select(Thread).where(Thread.id == thread_id).with_for_update())
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
        select(Issue.issue_number, Issue.position)
        .where(Issue.thread_id == thread_id)
        .with_for_update()
    )
    existing_issues = {row[0]: row[1] for row in existing_issues_result.fetchall()}

    max_position = 0
    if existing_issues:
        max_position = max(existing_issues.values())

    new_issues = []
    next_new_position = max_position + 1

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

    existing_position_values = list(existing_issues.values())
    conflicting_positions = [p for p in position_values if p in existing_position_values]
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

    new_issues_count = len(new_issues)

    # Get existing issue count before new issues were added
    existing_count_result = await db.execute(
        select(func.count()).select_from(Issue).where(Issue.thread_id == thread_id)
    )
    existing_issue_count = existing_count_result.scalar() or 0

    # Handle both initial migration and adding to existing migrated threads
    if thread.total_issues is None:
        # Initial thread migration - set up issue tracking from scratch
        thread.total_issues = existing_issue_count
        thread.issues_remaining = existing_issue_count
        thread.reading_progress = "not_started"
        if new_issues:
            thread.next_unread_issue_id = new_issues[0].id
            thread.status = "active"
    else:
        # Adding issues to existing migrated thread - update counts incrementally
        thread.total_issues += new_issues_count
        thread.issues_remaining += new_issues_count
        thread.reading_progress = "in_progress"
        # If thread was completed (no next_unread), reactivate with first new issue
        if thread.next_unread_issue_id is None and new_issues:
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
        # Otherwise keep existing next_unread - no change needed

    thread_id_val = thread.id

    event = Event(
        type="issues_created",
        timestamp=datetime.now(UTC),
        thread_id=thread_id_val,
    )
    db.add(event)

    await refresh_user_blocked_status(current_user.id, db)
    await db.commit()

    issue_responses = [issue_to_response(issue) for issue in new_issues]

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
