"""Snapshot service for undo functionality."""

from datetime import datetime, UTC

from sqlalchemy import delete, or_, update, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import Event, Snapshot, Thread
from app.models import Session as SessionModel
from app.models.user import User


async def restore_threads_from_snapshot(
    db: AsyncSession,
    snapshot: Snapshot,
    user: User,
    session: SessionModel | None = None,
) -> None:
    """Restore all thread states from a snapshot.

    This function:
    1. Deletes threads created after the snapshot
    2. Restores thread states (issues_remaining, queue_position, status, format) from snapshot
    3. Recreates threads that were deleted after the snapshot

    Args:
        db: Database session
        snapshot: The snapshot to restore from
        user: The user whose threads to restore
        session: Optional session model (used for pending_thread_id cleanup and user_id fallback)
    """
    snapshot_thread_ids = {int(tid) for tid in snapshot.thread_states.keys()}

    result = await db.execute(select(Thread).where(Thread.user_id == user.id))
    current_threads = result.scalars().all()
    current_thread_ids = {thread.id for thread in current_threads}

    # Delete threads that were created after the snapshot
    threads_to_delete = current_thread_ids - snapshot_thread_ids
    if threads_to_delete:
        # Clear pending_thread_id if it references a thread we're deleting
        if session is not None:
            await db.execute(
                update(SessionModel)
                .where(SessionModel.id == session.id)
                .where(SessionModel.pending_thread_id.in_(threads_to_delete))
                .values(pending_thread_id=None)
            )

        # Clear event references to threads we're deleting
        await db.execute(
            update(Event)
            .where(
                or_(
                    Event.thread_id.in_(threads_to_delete),
                    Event.selected_thread_id.in_(threads_to_delete),
                )
            )
            .values(thread_id=None, selected_thread_id=None)
        )

        # Delete the threads
        await db.execute(
            delete(Thread).where(Thread.id.in_(threads_to_delete)).where(Thread.user_id == user.id)
        )

        db.expire_all()

    # Restore or recreate threads from snapshot state
    fallback_user_id = session.user_id if session else user.id
    for thread_id, state in snapshot.thread_states.items():
        thread_id_int = int(thread_id)
        thread = await db.get(Thread, thread_id_int)
        if thread:
            # Update existing thread
            await _update_thread_from_state(thread, state)
        else:
            # Recreate deleted thread
            new_thread = await _create_thread_from_state(thread_id, state, fallback_user_id)
            db.add(new_thread)


async def _update_thread_from_state(thread: Thread, state: dict) -> None:
    """Update an existing thread from snapshot state.

    Args:
        thread: The thread to update
        state: The snapshot state dict for this thread
    """
    if "title" in state:
        thread.title = state["title"]
    if "format" in state:
        thread.format = state["format"]
    thread.issues_remaining = state.get("issues_remaining", thread.issues_remaining)
    thread.last_rating = state.get("last_rating", thread.last_rating)
    thread.queue_position = state.get("queue_position", thread.queue_position)
    thread.status = state.get("status", thread.status)
    if "review_url" in state:
        thread.review_url = state["review_url"]
    if "notes" in state:
        thread.notes = state["notes"]
    if "is_test" in state:
        thread.is_test = state["is_test"]
    if state.get("last_activity_at"):
        thread.last_activity_at = datetime.fromisoformat(state["last_activity_at"])
    if state.get("last_review_at"):
        thread.last_review_at = datetime.fromisoformat(state["last_review_at"])


async def _create_thread_from_state(
    thread_id: str | int,
    state: dict,
    fallback_user_id: int,
) -> Thread:
    """Create a new thread from snapshot state.

    Args:
        thread_id: The thread ID to use
        state: The snapshot state dict for this thread
        fallback_user_id: User ID to use if not in state

    Returns:
        A new Thread instance (not yet added to session)
    """
    new_thread = Thread(
        id=int(thread_id),
        title=state.get("title", "Unknown Thread"),
        format=state.get("format", "comic"),
        issues_remaining=state.get("issues_remaining", 0),
        last_rating=state.get("last_rating"),
        queue_position=state.get("queue_position", 1),
        status=state.get("status", "active"),
        review_url=state.get("review_url"),
        notes=state.get("notes"),
        is_test=state.get("is_test", False),
        user_id=state.get("user_id", fallback_user_id),
        created_at=datetime.fromisoformat(state["created_at"])
        if state.get("created_at")
        else datetime.now(UTC),
    )
    if state.get("last_activity_at"):
        new_thread.last_activity_at = datetime.fromisoformat(state["last_activity_at"])
    if state.get("last_review_at"):
        new_thread.last_review_at = datetime.fromisoformat(state["last_review_at"])
    return new_thread


async def restore_session_state_from_snapshot(
    session: SessionModel,
    snapshot: Snapshot,
) -> None:
    """Restore session-level state from a snapshot.

    Args:
        session: The session to update
        snapshot: The snapshot to restore from
    """
    if snapshot.session_state:
        session.start_die = snapshot.session_state.get("start_die", session.start_die)
        session.manual_die = snapshot.session_state.get("manual_die", session.manual_die)
