"""Shared session response and dice-ladder projection builders.

These builders were historically router privates (``app.api.session``,
``app.api.snooze``) shared across the roll/snooze/session routers. They are
shared domain logic that projects stored session/thread/event state into
user-facing responses, so they belong under ``app/services/`` rather than in
any single router. Routers and services import them without cross-router
imports.
"""

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import Event, Snapshot, Thread
from app.models import Session as SessionModel
from app.models.thread import normalize_format_value
from app.schemas import ActiveThreadInfo, SessionResponse
from app.schemas.session import (
    SnoozeCorrectionInfo,
    SnoozedThreadInfo,
    build_session_bandwidth_state,
    build_session_intent_state,
)
from comic_pile.session import get_current_die_for_session


async def build_ladder_path(
    session_id: int,
    db: AsyncSession,
    *,
    session: SessionModel | None = None,
    die_events: list[Event] | None = None,
) -> str:
    """Build narrative summary of dice ladder from session events.

    Args:
        session_id: The session ID to build ladder path for.
        db: Database session.
        session: Pre-loaded session object (avoids a redundant SELECT).
        die_events: Pre-fetched die-changing events (avoids a redundant SELECT).

    Returns:
        String representation of dice ladder path (e.g., "d4 → d6 → d8").
    """
    if session is None:
        session = await db.get(SessionModel, session_id)
        if not session:
            return ""

    if die_events is None:
        events_result = await db.execute(
            select(Event)
            .where(Event.session_id == session_id)
            .where(Event.type.in_(("rate", "snooze", "undo")))
            .where(Event.die_after.is_not(None))
            .order_by(Event.timestamp, Event.id)
        )
        die_events = events_result.scalars().all()

    if not die_events:
        return str(session.start_die)

    path = [session.start_die]
    for event in die_events:
        if event.die_after:
            path.append(event.die_after)

    return " → ".join(str(d) for d in path)


async def build_session_response(
    session: SessionModel,
    db: AsyncSession,
    *,
    current_die: int | None = None,
    active_thread_id: int | None = None,
    active_thread_info: ActiveThreadInfo | None = None,
    ladder_path: str | None = None,
    snapshot_count: int | None = None,
    snoozed_threads: list[SnoozedThreadInfo] | None = None,
    snoozed_thread_ids: list[int] | None = None,
    skipped_threads: list[SnoozedThreadInfo] | None = None,
    skipped_thread_ids: list[int] | None = None,
    correction: SnoozeCorrectionInfo | None = None,
) -> SessionResponse:
    """Build a SessionResponse from a session model.

    When pre-loaded values are provided, avoids redundant database queries.
    Callers that already computed die, active thread, or ladder path should
    pass them in to reduce round trips.

    Args:
        session: The session model.
        db: Database session.
        current_die: Pre-computed current die value (skips get_current_die query).
        active_thread_id: Pre-fetched active thread ID (skips event lookup).
        active_thread_info: Pre-fetched active thread info (skips thread lookup).
        ladder_path: Pre-computed ladder path string (skips event re-read).
        snapshot_count: Pre-computed snapshot count (skips COUNT query).
        snoozed_threads: Pre-fetched snoozed thread info (skips snoozed thread query).
        snoozed_thread_ids: Pre-fetched snoozed thread IDs (avoids expired session read).
        skipped_threads: Pre-fetched skipped thread info (skips skipped thread query).
        skipped_thread_ids: Pre-fetched skipped thread IDs (avoids expired session read).
        correction: Structured correction result from the most recent Snooze.

    Returns:
        A SessionResponse with all required fields populated.
    """
    if active_thread_id is not None and active_thread_info is None:
        thread = await db.get(Thread, active_thread_id)
        if thread:
            active_thread_info = ActiveThreadInfo(
                id=thread.id,
                title=thread.title,
                format=normalize_format_value(thread.format),
                issues_remaining=thread.issues_remaining,
                queue_position=thread.queue_position,
                last_rolled_result=None,
            )

    if snapshot_count is None:
        result = await db.execute(
            select(func.count()).select_from(Snapshot).where(Snapshot.session_id == session.id)
        )
        snapshot_count = result.scalar() or 0

    if snoozed_threads is not None and snoozed_thread_ids is not None:
        resolved_ids = snoozed_thread_ids
    else:
        snoozed_ids = session.snoozed_thread_ids or []
        resolved_ids = [sid for sid in snoozed_ids if isinstance(sid, int)]
        snoozed_threads = []
        if resolved_ids:
            result = await db.execute(select(Thread).where(Thread.id.in_(resolved_ids)))
            threads_by_id = {thread.id: thread for thread in result.scalars().all()}
            snoozed_threads = [
                SnoozedThreadInfo(id=thread_id, title=threads_by_id[thread_id].title)
                for thread_id in resolved_ids
                if thread_id in threads_by_id
            ]

    if skipped_threads is not None and skipped_thread_ids is not None:
        resolved_skipped_ids = skipped_thread_ids
        resolved_skipped_threads = skipped_threads
    else:
        skipped_ids_list = session.skipped_thread_ids or []
        resolved_skipped_ids = [sid for sid in skipped_ids_list if isinstance(sid, int)]
        resolved_skipped_threads = []
        if resolved_skipped_ids:
            result = await db.execute(select(Thread).where(Thread.id.in_(resolved_skipped_ids)))
            threads_by_id = {thread.id: thread for thread in result.scalars().all()}
            resolved_skipped_threads = [
                SnoozedThreadInfo(id=thread_id, title=threads_by_id[thread_id].title)
                for thread_id in resolved_skipped_ids
                if thread_id in threads_by_id
            ]

    if current_die is None:
        current_die = await get_current_die_for_session(session, db)
    if ladder_path is None:
        ladder_path = await build_ladder_path(session.id, db)

    return SessionResponse(
        id=session.id,
        started_at=session.started_at,
        ended_at=session.ended_at,
        start_die=session.start_die,
        manual_die=session.manual_die,
        user_id=session.user_id,
        ladder_path=ladder_path,
        active_thread=active_thread_info,
        current_die=current_die,
        last_rolled_result=active_thread_info.last_rolled_result if active_thread_info else None,
        has_restore_point=snapshot_count > 0,
        snapshot_count=snapshot_count,
        snoozed_thread_ids=resolved_ids,
        snoozed_threads=snoozed_threads,
        skipped_thread_ids=resolved_skipped_ids,
        skipped_threads=resolved_skipped_threads,
        pending_thread_id=session.pending_thread_id,
        timezone=session.timezone,
        reading_bandwidth=session.reading_bandwidth,
        reading_intent=session.reading_intent,
        reading_mode_source=session.reading_mode_source,
        reading_mode_suggested=session.reading_mode_suggested,
        bandwidth=build_session_bandwidth_state(
            predicted_bandwidth=session.predicted_bandwidth,
            active_bandwidth=session.active_bandwidth,
            confidence=session.bandwidth_confidence,
            source=session.bandwidth_source,
            mode_version=session.bandwidth_version,
        ),
        intent=build_session_intent_state(
            predicted_intent=session.predicted_intent,
            active_intent=session.active_intent,
            confidence=session.intent_confidence,
            source=session.intent_source,
            mode_version=session.intent_version,
        ),
        correction=correction,
    )
