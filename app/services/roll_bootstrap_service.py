"""v1 Roll bootstrap assembly (issue #3375).

Builds the frozen ``RollBootstrapResponse`` for ``GET /api/v1/roll/bootstrap``
from two bounded repository round trips instead of the previous eleven
sequential ones, while preserving every v1 predicate and response field.

The predicates that previously ran in SQL - active status, queue position, the
blocked flag, snoozed/skipped membership, and the seven-day stale cutoff - are
pure functions of the owned-thread inventory columns, so this service evaluates
them in Python over one ordered fetch. That keeps the semantics byte-for-byte
identical while removing the round trips that caused the production budget
violation (1962ms against a 1000ms budget, 36 queries).

The response contract is frozen and consumed by the frontend Roll page, so
field names, list bounding, and the ``summary_limit`` caps are unchanged.
"""

from __future__ import annotations

import logging
import random
from datetime import UTC, datetime, timedelta
from zoneinfo import ZoneInfo

from sqlalchemy.ext.asyncio import AsyncSession

from app.models.thread import normalize_format_value
from app.models.user import User
from app.repositories import roll_bootstrap_repository as bootstrap_repo
from app.repositories.roll_bootstrap_repository import BootstrapThreadRow
from app.roll_recovery import build_roll_recovery
from app.schemas import RollBootstrapResponse, SessionMode, ThreadExclusionReason
from app.schemas.roll import RollBootstrapThread
from app.schemas.session import build_session_bandwidth_state
from app.services.session_response import get_session_with_thread_safe
from app.services.snooze_service import derive_cross_session_excluded_thread_ids
from comic_pile.dependencies import get_blocking_explanations_batch
from comic_pile.reading_session import get_current_die_for_session, get_or_create

logger = logging.getLogger(__name__)

#: A thread with no activity newer than this is eligible for the stale nudge.
STALE_ACTIVITY_WINDOW = timedelta(days=7)


def _summarize_threads(
    thread_ids: list[int],
    threads_by_id: dict[int, BootstrapThreadRow],
) -> list[RollBootstrapThread]:
    """Materialize id-addressed summary threads from the owned-thread inventory.

    Snoozed and skipped summaries address stored session ids directly and never
    filtered on status, so a resolved thread is included whatever its status.
    Ids that no longer resolve to an owned thread are dropped, matching the
    previous ``id.in_(...)`` lookups.

    Args:
        thread_ids: Stored session ids, in the session's own order.
        threads_by_id: Owned threads keyed by id from the inventory fetch.

    Returns:
        Summary threads in ``thread_ids`` order.
    """
    summaries: list[RollBootstrapThread] = []
    for thread_id in thread_ids:
        row = threads_by_id.get(thread_id)
        if row is None:
            continue
        summaries.append(
            RollBootstrapThread(
                id=row["id"],
                title=row["title"],
                format=normalize_format_value(row["format"]),
            )
        )
    return summaries


async def build_roll_bootstrap_response(
    db: AsyncSession,
    *,
    current_user: User,
    timezone: str | None,
) -> RollBootstrapResponse:
    """Assemble the bounded v1 Roll bootstrap payload for the initial render.

    Replaces the need for separate session, full-thread-library, and
    stale-thread requests by returning only the retained data required for the
    first interactive screen.

    Args:
        db: Async database session.
        current_user: The authenticated user.
        timezone: Optional browser-resolved IANA timezone identifier captured once
            per active reading session. Invalid or unusable values leave the field
            unset and never break the roll.

    Returns:
        RollBootstrapResponse with session state, bounded pool, snoozed/blocked/stale summaries.
    """
    user_id = current_user.id
    current_session = await get_or_create(db, user_id=user_id, existing_user=current_user)
    await db.refresh(current_session)

    if timezone is not None and current_session.timezone is None:
        try:
            candidate_timezone = timezone.strip()
            if candidate_timezone and len(candidate_timezone) <= 100:
                ZoneInfo(candidate_timezone)
                current_session.timezone = candidate_timezone
                await db.commit()
                await db.refresh(current_session)
        except Exception:
            logger.exception("Failed to update session timezone from browser value %s", timezone)

    current_session_id = current_session.id

    bandwidth_state = build_session_bandwidth_state(
        predicted_bandwidth=current_session.predicted_bandwidth,
        active_bandwidth=current_session.active_bandwidth,
        confidence=current_session.bandwidth_confidence,
        source=current_session.bandwidth_source,
        mode_version=current_session.bandwidth_version,
    )

    _, active_thread = await get_session_with_thread_safe(current_session_id, db)

    die_size = await get_current_die_for_session(current_session, db)
    manual_die = current_session.manual_die
    pending_thread_id = current_session.pending_thread_id
    session_mode = SessionMode(
        active_bandwidth=current_session.active_bandwidth,
        predicted_bandwidth=current_session.predicted_bandwidth,
        bandwidth_confidence=current_session.bandwidth_confidence,
        bandwidth_source=current_session.bandwidth_source,
        bandwidth_version=current_session.bandwidth_version,
        active_intent=current_session.active_intent,
        predicted_intent=current_session.predicted_intent,
        intent_confidence=current_session.intent_confidence,
        intent_source=current_session.intent_source,
        intent_version=current_session.intent_version,
        session_mode_correction_guidance=current_session.session_mode_correction_guidance,
    )
    last_rolled_result = active_thread.last_rolled_result if active_thread else None
    pending_thread_title = (
        active_thread.title
        if active_thread is not None and active_thread.id == pending_thread_id
        else None
    )
    roll_recovery = await build_roll_recovery(
        db,
        user_id=user_id,
        pending_thread_id=pending_thread_id,
        pending_thread_title=pending_thread_title,
    )

    snoozed_ids = list(current_session.snoozed_thread_ids or [])
    skipped_ids = list(current_session.skipped_thread_ids or [])
    derived_snoozed_ids = await derive_cross_session_excluded_thread_ids(db, user_id)
    snoozed_id_set = set(snoozed_ids)
    skipped_id_set = set(skipped_ids)
    effective_snoozed_id_set = frozenset(snoozed_id_set | set(derived_snoozed_ids))

    # One inventory fetch replaces the previous all-active, completed, snoozed,
    # skipped, blocked-count, blocked-detail, stale-count, stale-id, and
    # stale-detail queries. Every predicate below is unchanged; only its
    # evaluation moved from SQL into Python over these rows.
    inventory = await bootstrap_repo.fetch_owned_thread_inventory(db, user_id=user_id)
    threads_by_id: dict[int, BootstrapThreadRow] = {row["id"]: row for row in inventory}
    active_rows = [row for row in inventory if row["status"] == "active"]
    completed_rows = [row for row in inventory if row["status"] == "completed"]

    # Mirrors the previous pool query's WHERE clause exactly: active (already
    # filtered above), queued, unblocked, and not snoozed or skipped in any
    # scope. The die cap is applied after the exclusions, as before.
    rollable_rows = [
        row
        for row in active_rows
        if row["queue_position"] is not None
        and row["queue_position"] >= 1
        and not row["is_blocked"]
        and row["id"] not in effective_snoozed_id_set
        and row["id"] not in skipped_id_set
    ][:die_size]
    pool_details = {
        row["thread_id"]: row
        for row in await bootstrap_repo.fetch_roll_pool_rows(
            db,
            user_id=user_id,
            thread_ids=[item["id"] for item in rollable_rows],
        )
    }
    roll_pool: list[RollBootstrapThread] = []
    for row in rollable_rows:
        detail = pool_details.get(row["id"])
        roll_pool.append(
            RollBootstrapThread(
                id=row["id"],
                title=row["title"],
                format=normalize_format_value(row["format"]),
                issue_id=detail["issue_id"] if detail is not None else None,
                issue_number=detail["issue_number"] if detail is not None else None,
                route_labels=list(detail["route_labels"]) if detail is not None else [],
            )
        )

    snoozed_threads = _summarize_threads(snoozed_ids, threads_by_id)
    skipped_threads = _summarize_threads(skipped_ids, threads_by_id)

    blocked_rows = [row for row in active_rows if row["is_blocked"]]
    blocked_count = len(blocked_rows)
    blocked_threads = [
        RollBootstrapThread(
            id=row["id"],
            title=row["title"],
            format=normalize_format_value(row["format"]),
        )
        for row in blocked_rows
    ]
    snoozed_count = len(snoozed_threads)
    snoozed_threads = snoozed_threads[: RollBootstrapResponse.summary_limit]
    blocked_threads = blocked_threads[: RollBootstrapResponse.summary_limit]
    skipped_threads = skipped_threads[: RollBootstrapResponse.summary_limit]

    # The stale nudge covers active, unblocked series that are snoozed nowhere
    # in any scope and have been quiet for longer than the stale window. Skipped
    # series stay eligible here, exactly as before.
    stale_cutoff = datetime.now(UTC) - STALE_ACTIVITY_WINDOW
    stale_ids = [
        row["id"]
        for row in active_rows
        if not row["is_blocked"]
        and row["id"] not in effective_snoozed_id_set
        and (
            (
                row["last_activity_at"]
                if row["last_activity_at"] is not None
                else row["created_at"]
            )
            is not None
        )
        and (
            (
                row["last_activity_at"]
                if row["last_activity_at"] is not None
                else row["created_at"]
            )
            < stale_cutoff
        )
    ]
    stale_thread_count = len(stale_ids)

    stale_thread: RollBootstrapThread | None = None
    if stale_ids:
        chosen = threads_by_id[random.choice(stale_ids)]
        chosen_last_activity = chosen["last_activity_at"]
        stale_thread = RollBootstrapThread(
            id=chosen["id"],
            title=chosen["title"],
            format=normalize_format_value(chosen["format"]),
            last_activity_at=(
                chosen_last_activity.isoformat() if chosen_last_activity else None
            ),
        )

    # Exclusion transparency for issue #3125: enumerate every series
    # not in the roll pool and explain why, so the user can see what
    # vanished and why. The pool is capped at the die size and only drives
    # the face mapping, so availability is decided by the rollable predicates
    # themselves: a rollable series beyond the die window is still available
    # and must never be reported as excluded.
    available_ids: set[int] = set()
    excluded: dict[int, ThreadExclusionReason] = {}
    inactive: list[ThreadExclusionReason] = []
    blocked_ids: list[int] = []

    for row in active_rows:
        tid = row["id"]
        title = row["title"]
        fmt = normalize_format_value(row["format"])
        is_blocked = row["is_blocked"]
        is_rollable = (
            row["queue_position"] is not None
            and row["queue_position"] >= 1
            and not is_blocked
            and tid not in effective_snoozed_id_set
            and tid not in skipped_id_set
        )
        if is_rollable:
            available_ids.add(tid)
            continue
        if is_blocked:
            blocked_ids.append(tid)
            exc = ThreadExclusionReason(
                thread_id=tid, title=title, format=fmt, reason="blocked",
            )
        elif tid in snoozed_id_set:
            exc = ThreadExclusionReason(
                thread_id=tid,
                title=title,
                format=fmt,
                reason="snoozed",
                detail="Snoozed in current session",
            )
        elif tid in derived_snoozed_ids:
            exc = ThreadExclusionReason(
                thread_id=tid,
                title=title,
                format=fmt,
                reason="snoozed",
                detail="Snoozed by cross-session backoff",
            )
        elif tid in skipped_id_set:
            exc = ThreadExclusionReason(
                thread_id=tid,
                title=title,
                format=fmt,
                reason="skipped",
                detail="Skipped in current session",
            )
        else:
            exc = ThreadExclusionReason(
                thread_id=tid,
                title=title,
                format=fmt,
                reason="not_in_queue",
                detail="Not in the active queue",
            )
            inactive.append(exc)
        excluded[tid] = exc

    # Completed series sit outside the active status and never reach the
    # pool query, so they vanish silently unless explained here.
    for row in completed_rows:
        tid = row["id"]
        exc = ThreadExclusionReason(
            thread_id=tid,
            title=row["title"],
            format=normalize_format_value(row["format"]),
            reason="completed",
            detail="Read the full series",
        )
        excluded[tid] = exc
        inactive.append(exc)

    # Attach human-readable blocking detail where it exists, then
    # materialize the bounded exclusion lists for the response. Every
    # active row is either available or excluded and every completed
    # row is excluded, so total - available always equals the union of
    # all exclusion reasons.
    if blocked_ids:
        blocking_map = await get_blocking_explanations_batch(
            sorted(blocked_ids), user_id, db
        )
        for tid, explanations in blocking_map.items():
            if tid in excluded and explanations:
                excluded[tid].detail = explanations[0].label

    total_threads = len(active_rows) + len(completed_rows)
    available_threads = len(available_ids)
    excluded_list = list(excluded.values())
    excluded_count = len(excluded_list)
    inactive_count = len(inactive)

    return RollBootstrapResponse(
        current_die=die_size,
        manual_die=manual_die,
        pending_thread_id=pending_thread_id,
        last_rolled_result=last_rolled_result,
        session_mode=session_mode,
        active_thread=active_thread,
        roll_recovery=roll_recovery,
        bandwidth=bandwidth_state,
        roll_pool=roll_pool,
        snoozed_threads=snoozed_threads,
        snoozed_count=snoozed_count,
        skipped_thread_ids=skipped_ids,
        skipped_threads=skipped_threads,
        blocked_count=blocked_count,
        blocked_threads=blocked_threads,
        stale_thread_count=stale_thread_count,
        stale_thread=stale_thread,
        session_id=current_session_id,
        user_id=user_id,
        timezone=current_session.timezone,

        # Issue #3125: exclusion transparency.
        total_threads=total_threads,
        available_threads=available_threads,
        excluded_count=excluded_count,
        excluded_threads=excluded_list,
        inactive_count=inactive_count,
        inactive_threads=inactive,
    )
