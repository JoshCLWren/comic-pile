"""Issue CRUD API endpoints."""

import logging
from datetime import UTC, datetime
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import func, or_, select, text, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth import get_current_user
from app.cache import TTL, cached
from app.cache_invalidation import invalidate_user_view
from app.database import get_db
from app.models import Dependency, Event, Issue, Thread
from app.models.continuity_rule import ContinuityRule, ContinuityRuleSelectedMember
from app.models.dependency_group import DependencyGroup, DependencyGroupMembership
from app.models.user import User
from app.schemas import (
    IssueCreateRange,
    IssueListResponse,
    IssueMoveRequest,
    IssueOrderValidationResponse,
    IssueReorderRequest,
    IssueResponse,
)
from app.schemas.comicvine import ComicVineIssueIntelligence
from app.schemas.reader_context import ReaderContextResponse
from app.services.comicvine_intelligence import get_issue_intelligence
from app.utils.issue_parser import parse_issue_ranges
from app.services.ownership import get_owned_issue_or_404, get_owned_thread_or_404
from comic_pile.dependencies import (
    refresh_user_blocked_status,
    validate_position_dependency_consistency,
)

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


async def _get_locked_thread_with_issues(
    thread_id: int,
    current_user: User,
    db: AsyncSession,
) -> tuple[Thread, list[Issue]]:
    """Lock a thread and all of its issues, validating ownership."""
    thread = await get_owned_thread_or_404(db, current_user.id, thread_id, for_update=True)

    issues_result = await db.execute(
        select(Issue)
        .where(Issue.thread_id == thread_id)
        .order_by(Issue.position, Issue.id)
        .with_for_update()
    )
    return thread, list(issues_result.scalars().all())


async def _get_issue_thread_id(
    issue_id: int,
    current_user: User,
    db: AsyncSession,
) -> int:
    """Resolve an issue's thread ID with ownership validation before taking thread locks."""
    issue_thread_result = await db.execute(
        select(Issue.thread_id)
        .join(Thread, Thread.id == Issue.thread_id)
        .where(Issue.id == issue_id, Thread.user_id == current_user.id)
    )
    thread_id = issue_thread_result.scalar_one_or_none()
    if thread_id is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Issue {issue_id} not found",
        )
    return thread_id


def _assign_issue_positions(issues: list[Issue]) -> None:
    """Rewrite positions so the given issue order becomes canonical."""
    for position, issue in enumerate(issues, start=1):
        issue.position = position


def _recalculate_next_unread_issue_id(thread: Thread, issues: list[Issue]) -> None:
    """Update a thread's next unread pointer from the current in-memory issue order."""
    next_unread_issue = next(
        (issue for issue in issues if issue.status == "unread"),
        None,
    )
    thread.next_unread_issue_id = next_unread_issue.id if next_unread_issue else None


def _recalculate_thread_issue_tracking_state(thread: Thread, issues: list[Issue]) -> None:
    """Recalculate issue-tracking metadata from the current in-memory issue state."""
    unread_issues = [issue for issue in issues if issue.status == "unread"]
    unread_count = len(unread_issues)
    total_issues = len(issues)

    thread.total_issues = total_issues
    thread.issues_remaining = unread_count
    thread.next_unread_issue_id = unread_issues[0].id if unread_issues else None

    if unread_count == 0:
        thread.reading_progress = "completed"
        thread.status = "completed"
        return

    if unread_count == total_issues:
        thread.reading_progress = "not_started"
    else:
        thread.reading_progress = "in_progress"

    if thread.status == "completed":
        thread.status = "active"


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
    await get_owned_thread_or_404(db, current_user.id, thread_id)

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

    count_query = select(func.count()).select_from(Issue).where(Issue.thread_id == thread_id)
    if status_filter:
        count_query = count_query.where(Issue.status == status_filter)
    total_count_result = await db.execute(count_query)
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
    thread = await get_owned_thread_or_404(db, current_user.id, thread_id, for_update=True)

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

    new_issue_numbers = [
        issue_number for issue_number in issue_numbers if issue_number not in existing_issues
    ]

    if not new_issue_numbers:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="All issues in range already exist",
        )

    new_issues_count = len(new_issue_numbers)

    if request.insert_after_issue_id is not None:
        await db.execute(text("SET CONSTRAINTS uq_issue_thread_position DEFERRED"))
        await db.execute(
            update(Issue)
            .where(Issue.thread_id == thread_id, Issue.position > insert_position)
            .values(position=Issue.position + new_issues_count)
        )

    new_issues = []
    next_new_position = insert_position + 1

    for issue_number in new_issue_numbers:
        issue = Issue(
            thread_id=thread_id,
            issue_number=issue_number,
            position=next_new_position,
            status="unread",
        )
        db.add(issue)
        new_issues.append(issue)
        next_new_position += 1

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
        total_count_result = await db.execute(
            select(func.count()).select_from(Issue).where(Issue.thread_id == thread_id)
        )
        total_issue_count = total_count_result.scalar() or 0

        first_unread_result = await db.execute(
            select(Issue)
            .where(Issue.thread_id == thread_id, Issue.status == "unread")
            .order_by(Issue.position)
            .limit(1)
        )
        first_unread_issue = first_unread_result.scalar_one_or_none()
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

    if thread.total_issues is None:
        thread.total_issues = total_issue_count
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
        existing_next_unread_issue_id = thread.next_unread_issue_id
        was_not_started = thread.reading_progress == "not_started"
        thread.total_issues += new_issues_count
        thread.issues_remaining += new_issues_count
        thread.reading_progress = "not_started" if was_not_started else "in_progress"
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
            thread.reading_progress = "in_progress"
            thread.status = "active"
        elif (
            new_issues
            and existing_next_unread_issue_id is not None
            and await should_update_next_unread(new_issues[0].id, existing_next_unread_issue_id, db)
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
    try:
        await db.commit()
        await _invalidate_issue_caches(current_user.id)
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
    thread_id = await _get_issue_thread_id(issue_id, current_user, db)
    thread, thread_issues = await _get_locked_thread_with_issues(thread_id, current_user, db)

    issue_map = {issue.id: issue for issue in thread_issues}
    issue = issue_map.get(issue_id)
    if issue is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Issue {issue_id} not found",
        )

    if request.after_issue_id == issue_id:
        _recalculate_next_unread_issue_id(thread, thread_issues)
        await refresh_user_blocked_status(current_user.id, db)
        await db.commit()
        await _invalidate_issue_caches(current_user.id)
        return

    reordered_issues = [
        existing_issue for existing_issue in thread_issues if existing_issue.id != issue_id
    ]

    if request.after_issue_id is None:
        insert_index = 0
    else:
        after_issue = issue_map.get(request.after_issue_id)
        if after_issue is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Issue {request.after_issue_id} not found",
            )
        insert_index = (
            next(
                index
                for index, existing_issue in enumerate(reordered_issues)
                if existing_issue.id == after_issue.id
            )
            + 1
        )

    reordered_issues.insert(insert_index, issue)
    _assign_issue_positions(reordered_issues)
    _recalculate_next_unread_issue_id(thread, reordered_issues)

    await refresh_user_blocked_status(current_user.id, db)
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
    thread, thread_issues = await _get_locked_thread_with_issues(thread_id, current_user, db)

    existing_issue_ids = [issue.id for issue in thread_issues]
    requested_issue_ids = request.issue_ids
    if (
        len(requested_issue_ids) != len(existing_issue_ids)
        or len(set(requested_issue_ids)) != len(requested_issue_ids)
        or set(requested_issue_ids) != set(existing_issue_ids)
    ):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="issue_ids must contain every issue in the thread exactly once",
        )

    issue_map = {issue.id: issue for issue in thread_issues}
    reordered_issues = [issue_map[issue_id] for issue_id in requested_issue_ids]

    _assign_issue_positions(reordered_issues)
    _recalculate_next_unread_issue_id(thread, reordered_issues)

    await refresh_user_blocked_status(current_user.id, db)
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
    thread_id = await _get_issue_thread_id(issue_id, current_user, db)
    thread, thread_issues = await _get_locked_thread_with_issues(thread_id, current_user, db)

    issue_map = {issue.id: issue for issue in thread_issues}
    issue = issue_map.get(issue_id)
    if issue is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Issue {issue_id} not found",
        )

    deleted_position = issue.position
    deleted_issue_number = issue.issue_number
    remaining_issues = [
        existing_issue for existing_issue in thread_issues if existing_issue.id != issue_id
    ]

    await db.delete(issue)

    for remaining_issue in remaining_issues:
        if remaining_issue.position > deleted_position:
            remaining_issue.position -= 1

    _recalculate_thread_issue_tracking_state(thread, remaining_issues)

    db.add(
        Event(
            type="issue_deleted",
            timestamp=datetime.now(UTC),
            thread_id=thread.id,
            issue_number=deleted_issue_number,
        )
    )

    await refresh_user_blocked_status(current_user.id, db)
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
    issue = await get_owned_issue_or_404(db, current_user.id, issue_id)
    thread = await get_owned_thread_or_404(db, current_user.id, issue.thread_id)

    if issue.status == "read":
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Issue {issue_id} is already marked as read",
        )

    issue.status = "read"
    issue.read_at = datetime.now(UTC)

    thread_id = thread.id

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
        issue_number=issue.issue_number,
    )
    db.add(event)

    await refresh_user_blocked_status(current_user.id, db)
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
    issue = await get_owned_issue_or_404(db, current_user.id, issue_id)
    thread = await get_owned_thread_or_404(db, current_user.id, issue.thread_id)

    if issue.status == "unread":
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Issue {issue_id} is already marked as unread",
        )

    issue.status = "unread"
    issue.read_at = None

    thread_id = thread.id
    thread_was_completed = thread.status == "completed"

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
        issue_number=issue.issue_number,
    )
    db.add(event)

    await refresh_user_blocked_status(current_user.id, db)
    await db.commit()
    await _invalidate_issue_caches(current_user.id)


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


@router.get(
    "/issues/{issue_id}/reader-context",
    response_model=ReaderContextResponse,
    description="Get bounded reader context for the active roll issue.",
)
async def get_reader_context(
    issue_id: int,
    current_user: Annotated[User, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> ReaderContextResponse:
    """Return bounded reader context for one owned issue.

    Provides series identity, canonical-series aggregates, exact crossover context,
    and a bounded local same-thread chain with one-hop edges.

    Args:
        issue_id: The owned issue ID to get context for.
        current_user: Authenticated owner of the issue.
        db: Async database session.

    Returns:
        ReaderContextResponse with series, crossovers, and local chain data.

    Raises:
        HTTPException: If issue not found or not owned by user.
    """
    issue = await get_owned_issue_or_404(db, current_user.id, issue_id)
    thread = await get_owned_thread_or_404(db, current_user.id, issue.thread_id)

    # --- Series identity and aggregates ---
    series_info = await _build_series_info(db, current_user.id, issue, thread)

    # --- Exact crossover context ---
    crossovers = await _build_crossover_info(db, current_user.id, issue, thread)

    # --- Local same-thread chain + one-hop edges ---
    local_chain = await _build_local_chain(db, current_user.id, issue, thread)

    return ReaderContextResponse(
        issue_id=issue_id,
        series=series_info,
        crossovers=crossovers,
        local_chain=local_chain,
    )


async def _build_series_info(
    db: AsyncSession, user_id: int, issue: Issue, thread: Thread
) -> "SeriesInfo":
    """Build series identity and aggregate rating information."""
    from app.models.external_identity import ThreadExternalSeriesMapping
    from app.schemas.reader_context import SeriesInfo, LocalChainIssue

    # Check for confirmed ComicVine identity
    mapping_result = await db.execute(
        select(ThreadExternalSeriesMapping).where(
            ThreadExternalSeriesMapping.thread_id == thread.id,
            ThreadExternalSeriesMapping.provider == "comicvine",
        )
    )
    mapping = mapping_result.scalar_one_or_none()

    if mapping is None:
        return SeriesInfo(
            identity_source="unavailable",
            canonical_series_id=None,
            series_name=None,
            average_rating=None,
            ratings_count=0,
            previous_issue=None,
            recent_ratings=[],
            highest_rating=None,
            lowest_rating=None,
        )

    canonical_series_id = str(mapping.external_series_id)

    # Get all issues in this thread that are confirmed to the same canonical series
    # For now, we use the thread's issues since the mapping is at thread level
    thread_issues_result = await db.execute(
        select(Issue)
        .where(Issue.thread_id == thread.id)
        .order_by(Issue.position)
    )
    thread_issues = list(thread_issues_result.scalars().all())

    # Get effective ratings for issues in this thread (latest rate event per issue)
    from app.models import Event

    issue_ids = [i.id for i in thread_issues]
    if not issue_ids:
        return SeriesInfo(
            identity_source="comicvine",
            canonical_series_id=canonical_series_id,
            series_name=thread.title,
            average_rating=None,
            ratings_count=0,
            previous_issue=None,
            recent_ratings=[],
            highest_rating=None,
            lowest_rating=None,
        )

    # Get latest rate event per issue
    rate_events_result = await db.execute(
        select(Event)
        .where(Event.type == "rate", Event.issue_id.in_(issue_ids))
        .order_by(Event.issue_id, Event.timestamp.desc())
    )
    rate_events = rate_events_result.scalars().all()

    # Dedupe by issue_id - keep only the latest per issue
    latest_ratings: dict[int, float] = {}
    for event in rate_events:
        if event.issue_id and event.issue_id not in latest_ratings:
            latest_ratings[event.issue_id] = event.rating

    # Calculate aggregates
    ratings = list(latest_ratings.values())
    ratings_count = len(ratings)
    average_rating = sum(ratings) / ratings_count if ratings_count > 0 else None
    highest_rating = max(ratings) if ratings else None
    lowest_rating = min(ratings) if ratings else None

    # Find previous issue (immediately preceding by position in current thread)
    current_position = issue.position
    previous_issue = None
    for thread_issue in thread_issues:
        if thread_issue.position < current_position:
            if previous_issue is None or thread_issue.position > previous_issue.position:
                previous_issue = thread_issue

    # Build previous issue response
    previous_issue_response = None
    if previous_issue:
        previous_issue_response = LocalChainIssue(
            issue_id=previous_issue.id,
            issue_number=previous_issue.issue_number,
            position=previous_issue.position,
            status=previous_issue.status,
            relation="previous",
            rating=latest_ratings.get(previous_issue.id),
            crossover_memberships=[],  # Will be populated separately if needed
        )

    # Recent ratings (max 5, ordered by effective-event timestamp descending)
    # We need to get the events with timestamps for ordering
    recent_events_result = await db.execute(
        select(Event)
        .where(Event.type == "rate", Event.issue_id.in_(issue_ids))
        .order_by(Event.timestamp.desc())
        .limit(5)
    )
    recent_events = recent_events_result.scalars().all()

    recent_ratings = []
    seen_issues = set()
    for event in recent_events:
        if event.issue_id and event.issue_id not in seen_issues:
            seen_issues.add(event.issue_id)
            rated_issue = next((i for i in thread_issues if i.id == event.issue_id), None)
            if rated_issue:
                recent_ratings.append(
                    LocalChainIssue(
                        issue_id=rated_issue.id,
                        issue_number=rated_issue.issue_number,
                        position=rated_issue.position,
                        status=rated_issue.status,
                        relation="current" if rated_issue.id == issue.id else "previous",
                        rating=event.rating,
                        crossover_memberships=[],
                    )
                )

    return SeriesInfo(
        identity_source="comicvine",
        canonical_series_id=canonical_series_id,
        series_name=thread.title,
        average_rating=average_rating,
        ratings_count=ratings_count,
        previous_issue=previous_issue_response,
        recent_ratings=recent_ratings,
        highest_rating=highest_rating,
        lowest_rating=lowest_rating,
    )


async def _build_crossover_info(
    db: AsyncSession, user_id: int, issue: Issue, thread: Thread
) -> list["CrossoverInfo"]:
    """Build exact crossover context for the current issue."""
    from app.models.dependency_group import DependencyGroup, DependencyGroupMembership
    from app.schemas.reader_context import CrossoverInfo, LocalChainIssue, CrossoverMemberInfo

    # Get crossovers this thread belongs to
    memberships_result = await db.execute(
        select(DependencyGroupMembership)
        .where(DependencyGroupMembership.thread_id == thread.id)
    )
    memberships = memberships_result.scalars().all()

    if not memberships:
        return []

    group_ids = [m.group_id for m in memberships]
    groups_result = await db.execute(
        select(DependencyGroup).where(DependencyGroup.id.in_(group_ids))
    )
    groups = list(groups_result.scalars().all())

    crossovers = []
    for group in groups:
        # Get all member issues for this crossover (owned by user)
        member_memberships_result = await db.execute(
            select(DependencyGroupMembership)
            .where(
                DependencyGroupMembership.group_id == group.id,
                DependencyGroupMembership.issue_id.is_not(None),
            )
        )
        member_memberships = member_memberships_result.scalars().all()

        member_issue_ids = [m.issue_id for m in member_memberships if m.issue_id]
        member_issues = []
        if member_issue_ids:
            member_issues_result = await db.execute(
                select(Issue).where(Issue.id.in_(member_issue_ids))
            )
            member_issues = list(member_issues_result.scalars().all())

        # Check if current issue is a member
        applies_to_current = any(m.issue_id == issue.id for m in member_memberships)

        # Find next member (future issue in the same thread)
        next_member = None
        thread_member_issues = [i for i in member_issues if i.thread_id == thread.id]
        future_members = [i for i in thread_member_issues if i.position > issue.position]
        if future_members:
            next_member_issue = min(future_members, key=lambda i: i.position)
            next_member = LocalChainIssue(
                issue_id=next_member_issue.id,
                issue_number=next_member_issue.issue_number,
                position=next_member_issue.position,
                status=next_member_issue.status,
                relation="future",
                rating=None,
                crossover_memberships=[],
            )

        # Calculate crossover aggregates using effective ratings
        if member_issue_ids:
            rate_events_result = await db.execute(
                select(Event)
                .where(Event.type == "rate", Event.issue_id.in_(member_issue_ids))
                .order_by(Event.issue_id, Event.timestamp.desc())
            )
            rate_events = rate_events_result.scalars().all()

            latest_ratings: dict[int, float] = {}
            for event in rate_events:
                if event.issue_id and event.issue_id not in latest_ratings:
                    latest_ratings[event.issue_id] = event.rating

            ratings = list(latest_ratings.values())
            average_rating = sum(ratings) / len(ratings) if ratings else None
            ratings_count = len(ratings)
            read_count = sum(1 for i in member_issues if i.status == "read")
        else:
            average_rating = None
            ratings_count = 0
            read_count = 0

        # Build member info for the crossover
        member_info = []
        for member_issue in member_issues:
            member_info.append(
                CrossoverMemberInfo(
                    issue_id=member_issue.id,
                    issue_number=member_issue.issue_number,
                    rating=latest_ratings.get(member_issue.id) if member_issue_ids else None,
                    status=member_issue.status,
                )
            )

        crossovers.append(
            CrossoverInfo(
                id=group.id,
                name=group.name,
                applies_to_current_issue=applies_to_current,
                next_member=next_member,
                average_rating=average_rating,
                ratings_count=ratings_count,
                read_count=read_count,
            )
        )

    return crossovers


async def _build_local_chain(
    db: AsyncSession, user_id: int, issue: Issue, thread: Thread
) -> "LocalChainResponse":
    """Build bounded local same-thread chain with one-hop edges."""
    from app.schemas.reader_context import (
        LocalChainResponse,
        LocalChainIssue,
        LocalChainEdge,
        CrossoverMemberInfo,
    )

    # Get up to 5 same-thread issues centered on current: up to 2 before, current, up to 2 after
    thread_issues_result = await db.execute(
        select(Issue).where(Issue.thread_id == thread.id).order_by(Issue.position)
    )
    thread_issues = list(thread_issues_result.scalars().all())

    current_index = next((i for i, ti in enumerate(thread_issues) if ti.id == issue.id), 0)
    start = max(0, current_index - 2)
    end = min(len(thread_issues), current_index + 3)  # current + 2 after
    neighborhood_issues = thread_issues[start:end]

    # Get effective ratings for neighborhood issues
    neighborhood_issue_ids = [i.id for i in neighborhood_issues]
    rate_events_result = await db.execute(
        select(Event)
        .where(Event.type == "rate", Event.issue_id.in_(neighborhood_issue_ids))
        .order_by(Event.issue_id, Event.timestamp.desc())
    )
    rate_events = rate_events_result.scalars().all()

    latest_ratings: dict[int, float] = {}
    for event in rate_events:
        if event.issue_id and event.issue_id not in latest_ratings:
            latest_ratings[event.issue_id] = event.rating

    # Get crossover memberships for neighborhood issues
    memberships_result = await db.execute(
        select(DependencyGroupMembership)
        .where(DependencyGroupMembership.issue_id.in_(neighborhood_issue_ids))
    )
    memberships = memberships_result.scalars().all()

    group_ids = list({m.group_id for m in memberships})
    groups = {}
    if group_ids:
        groups_result = await db.execute(
            select(DependencyGroup).where(DependencyGroup.id.in_(group_ids))
        )
        groups = {g.id: g for g in groups_result.scalars().all()}

    # Group memberships by issue_id
    memberships_by_issue: dict[int, list[DependencyGroupMembership]] = {}
    for m in memberships:
        if m.issue_id:
            memberships_by_issue.setdefault(m.issue_id, []).append(m)

    # Build local chain issues
    local_issues = []
    for idx, ti in enumerate(neighborhood_issues):
        if idx == current_index - start:
            relation = "current"
        elif idx < current_index - start:
            relation = "previous" if idx == current_index - start - 1 else "previous"
        else:
            relation = "next" if idx == current_index - start + 1 else "future"

        # Get crossover memberships for this issue
        issue_memberships = memberships_by_issue.get(ti.id, [])
        crossover_memberships = []
        for m in issue_memberships:
            group = groups.get(m.group_id)
            if group:
                crossover_memberships.append(
                    CrossoverMemberInfo(
                        issue_id=ti.id,
                        issue_number=ti.issue_number,
                        rating=latest_ratings.get(ti.id),
                        status=ti.status,
                    )
                )

        local_issues.append(
            LocalChainIssue(
                issue_id=ti.id,
                issue_number=ti.issue_number,
                position=ti.position,
                status=ti.status,
                relation=relation,
                rating=latest_ratings.get(ti.id),
                crossover_memberships=crossover_memberships,
            )
        )

    # Get one-hop edges touching neighborhood issues
    # Edges where source or target is in the neighborhood
    neighborhood_issue_id_set = set(neighborhood_issue_ids)
    edges_result = await db.execute(
        select(Dependency)
        .where(
            (Dependency.source_issue_id.in_(neighborhood_issue_ids))
            | (Dependency.target_issue_id.in_(neighborhood_issue_ids))
        )
        .limit(20)
    )
    edges = list(edges_result.scalars().all())

    # Build edge responses with full context
    all_issue_ids = set()
    for edge in edges:
        all_issue_ids.add(edge.source_issue_id)
        all_issue_ids.add(edge.target_issue_id)

    all_issues = {}
    if all_issue_ids:
        all_issues_result = await db.execute(
            select(Issue).where(Issue.id.in_(all_issue_ids))
        )
        all_issues = {i.id: i for i in all_issues_result.scalars().all()}

    local_edges = []
    for edge in edges:
        source_issue = all_issues.get(edge.source_issue_id)
        target_issue = all_issues.get(edge.target_issue_id)

        if source_issue and target_issue:
            source_thread = await db.get(Thread, source_issue.thread_id)
            target_thread = await db.get(Thread, target_issue.thread_id)

            if source_thread and target_thread:
                local_edges.append(
                    LocalChainEdge(
                        dependency_id=edge.id,
                        source_issue_id=edge.source_issue_id,
                        target_issue_id=edge.target_issue_id,
                        source_issue_number=source_issue.issue_number,
                        target_issue_number=target_issue.issue_number,
                        source_thread_id=source_thread.id,
                        target_thread_id=target_thread.id,
                        source_thread_title=source_thread.title,
                        target_thread_title=target_thread.title,
                        note=edge.note,
                    )
                )

    return LocalChainResponse(issues=local_issues, edges=local_edges)
