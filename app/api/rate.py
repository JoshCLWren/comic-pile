"""Rate API endpoint."""

from datetime import UTC, datetime
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Request, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.thread import thread_to_response
from app.auth import get_current_user
from app.cache_invalidation import invalidate_user_view
from app.config import get_rating_settings
from app.database import get_db
from app.middleware import limiter
from app.models import Event, Issue, Snapshot, Thread
from app.models import Session as SessionModel
from app.models.user import User
from app.schemas import RateRequest, ThreadResponse
from app.services.snapshot_contract import (
    BLOCKED_CHANGES_KEY,
    QUEUE_CHANGES_KEY,
    SNAPSHOT_VERSION,
    SNAPSHOT_VERSION_KEY,
    USES_ISSUE_TRACKING_KEY,
)
from comic_pile.dependencies import refresh_user_blocked_status
from comic_pile.dice_ladder import step_down, step_up
from comic_pile.queue import move_to_back, move_to_front, move_to_safe_position
from comic_pile.session import get_current_die

router = APIRouter()


async def _capture_thread_pre_state(thread: Thread, db: AsyncSession) -> dict:
    """Extract a thread's full pre-rating state as a plain dictionary.

    Args:
        thread: Thread being rated.
        db: Database session.

    Returns:
        Serializable pre-rating thread state.
    """
    uses_issue_tracking = thread.uses_issue_tracking()
    state: dict = {
        "title": thread.title,
        "format": thread.format,
        "issues_remaining": thread.issues_remaining,
        "last_rating": thread.last_rating,
        "last_activity_at": thread.last_activity_at.isoformat()
        if thread.last_activity_at
        else None,
        "queue_position": thread.queue_position,
        "status": thread.status,
        "notes": thread.notes,
        "is_test": thread.is_test,
        "created_at": thread.created_at.isoformat(),
        "user_id": thread.user_id,
        "is_blocked": thread.is_blocked,
        USES_ISSUE_TRACKING_KEY: uses_issue_tracking,
    }

    if uses_issue_tracking:
        issues_result = await db.execute(
            select(Issue).where(Issue.thread_id == thread.id).order_by(Issue.position)
        )
        issues = issues_result.scalars().all()
        state["issue_states"] = [
            {
                "id": issue.id,
                "number": issue.issue_number,
                "status": issue.status,
                "read_at": issue.read_at.isoformat() if issue.read_at else None,
                "position": issue.position,
            }
            for issue in issues
        ]
        state["total_issues"] = thread.total_issues
        state["next_unread_issue_id"] = thread.next_unread_issue_id
        state["reading_progress"] = thread.reading_progress
    else:
        state["issue_states"] = None
        state["total_issues"] = None
        state["next_unread_issue_id"] = None
        state["reading_progress"] = None

    return state


async def snapshot_thread_states(
    db: AsyncSession,
    session_id: int,
    event_id: int,
    user_id: int,
    commit: bool = True,
    *,
    rated_thread_id: int | None = None,
    rated_thread_pre_state: dict | None = None,
    queue_position_changes: dict[int, int] | None = None,
    blocked_changes: dict[int, bool] | None = None,
    pre_session_state: dict | None = None,
) -> None:
    """Create a versioned delta or legacy full undo snapshot.

    Args:
        db: SQLAlchemy session.
        session_id: Session to snapshot.
        event_id: Event that triggered the snapshot.
        user_id: Thread owner.
        commit: Whether to commit inside this helper.
        rated_thread_id: ID of the rated thread in delta mode.
        rated_thread_pre_state: Pre-rating state of the rated thread.
        queue_position_changes: Changed thread IDs mapped to old positions.
        blocked_changes: Changed thread IDs mapped to old blocked flags.
        pre_session_state: Pre-rating session fields.

    Raises:
        ValueError: If delta state is supplied without a rated thread ID.
    """
    if rated_thread_pre_state is not None:
        if rated_thread_id is None:
            raise ValueError(
                "rated_thread_id is required when rated_thread_pre_state is set"
            )

        thread_states: dict = {
            SNAPSHOT_VERSION_KEY: SNAPSHOT_VERSION,
            str(rated_thread_id): rated_thread_pre_state,
        }
        if queue_position_changes:
            thread_states[QUEUE_CHANGES_KEY] = {
                str(thread_id): old_position
                for thread_id, old_position in queue_position_changes.items()
            }
        if blocked_changes:
            thread_states[BLOCKED_CHANGES_KEY] = {
                str(thread_id): old_value
                for thread_id, old_value in blocked_changes.items()
            }

        db.add(
            Snapshot(
                session_id=session_id,
                event_id=event_id,
                thread_states=thread_states,
                session_state=pre_session_state,
                description="After rating",
            )
        )
        if commit:
            await db.commit()
        return

    result = await db.execute(select(Thread).where(Thread.user_id == user_id))
    threads = result.scalars().all()
    thread_states = {
        thread.id: await _capture_thread_pre_state(thread, db) for thread in threads
    }

    session = await db.get(SessionModel, session_id)
    session_state = None
    if session:
        session_state = {
            "start_die": session.start_die,
            "manual_die": session.manual_die,
        }

    db.add(
        Snapshot(
            session_id=session_id,
            event_id=event_id,
            thread_states=thread_states,
            session_state=session_state,
            description="After rating",
        )
    )
    if commit:
        await db.commit()


def _get_rating_limits() -> tuple[float, float, float]:
    """Get rating min, max, and threshold from config.

    Returns:
        Tuple of rating minimum, maximum, and threshold.
    """
    settings = get_rating_settings()
    return settings.rating_min, settings.rating_max, settings.rating_threshold


@router.post("/", response_model=ThreadResponse)
@limiter.limit("60/minute")
async def rate_thread(
    request: Request,
    rate_data: RateRequest,
    current_user: Annotated[User, Depends(get_current_user)],
    db: AsyncSession = Depends(get_db),
) -> ThreadResponse:
    """Rate current reading and update its thread.

    Args:
        request: FastAPI request object for rate limiting.
        rate_data: Rating request data.
        current_user: Authenticated user making the request.
        db: SQLAlchemy session.

    Returns:
        Updated thread response.

    Raises:
        HTTPException: If no active session, rating, or thread is valid.
    """
    user_id = current_user.id
    result = await db.execute(
        select(SessionModel)
        .where(SessionModel.user_id == user_id)
        .where(SessionModel.ended_at.is_(None))
        .order_by(SessionModel.started_at.desc())
    )
    current_session = result.scalars().first()
    if not current_session:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="No active session. Please roll the dice first.",
        )

    current_session_id = current_session.id
    target_thread_id = current_session.pending_thread_id

    if target_thread_id is not None:
        result = await db.execute(
            select(Thread).where(Thread.id == target_thread_id).where(Thread.user_id == user_id)
        )
        thread = result.scalar_one_or_none()
        if not thread:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Thread {target_thread_id} not found",
            )
    else:
        result = await db.execute(
            select(Event)
            .where(Event.session_id == current_session_id)
            .where(Event.type.in_(["roll", "rate", "snooze", "rolled_but_skipped"]))
            .order_by(Event.timestamp.desc(), Event.id.desc())
        )
        latest_action_event = result.scalars().first()
        if (
            not latest_action_event
            or latest_action_event.type != "roll"
            or latest_action_event.selected_thread_id is None
        ):
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="No active thread. Please roll the dice first.",
            )

        result = await db.execute(
            select(Thread)
            .where(Thread.id == latest_action_event.selected_thread_id)
            .where(Thread.user_id == user_id)
        )
        thread = result.scalar_one_or_none()
        if not thread:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Thread {latest_action_event.selected_thread_id} not found",
            )

    thread_id = thread.id
    pre_thread_state = await _capture_thread_pre_state(thread, db)
    current_die = await get_current_die(current_session_id, db)
    pre_session_state = {
        "start_die": current_session.start_die,
        "manual_die": current_session.manual_die,
        "current_die": current_die,
        "pending_thread_id": current_session.pending_thread_id,
        "pending_thread_updated_at": current_session.pending_thread_updated_at.isoformat()
        if current_session.pending_thread_updated_at
        else None,
        "ended_at": current_session.ended_at.isoformat()
        if current_session.ended_at
        else None,
        "snoozed_thread_ids": (
            list(current_session.snoozed_thread_ids)
            if current_session.snoozed_thread_ids
            else None
        ),
    }

    issues_remaining = await thread.get_issues_remaining(db)
    if issues_remaining <= 0:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Thread {thread_id} has no issues remaining",
        )

    if not thread.uses_issue_tracking() and rate_data.issue_number is not None:
        issue_number = rate_data.issue_number
        result = await db.execute(
            select(Issue)
            .where(Issue.thread_id == thread.id)
            .where(Issue.issue_number == issue_number)
        )
        current_issue = result.scalar_one_or_none()

        if not current_issue:
            try:
                issue_num_int = int(issue_number)
                total_issues = issue_num_int + max(thread.issues_remaining - 1, 0)
                if total_issues > 1000:
                    raise HTTPException(
                        status_code=status.HTTP_400_BAD_REQUEST,
                        detail=f"Total issues ({total_issues}) exceeds reasonable limit",
                    )
                for issue_position in range(1, total_issues + 1):
                    db.add(
                        Issue(
                            thread_id=thread.id,
                            issue_number=str(issue_position),
                            status="read" if issue_position < issue_num_int else "unread",
                            read_at=datetime.now(UTC)
                            if issue_position < issue_num_int
                            else None,
                            position=issue_position,
                        )
                    )
                result = await db.execute(
                    select(Issue)
                    .where(Issue.thread_id == thread.id)
                    .where(Issue.issue_number == issue_number)
                )
                current_issue = result.scalar_one_or_none()
                if not current_issue:
                    raise HTTPException(
                        status_code=status.HTTP_400_BAD_REQUEST,
                        detail=f"Failed to create issue '{issue_number}'.",
                    )
            except ValueError:
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail=(
                        f"Non-numeric issue '{issue_number}' not found in thread. "
                        "Add it via Edit Thread first."
                    ),
                ) from None
            except HTTPException:
                raise
            except Exception as error:
                await db.rollback()
                raise HTTPException(
                    status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                    detail="Migration failed.",
                ) from error

        all_issues_result = await db.execute(
            select(Issue).where(Issue.thread_id == thread.id).order_by(Issue.position)
        )
        all_issues = all_issues_result.scalars().all()
        for issue in all_issues:
            if issue.position < current_issue.position and issue.status != "read":
                issue.status = "read"
                issue.read_at = datetime.now(UTC)
            elif issue.position == current_issue.position:
                issue.status = "unread"
                issue.read_at = None
        thread.total_issues = len(all_issues)
        thread.next_unread_issue_id = current_issue.id
        thread.reading_progress = "in_progress"

    rating_min, rating_max, rating_threshold = _get_rating_limits()
    if rate_data.rating < rating_min or rate_data.rating > rating_max:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Rating must be between {rating_min} and {rating_max}",
        )

    issues_read = 0
    rated_issue_id: int | None = None
    rated_issue_number: str | None = None

    if thread.uses_issue_tracking():
        if thread.next_unread_issue_id:
            issue_result = await db.execute(
                select(Issue)
                .where(Issue.id == thread.next_unread_issue_id)
                .where(Issue.thread_id == thread.id)
            )
            issue = issue_result.scalar_one_or_none()
            if issue and issue.status == "unread":
                issue.status = "read"
                issue.read_at = datetime.now(UTC)
                rated_issue_id = issue.id
                rated_issue_number = issue.issue_number
                issues_read = 1

                next_result = await db.execute(
                    select(Issue)
                    .where(Issue.thread_id == thread.id)
                    .where(Issue.status == "unread")
                    .order_by(Issue.position, Issue.id)
                    .limit(1)
                )
                next_issue = next_result.scalar_one_or_none()
                if next_issue:
                    thread.next_unread_issue_id = next_issue.id
                    thread.reading_progress = "in_progress"
                    thread.issues_remaining = await thread.get_issues_remaining(db)
                else:
                    thread.next_unread_issue_id = None
                    thread.reading_progress = "completed"
                    thread.status = "completed"
                    thread.issues_remaining = 0

        thread_issues_remaining = thread.issues_remaining
    else:
        issues_read = 1 if thread.issues_remaining > 0 else 0
        thread.issues_remaining -= issues_read
        thread_issues_remaining = thread.issues_remaining

    thread.last_rating = rate_data.rating
    thread.last_activity_at = datetime.now(UTC)
    new_die = (
        step_down(current_die)
        if rate_data.rating >= rating_threshold
        else step_up(current_die)
    )

    event = Event(
        type="rate",
        session_id=current_session_id,
        thread_id=thread_id,
        rating=rate_data.rating,
        issues_read=issues_read,
        die=current_die,
        die_after=new_die,
        issue_id=rated_issue_id,
        issue_number=rated_issue_number,
    )
    db.add(event)

    should_complete_thread = thread_issues_remaining <= 0
    if should_complete_thread:
        thread.status = "completed"
        queue_position_changes = await move_to_back(
            thread_id,
            user_id,
            db,
            commit=False,
        )
        blocked_changes = await refresh_user_blocked_status(user_id, db)
    elif rate_data.rating >= rating_threshold:
        queue_position_changes = await move_to_front(
            thread_id,
            user_id,
            db,
            commit=False,
        )
        blocked_changes = {}
    else:
        queue_position_changes = await move_to_safe_position(
            thread_id,
            user_id,
            new_die,
            db,
            excluded_thread_ids=current_session.snoozed_thread_ids,
        )
        blocked_changes = {}

    if rate_data.finish_session:
        current_session.ended_at = datetime.now(UTC)
        current_session.snoozed_thread_ids = None

    current_session.pending_thread_id = None
    current_session.pending_thread_updated_at = None

    await db.flush()
    await snapshot_thread_states(
        db,
        current_session_id,
        event.id,
        user_id,
        commit=False,
        rated_thread_id=thread_id,
        rated_thread_pre_state=pre_thread_state,
        queue_position_changes=queue_position_changes,
        blocked_changes=blocked_changes,
        pre_session_state=pre_session_state,
    )
    await db.commit()

    await invalidate_user_view(user_id)

    result = await db.execute(
        select(Thread).where(Thread.id == thread_id).where(Thread.user_id == user_id)
    )
    updated_thread = result.scalar_one_or_none()
    if not updated_thread:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Thread {thread_id} not found",
        )

    return await thread_to_response(updated_thread, db)
