"""Issue CRUD API endpoints."""

from datetime import UTC, datetime
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import Integer, cast, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth import get_current_user
from app.database import get_db
from app.models import Event, Issue, Thread
from app.models.user import User
from app.schemas import IssueCreateRange, IssueListResponse, IssueResponse
from app.utils.issue_parser import parse_issue_ranges
from comic_pile.dependencies import refresh_user_blocked_status

router = APIRouter(prefix="/api/v1", tags=["issues"])


def issue_to_response(issue: Issue) -> IssueResponse:
    """Convert Issue model to IssueResponse.

    Args:
        issue: Issue model instance

    Returns:
        IssueResponse schema
    """
    issue_id = issue.id
    thread_id = issue.thread_id
    issue_number = issue.issue_number
    issue_status = issue.status
    read_at = issue.read_at
    created_at = issue.created_at

    return IssueResponse(
        id=issue_id,
        thread_id=thread_id,
        issue_number=issue_number,
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

    query = query.order_by(cast(Issue.issue_number, Integer))

    if page_token:
        try:
            parts = page_token.split(",")
            if len(parts) != 2:
                raise ValueError("Invalid format")
            cursor_number = parts[0]
            cursor_id = int(parts[1])
            query = query.where(
                or_(
                    cast(Issue.issue_number, Integer) > int(cursor_number),
                    (cast(Issue.issue_number, Integer) == int(cursor_number))
                    & (Issue.id > cursor_id),
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
        next_token = f"{last.issue_number},{last.id}"

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

    Args:
        thread_id: The thread ID to create issues for.
        request: Request with issue range string.
        current_user: The authenticated user making the request.
        db: SQLAlchemy session for database operations.

    Returns:
        IssueListResponse with created issues.

    Raises:
        HTTPException: If thread not found, thread already uses issue tracking,
                      or issue range is invalid.
    """
    thread = await db.get(Thread, thread_id)
    if not thread or thread.user_id != current_user.id:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Thread {thread_id} not found",
        )

    if thread.total_issues is not None:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Thread {thread_id} already uses issue tracking",
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
        select(Issue.issue_number).where(Issue.thread_id == thread_id)
    )
    existing_numbers = {row[0] for row in existing_issues_result.fetchall()}

    new_issues = []
    for issue_number in issue_numbers:
        if issue_number in existing_numbers:
            continue
        issue = Issue(
            thread_id=thread_id,
            issue_number=issue_number,
            status="unread",
        )
        db.add(issue)
        new_issues.append(issue)

    if not new_issues:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="All issues in range already exist",
        )

    await db.flush()

    total_issues = len(issue_numbers)
    thread.total_issues = total_issues
    thread.issues_remaining = total_issues
    thread.reading_progress = "not_started"

    if new_issues:
        thread.next_unread_issue_id = new_issues[0].id

    thread_id_val = thread.id

    event = Event(
        type="issues_created",
        timestamp=datetime.now(UTC),
        thread_id=thread_id_val,
    )
    db.add(event)

    await db.commit()

    issue_responses = [issue_to_response(issue) for issue in new_issues]

    return IssueListResponse(
        issues=issue_responses,
        total_count=total_issues,
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
        .order_by(cast(Issue.issue_number, Integer))
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
        issue.issue_number, thread.next_unread_issue_id, db
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
    issue_number: str, next_unread_issue_id: int, db: AsyncSession
) -> bool:
    """Check if next_unread_issue_id should be updated to the given issue.

    Returns True if the issue with issue_number should become the next unread
    (i.e., its issue_number is earlier than the current next unread).

    Args:
        issue_number: Issue number to check.
        next_unread_issue_id: Current next unread issue ID.
        db: Database session.

    Returns:
        True if issue_number is earlier than current next unread issue.

    Raises:
        ValueError: If issue numbers cannot be compared numerically.
    """
    next_issue = await db.get(Issue, next_unread_issue_id)
    if not next_issue:
        return True

    try:
        return int(issue_number) < int(next_issue.issue_number)
    except ValueError as e:
        raise ValueError(
            f"Cannot compare issue numbers: '{issue_number}' and '{next_issue.issue_number}'. "
            f"Both must be numeric for proper ordering."
        ) from e
