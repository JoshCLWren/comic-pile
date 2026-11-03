"""Roll eligibility exclusion helpers.

This module computes the thread exclusion sets shared by every roll path.
It replaces the legacy ``snooze_service.py`` which also contained the v1
snooze/unsnooze API handlers (now removed).

Services own business rules and transaction boundaries (commit/rollback).
Query construction lives in ``app.repositories``. HTTP status mapping lives
in routers.
"""

import logging
from bisect import bisect_right
from collections.abc import Collection
from datetime import datetime

from sqlalchemy.ext.asyncio import AsyncSession

from app.services.reading_eligibility_service import get_execution_eligibility
from app.repositories.snooze_repository import (
    fetch_snooze_backoff_rows,
    fetch_user_session_started_ats,
)
from app.repositories.thread_repository import threads_by_ids, fetch_excluded_thread_ids
from app.schemas.session import SnoozedThreadInfo
from comic_pile.snooze_backoff import is_eligible

logger = logging.getLogger(__name__)


def _after_reset(
    last_activity_at: datetime | None,
    event_type: str | None,
    event_timestamp: datetime | None,
) -> bool:
    """Return whether an event counts toward the current snooze streak.

    Args:
        last_activity_at: The thread's read/reset boundary, or ``None`` when
            the thread was never successfully read.
        event_type: The event's type.
        event_timestamp: The event's timestamp.

    Returns:
        True when the event occurred after the reset boundary.
    """
    return (
        event_type is not None
        and event_timestamp is not None
        and (last_activity_at is None or event_timestamp > last_activity_at)
    )


async def derive_cross_session_excluded_thread_ids(
    db: AsyncSession, user_id: int
) -> set[int]:
    """Derive threads excluded by durable cross-session snooze backoff.

    ``Session.snoozed_thread_ids`` only covers the current session. Beyond it,
    a thread stays out of the roll pool and stale list until enough later
    reading sessions have started (issue #2740). The streak is derived from
    stored ``snooze``/``unsnooze`` events and the user's session history in
    two batched queries, never one historical query per candidate thread.

    The reset boundary is ``Thread.last_activity_at``: snooze events on or
    before a successful read do not count toward the streak (or all snoozes
    count when the thread was never read). A manual ``unsnooze`` newer than
    the latest snooze makes the thread immediately eligible without resetting
    the streak.

    Args:
        db: Database session.
        user_id: Owner of the threads.

    Returns:
        Set of thread IDs that must stay excluded until their backoff elapses.
    """
    eligibility = await get_execution_eligibility(db, user_id)
    eligibility_args = {"eligibility": eligibility} if eligibility is not None else {}
    rows = await fetch_snooze_backoff_rows(db, user_id, **eligibility_args)
    excluded: set[int] = set()
    if not rows:
        return excluded

    session_starts = await fetch_user_session_started_ats(db, user_id)
    if not session_starts:
        return excluded

    grouped: dict[int, list[tuple[datetime | None, str | None, datetime | None, int]]] = {}
    for thread_id, last_activity_at, event_type, event_timestamp, event_id in rows:
        grouped.setdefault(thread_id, []).append(
            (last_activity_at, event_type, event_timestamp, event_id)
        )

    for thread_id, thread_rows in grouped.items():
        last_activity_at = thread_rows[0][0]

        snoozes = [
            event_timestamp
            for _activity, event_type, event_timestamp, _event_id in thread_rows
            if event_type == "snooze"
            and _after_reset(last_activity_at, event_type, event_timestamp)
        ]
        if not snoozes:
            continue

        unsnoozes = [
            event_timestamp
            for _activity, event_type, event_timestamp, _event_id in thread_rows
            if event_type == "unsnooze"
            and _after_reset(last_activity_at, event_type, event_timestamp)
        ]

        latest_snooze = max(snoozes)
        if unsnoozes and max(unsnoozes) > latest_snooze:
            continue

        later_session_count = len(session_starts) - bisect_right(
            session_starts, latest_snooze
        )
        if not is_eligible(len(snoozes), later_session_count):
            excluded.add(thread_id)

    return excluded


async def derive_effective_roll_excluded_thread_ids(
    db: AsyncSession,
    user_id: int,
    *,
    session_snoozed_ids: Collection[int] | None = None,
    session_skipped_ids: Collection[int] | None = None,
) -> list[int]:
    """Return the complete thread exclusion set shared by every roll path.

    Roll eligibility is one policy with three inputs: the current session's
    snoozed threads, the current session's skipped threads, and durable
    cross-session snooze backoff. Issue #3696 was a production repeat-roll
    defect caused by rating-time safe placement counting only part of that set,
    so the rating path and every live roll-selection path build it here instead
    of repeating the union at each call site.

    Callers that report exclusion transparency still need the raw backoff set
    from :func:`derive_cross_session_excluded_thread_ids` to explain *why* a
    thread is hidden; this helper is for eligibility decisions only.

    Args:
        db: Database session.
        user_id: Owner of the threads.
        session_snoozed_ids: Current session's snoozed thread IDs.
        session_skipped_ids: Current session's skipped thread IDs.

    Returns:
        Deduplicated thread IDs that must stay out of roll eligibility.
    """
    derived_excluded_ids = await derive_cross_session_excluded_thread_ids(db, user_id)
    excluded_ids: list[int] = []
    seen: set[int] = set()
    for thread_id in (
        *(session_snoozed_ids or ()),
        *(session_skipped_ids or ()),
        *sorted(derived_excluded_ids),
    ):
        if thread_id in seen:
            continue
        seen.add(thread_id)
        excluded_ids.append(thread_id)

    # A durable "Remove from Queue" exclusion (#3807) is reader-owned, not
    # session-owned: it keeps the series out of the roll pool across sessions
    # until it is explicitly restored. The rows still exist, so nothing about
    # reading history, ratings, or mappings is lost by excluding the id here.
    excluded_status_ids = await fetch_excluded_thread_ids(db, user_id)
    for tid in excluded_status_ids:
        if tid not in seen:
            seen.add(tid)
            excluded_ids.append(tid)

    return excluded_ids


async def _snoozed_thread_info(db: AsyncSession, thread_ids: list[int]) -> list[SnoozedThreadInfo]:
    """Resolve snoozed thread IDs to display titles in one bulk read.

    Args:
        db: Database session.
        thread_ids: Snoozed thread IDs to resolve.

    Returns:
        Ordered ``SnoozedThreadInfo`` rows for the existing threads.
    """
    if not thread_ids:
        return []

    threads_by_id = await threads_by_ids(db, set(thread_ids))
    return [
        SnoozedThreadInfo(id=thread_id, title=threads_by_id[thread_id].title)
        for thread_id in thread_ids
        if thread_id in threads_by_id
    ]