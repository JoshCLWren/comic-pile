"""Rate API endpoint."""

from datetime import UTC, datetime

from fastapi import APIRouter, Depends, HTTPException, Request, status
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession
from typing import Annotated

from app.auth import get_current_user
from app.config import get_rating_settings
from app.database import get_db
from app.middleware import limiter
from app.models import Event, Issue, Snapshot, Thread
from app.models import Session as SessionModel
from app.models.user import User
from app.schemas import RateRequest, ThreadResponse
from app.api.thread import thread_to_response
from comic_pile.dependencies import refresh_user_blocked_status
from comic_pile.dice_ladder import step_down, step_up
from comic_pile.queue import get_roll_pool, move_to_back, move_to_front
from comic_pile.session import get_current_die

router = APIRouter()


async def snapshot_thread_states(
    db: AsyncSession, session_id: int, event_id: int, user_id: int, commit: bool = True
) -> None:
    """Create a snapshot of all thread states for undo functionality.

    Args:
        db: SQLAlchemy session for database operations.
        session_id: The session ID to create snapshot for.
        event_id: The event ID that triggered the snapshot.
        user_id: The user ID to snapshot threads for.
        commit: Whether to commit inside this helper.
    """
    from app.models import Issue

    result = await db.execute(select(Thread).where(Thread.user_id == user_id))
    threads = result.scalars().all()

    thread_states = {}
    for thread in threads:
        base_state = {
            "title": thread.title,
            "format": thread.format,
            "issues_remaining": thread.issues_remaining,
            "last_rating": thread.last_rating,
            "last_activity_at": thread.last_activity_at.isoformat()
            if thread.last_activity_at
            else None,
            "queue_position": thread.queue_position,
            "status": thread.status,
            "review_url": thread.review_url,
            "last_review_at": thread.last_review_at.isoformat() if thread.last_review_at else None,
            "notes": thread.notes,
            "is_test": thread.is_test,
            "created_at": thread.created_at.isoformat(),
            "user_id": thread.user_id,
        }

        if thread.uses_issue_tracking():
            issues_result = await db.execute(
                select(Issue).where(Issue.thread_id == thread.id).order_by(Issue.issue_number)
            )
            issues = issues_result.scalars().all()

            base_state["issue_states"] = [
                {
                    "id": issue.id,
                    "number": issue.issue_number,
                    "status": issue.status,
                    "read_at": issue.read_at.isoformat() if issue.read_at else None,
                }
                for issue in issues
            ]
            base_state["total_issues"] = thread.total_issues
            base_state["next_unread_issue_id"] = thread.next_unread_issue_id
            base_state["reading_progress"] = thread.reading_progress
        else:
            base_state["issue_states"] = None
            base_state["total_issues"] = None
            base_state["next_unread_issue_id"] = None
            base_state["reading_progress"] = None

        thread_states[thread.id] = base_state

    session = await db.get(SessionModel, session_id)
    session_state = None
    if session:
        session_state = {
            "start_die": session.start_die,
            "manual_die": session.manual_die,
        }

    snapshot = Snapshot(
        session_id=session_id,
        event_id=event_id,
        thread_states=thread_states,
        session_state=session_state,
        description="After rating",
    )
    db.add(snapshot)
    if commit:
        await db.commit()


clear_cache = None


def _get_rating_limits() -> tuple[float, float, float]:
    """Get rating min, max, and threshold from config.

    Returns:
        Tuple of (rating_min, rating_max, rating_threshold).
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
    """Rate current reading and update thread.

    Args:
        request: FastAPI request object for rate limiting.
        rate_data: Rating request data.
        current_user: The authenticated user making the request.
        db: SQLAlchemy session for database operations.

    Returns:
        ThreadResponse with updated thread details.

    Raises:
        HTTPException: If no active session, invalid rating, or thread not found.
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
    thread = None
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
            .where(Event.type == "roll")
            .where(Event.selected_thread_id.is_not(None))
            .order_by(Event.timestamp.desc())
        )
        last_roll_event = result.scalars().first()

        if not last_roll_event:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="No active thread. Please roll the dice first.",
            )

        result = await db.execute(
            select(Thread)
            .where(Thread.id == last_roll_event.selected_thread_id)
            .where(Thread.user_id == user_id)
        )
        thread = result.scalar_one_or_none()
        if not thread:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Thread {last_roll_event.selected_thread_id} not found",
            )
    thread_id = thread.id

    current_die = await get_current_die(current_session_id, db)

    rating_min, rating_max, rating_threshold = _get_rating_limits()

    if rate_data.rating < rating_min or rate_data.rating > rating_max:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Rating must be between {rating_min} and {rating_max}",
        )

    # Comic Pile reads one issue per rating action by design.
    if thread.uses_issue_tracking():
        if thread.next_unread_issue_id:
            issue_result = await db.execute(
                select(Issue).where(Issue.id == thread.next_unread_issue_id)
            )
            issue = issue_result.scalar_one_or_none()

            if issue:
                issue.status = "read"
                issue.read_at = datetime.now(UTC)

                next_result = await db.execute(
                    select(Issue)
                    .where(Issue.thread_id == thread.id)
                    .where(Issue.status == "unread")
                    .order_by(Issue.issue_number)
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

        issues_read = 1
        thread_issues_remaining = thread.issues_remaining
    else:
        issues_read = 1 if thread.issues_remaining > 0 else 0
        thread.issues_remaining -= issues_read
        thread_issues_remaining = thread.issues_remaining

    thread.last_rating = rate_data.rating
    thread.last_activity_at = datetime.now(UTC)

    if rate_data.rating >= rating_threshold:
        new_die = step_down(current_die)
    else:
        new_die = step_up(current_die)

    event = Event(
        type="rate",
        session_id=current_session_id,
        thread_id=thread_id,
        rating=rate_data.rating,
        issues_read=issues_read,
        die=current_die,
        die_after=new_die,
    )
    db.add(event)

    should_complete_thread = thread_issues_remaining <= 0

    if should_complete_thread:
        await db.execute(
            update(Thread)
            .where(Thread.id == thread_id)
            .where(Thread.user_id == user_id)
            .values(status="completed")
        )

    if should_complete_thread:
        await move_to_back(thread_id, user_id, db, commit=False)
        await refresh_user_blocked_status(user_id, db)
    elif rate_data.rating >= rating_threshold:
        await move_to_front(thread_id, user_id, db, commit=False)
    else:
        await move_to_back(thread_id, user_id, db, commit=False)

    if rate_data.finish_session:
        current_session.ended_at = datetime.now(UTC)
        current_session.snoozed_thread_ids = None

    if clear_cache:
        clear_cache()

    if rate_data.finish_session:
        current_session.pending_thread_id = None
        current_session.pending_thread_updated_at = None
    else:
        snoozed_ids = current_session.snoozed_thread_ids or []
        roll_pool = await get_roll_pool(user_id, db, snoozed_ids)

        next_pending_thread_id = next(
            (candidate.id for candidate in roll_pool if candidate.id != thread_id),
            roll_pool[0].id if roll_pool else None,
        )

        current_session.pending_thread_id = next_pending_thread_id
        current_session.pending_thread_updated_at = (
            datetime.now(UTC) if next_pending_thread_id is not None else None
        )

    await db.flush()
    await db.refresh(event)
    event_id = event.id
    await snapshot_thread_states(db, current_session_id, event_id, user_id, commit=False)
    await db.commit()

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
