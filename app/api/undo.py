"""Undo API endpoints."""

import asyncio
from datetime import UTC, datetime
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import and_, case, delete, func, or_, select, update
from sqlalchemy.exc import OperationalError
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.session import _invalidate_session_caches, build_ladder_path
from app.auth import get_current_user
from app.cache import invalidate_cache
from app.database import get_db
from app.models import Event, Issue, Snapshot, Thread
from app.models import Session as SessionModel
from app.models.user import User
from app.schemas import ActiveThreadInfo, SessionResponse
from app.services.snapshot_contract import (
    BLOCKED_CHANGES_KEY,
    QUEUE_CHANGES_KEY,
    SNAPSHOT_VERSION,
    SNAPSHOT_VERSION_KEY,
    USES_ISSUE_TRACKING_KEY,
)
from comic_pile.session import get_current_die

router = APIRouter(tags=["undo"])


def _deserialize_datetime(value: str | None) -> datetime | None:
    """Deserialize an optional ISO datetime value."""
    return datetime.fromisoformat(value) if value else None


def _is_delta_snapshot(snapshot: Snapshot) -> bool:
    """Return whether a snapshot uses the version-two delta contract."""
    thread_states = snapshot.thread_states or {}
    return thread_states.get(SNAPSHOT_VERSION_KEY) == SNAPSHOT_VERSION


async def _latest_delta_snapshot(
    db: AsyncSession,
    session_id: int,
) -> Snapshot | None:
    """Return the newest unconsumed delta snapshot for a session."""
    result = await db.execute(
        select(Snapshot)
        .where(Snapshot.session_id == session_id)
        .order_by(Snapshot.created_at.desc(), Snapshot.id.desc())
    )
    return next(
        (snapshot for snapshot in result.scalars().all() if _is_delta_snapshot(snapshot)),
        None,
    )


async def _restore_issue_states(
    db: AsyncSession,
    thread: Thread,
    state: dict,
) -> None:
    """Restore issue state in place so surviving associations remain intact."""
    has_tracking_marker = USES_ISSUE_TRACKING_KEY in state
    has_issue_payload = "issue_states" in state
    if not has_tracking_marker and not has_issue_payload:
        return

    uses_issue_tracking = state.get(
        USES_ISSUE_TRACKING_KEY,
        state.get("issue_states") is not None,
    )
    result = await db.execute(
        select(Issue).where(Issue.thread_id == thread.id).order_by(Issue.position)
    )
    existing_issues = list(result.scalars().all())

    thread.next_unread_issue_id = None
    await db.flush()

    if not uses_issue_tracking:
        if existing_issues:
            await db.execute(
                delete(Issue).where(Issue.id.in_([issue.id for issue in existing_issues]))
            )
        thread.total_issues = None
        thread.next_unread_issue_id = None
        thread.reading_progress = None
        thread.issues_remaining = state.get(
            "issues_remaining",
            thread.issues_remaining,
        )
        return

    snapshot_issues = state.get("issue_states") or []
    snapshot_ids = {int(issue_state["id"]) for issue_state in snapshot_issues}
    existing_by_id = {issue.id: issue for issue in existing_issues}
    extra_ids = [issue.id for issue in existing_issues if issue.id not in snapshot_ids]
    if extra_ids:
        await db.execute(delete(Issue).where(Issue.id.in_(extra_ids)))

    for fallback_position, issue_state in enumerate(snapshot_issues, start=1):
        issue_id = int(issue_state["id"])
        issue = existing_by_id.get(issue_id)
        if issue is None:
            issue = Issue(id=issue_id, thread_id=thread.id)
            db.add(issue)
        issue.issue_number = issue_state["number"]
        issue.status = issue_state["status"]
        issue.read_at = _deserialize_datetime(issue_state.get("read_at"))
        issue.position = issue_state.get("position", fallback_position)

    await db.flush()
    thread.total_issues = state.get("total_issues")
    thread.next_unread_issue_id = state.get("next_unread_issue_id")
    thread.reading_progress = state.get("reading_progress")
    thread.issues_remaining = state.get(
        "issues_remaining",
        thread.issues_remaining,
    )


async def _restore_thread_from_state(
    db: AsyncSession,
    thread_id: int,
    state: dict,
    session_user_id: int,
) -> None:
    """Restore one thread and its issue state from a snapshot payload."""
    thread = await db.get(Thread, thread_id)
    if thread is None:
        thread = Thread(
            id=thread_id,
            title=state.get("title", "Unknown Thread"),
            format=state.get("format", "comic"),
            issues_remaining=state.get("issues_remaining", 0),
            last_rating=state.get("last_rating"),
            queue_position=state.get("queue_position", 1),
            status=state.get("status", "active"),
            review_url=state.get("review_url"),
            notes=state.get("notes"),
            is_test=state.get("is_test", False),
            is_blocked=state.get("is_blocked", False),
            user_id=state.get("user_id", session_user_id),
            created_at=_deserialize_datetime(state.get("created_at"))
            or datetime.now(UTC),
        )
        thread.last_activity_at = _deserialize_datetime(state.get("last_activity_at"))
        thread.last_review_at = _deserialize_datetime(state.get("last_review_at"))
        db.add(thread)
        await db.flush()
    else:
        if "title" in state:
            thread.title = state["title"]
        if "format" in state:
            thread.format = state["format"]
        if "issues_remaining" in state:
            thread.issues_remaining = state["issues_remaining"]
        if "last_rating" in state:
            thread.last_rating = state["last_rating"]
        if "queue_position" in state:
            thread.queue_position = state["queue_position"]
        if "status" in state:
            thread.status = state["status"]
        if "review_url" in state:
            thread.review_url = state["review_url"]
        if "notes" in state:
            thread.notes = state["notes"]
        if "is_test" in state:
            thread.is_test = state["is_test"]
        if "is_blocked" in state:
            thread.is_blocked = state["is_blocked"]
        if "last_activity_at" in state:
            thread.last_activity_at = _deserialize_datetime(state["last_activity_at"])
        if "last_review_at" in state:
            thread.last_review_at = _deserialize_datetime(state["last_review_at"])

    await _restore_issue_states(db, thread, state)


async def _restore_from_full_snapshot(
    db: AsyncSession,
    session: SessionModel,
    snapshot: Snapshot,
    session_id: int,
) -> None:
    """Restore a legacy or session-start full-library snapshot."""
    snapshot_thread_ids = {int(thread_id) for thread_id in snapshot.thread_states}

    result = await db.execute(select(Thread).where(Thread.user_id == session.user_id))
    current_threads = result.scalars().all()
    current_thread_ids = {thread.id for thread in current_threads}
    threads_to_delete = current_thread_ids - snapshot_thread_ids

    if threads_to_delete:
        await db.execute(
            update(SessionModel)
            .where(SessionModel.id == session_id)
            .where(SessionModel.pending_thread_id.in_(threads_to_delete))
            .values(pending_thread_id=None)
        )
        await db.execute(
            update(Event)
            .where(
                or_(
                    Event.thread_id.in_(threads_to_delete),
                    Event.selected_thread_id.in_(threads_to_delete),
                )
            )
            .values(
                thread_id=case(
                    (Event.thread_id.in_(threads_to_delete), None),
                    else_=Event.thread_id,
                ),
                selected_thread_id=case(
                    (Event.selected_thread_id.in_(threads_to_delete), None),
                    else_=Event.selected_thread_id,
                ),
            )
        )
        await db.execute(
            delete(Thread)
            .where(Thread.id.in_(threads_to_delete))
            .where(Thread.user_id == session.user_id)
        )
        db.expire_all()

    for thread_id, state in snapshot.thread_states.items():
        await _restore_thread_from_state(
            db,
            int(thread_id),
            state,
            session.user_id,
        )

    if snapshot.session_state:
        session.start_die = snapshot.session_state.get("start_die", session.start_die)
        session.manual_die = snapshot.session_state.get("manual_die", session.manual_die)


async def _restore_from_delta_snapshot(
    db: AsyncSession,
    session: SessionModel,
    snapshot: Snapshot,
) -> None:
    """Restore only state changed by one version-two rating snapshot."""
    thread_states = snapshot.thread_states or {}
    for thread_id, state in thread_states.items():
        if thread_id.startswith("_"):
            continue
        await _restore_thread_from_state(
            db,
            int(thread_id),
            state,
            session.user_id,
        )

    queue_changes = {
        int(thread_id): old_position
        for thread_id, old_position in thread_states.get(QUEUE_CHANGES_KEY, {}).items()
    }
    if queue_changes:
        await db.execute(
            update(Thread)
            .where(Thread.user_id == session.user_id)
            .where(Thread.id.in_(queue_changes))
            .values(
                queue_position=case(
                    queue_changes,
                    value=Thread.id,
                    else_=Thread.queue_position,
                )
            )
        )

    blocked_changes = {
        int(thread_id): old_value
        for thread_id, old_value in thread_states.get(BLOCKED_CHANGES_KEY, {}).items()
    }
    if blocked_changes:
        await db.execute(
            update(Thread)
            .where(Thread.user_id == session.user_id)
            .where(Thread.id.in_(blocked_changes))
            .values(
                is_blocked=case(
                    blocked_changes,
                    value=Thread.id,
                    else_=Thread.is_blocked,
                )
            )
        )

    session_state = snapshot.session_state
    if session_state:
        session.start_die = session_state.get("start_die", session.start_die)
        session.manual_die = session_state.get("manual_die", session.manual_die)
        if "pending_thread_id" in session_state:
            session.pending_thread_id = session_state["pending_thread_id"]
        if "pending_thread_updated_at" in session_state:
            session.pending_thread_updated_at = _deserialize_datetime(
                session_state["pending_thread_updated_at"]
            )
        if "ended_at" in session_state:
            session.ended_at = _deserialize_datetime(session_state["ended_at"])
        if "snoozed_thread_ids" in session_state:
            session.snoozed_thread_ids = session_state["snoozed_thread_ids"]


async def _record_undo_event(
    db: AsyncSession,
    snapshot: Snapshot,
    session_id: int,
) -> None:
    """Append a compensating history event with the restored die value."""
    target_event = (
        await db.get(Event, snapshot.event_id)
        if snapshot.event_id is not None
        else None
    )
    restored_die = None
    if snapshot.session_state:
        restored_die = snapshot.session_state.get("current_die")
    if restored_die is None and target_event is not None:
        restored_die = target_event.die

    db.add(
        Event(
            type="undo",
            session_id=session_id,
            thread_id=target_event.thread_id if target_event else None,
            die=target_event.die_after if target_event else None,
            die_after=restored_die,
        )
    )


@router.post("/{session_id}/undo/{snapshot_id}")
async def undo_to_snapshot(
    session_id: int,
    snapshot_id: int,
    current_user: Annotated[User, Depends(get_current_user)],
    db: AsyncSession = Depends(get_db),
) -> SessionResponse:
    """Undo session state to a snapshot with deadlock retry handling.

    Args:
        session_id: Session to restore.
        snapshot_id: Snapshot to restore.
        current_user: Authenticated user.
        db: Database session.

    Returns:
        Restored session response.

    Raises:
        RuntimeError: If all deadlock retries fail.
    """
    max_retries = 3
    initial_delay = 0.1
    retries = 0

    while retries < max_retries:
        try:
            result = await db.execute(
                select(SessionModel)
                .where(
                    and_(
                        SessionModel.id == session_id,
                        SessionModel.user_id == current_user.id,
                    )
                )
                .with_for_update()
            )
            session = result.scalar_one_or_none()
            if not session:
                raise HTTPException(
                    status_code=status.HTTP_404_NOT_FOUND,
                    detail=f"Session {session_id} not found",
                )

            result = await db.execute(
                select(Snapshot)
                .where(Snapshot.session_id == session_id)
                .where(Snapshot.id == snapshot_id)
            )
            snapshot = result.scalars().first()
            if not snapshot:
                raise HTTPException(
                    status_code=status.HTTP_404_NOT_FOUND,
                    detail=f"Snapshot {snapshot_id} not found for session {session_id}",
                )

            is_delta = _is_delta_snapshot(snapshot)
            if is_delta:
                latest_delta = await _latest_delta_snapshot(db, session_id)
                if latest_delta is None or latest_delta.id != snapshot.id:
                    raise HTTPException(
                        status_code=status.HTTP_409_CONFLICT,
                        detail="Only the latest rating can be undone",
                    )
                await _restore_from_delta_snapshot(db, session, snapshot)
            else:
                await _restore_from_full_snapshot(db, session, snapshot, session_id)

            await _record_undo_event(db, snapshot, session_id)
            if is_delta:
                await db.delete(snapshot)
            await db.commit()
            await db.refresh(session)

            await asyncio.gather(
                _invalidate_session_caches(current_user.id),
                invalidate_cache(f"cache:list_threads:User:{current_user.id}:*"),
                invalidate_cache(f"cache:get_thread:*:User:{current_user.id}:"),
                invalidate_cache(f"cache:list_issues:*:User:{current_user.id}:*"),
                invalidate_cache(f"cache:get_issue:*:User:{current_user.id}:"),
                invalidate_cache(f"cache:get_blocked_thread_ids:{current_user.id}:"),
            )

            result = await db.execute(
                select(Event)
                .where(Event.session_id == session_id)
                .where(Event.type == "roll")
                .where(Event.selected_thread_id.is_not(None))
                .order_by(Event.timestamp.desc(), Event.id.desc())
            )
            active_thread = result.scalars().first()

            thread = None
            if active_thread and active_thread.selected_thread_id:
                thread = await db.get(Thread, active_thread.selected_thread_id)
                if thread is not None:
                    await db.refresh(thread)

            result = await db.execute(
                select(func.count())
                .select_from(Snapshot)
                .where(Snapshot.session_id == session_id)
            )
            snapshot_count = result.scalar() or 0

            return SessionResponse(
                id=session_id,
                started_at=session.started_at,
                ended_at=session.ended_at,
                start_die=session.start_die,
                manual_die=session.manual_die,
                user_id=session.user_id,
                ladder_path=await build_ladder_path(session_id, db),
                active_thread=ActiveThreadInfo(
                    id=thread.id,
                    title=thread.title,
                    format=thread.format,
                    issues_remaining=thread.issues_remaining,
                    queue_position=thread.queue_position,
                    last_rolled_result=active_thread.result if active_thread else None,
                )
                if thread
                else None,
                current_die=await get_current_die(session_id, db),
                last_rolled_result=active_thread.result if active_thread else None,
                has_restore_point=snapshot_count > 0,
                snapshot_count=snapshot_count,
            )
        except OperationalError as error:
            if "deadlock" not in str(error).lower():
                raise
            await db.rollback()
            retries += 1
            if retries >= max_retries:
                raise
            await asyncio.sleep(initial_delay * (2 ** (retries - 1)))

    raise RuntimeError(f"Failed to undo to snapshot after {max_retries} retries")


@router.get("/{session_id}/snapshots")
async def list_session_snapshots(
    session_id: int,
    current_user: Annotated[User, Depends(get_current_user)],
    db: AsyncSession = Depends(get_db),
) -> list[dict]:
    """List all snapshots for a session.

    Args:
        session_id: Session whose snapshots should be listed.
        current_user: Authenticated user.
        db: Database session.

    Returns:
        Snapshot metadata in reverse chronological order.

    Raises:
        HTTPException: If the session is not owned by the current user.
    """
    session = await db.get(SessionModel, session_id)
    if not session or session.user_id != current_user.id:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Session {session_id} not found",
        )

    result = await db.execute(
        select(Snapshot)
        .where(Snapshot.session_id == session_id)
        .order_by(Snapshot.created_at.desc(), Snapshot.id.desc())
    )
    snapshots = result.scalars().all()
    return [
        {
            "id": snapshot.id,
            "created_at": snapshot.created_at,
            "description": snapshot.description,
            "event_id": snapshot.event_id,
        }
        for snapshot in snapshots
    ]
