"""Unified continuity-derived blocked-state helpers.

DEPRECATED: After the Roll cutover (issue #2553), these functions are
no longer part of Roll authority. They are retained for diagnostic
services (reader_order_cutover.py) only.
"""

from sqlalchemy.ext.asyncio import AsyncSession

from app.services.continuity_graph import (
    crossover_order_blockers,
    issue_readiness,
    issue_rule_readiness,
    load_snapshot,
)


async def get_continuity_blocked_thread_ids(
    user_id: int,
    db: AsyncSession,
) -> set[int]:
    """DEPRECATED: No longer part of Roll authority after cutover.

    Return threads whose current unread issue is blocked by continuity rules.
    Retained for diagnostic services only.
    """
    snapshot = await load_snapshot(db, user_id)
    blocked_thread_ids: set[int] = set()
    for thread_id, thread in snapshot.threads.items():
        issue_id = thread.next_unread_issue_id
        if issue_id is not None and issue_readiness(issue_id, snapshot):
            blocked_thread_ids.add(thread_id)
    return blocked_thread_ids


async def get_continuity_rule_blocked_thread_ids(
    user_id: int,
    db: AsyncSession,
) -> set[int]:
    """DEPRECATED: No longer part of Roll authority after cutover.

    Return threads blocked only by compiled ContinuityRule rows.
    Retained for diagnostic services only.
    """
    snapshot = await load_snapshot(db, user_id)
    blocked_thread_ids: set[int] = set()
    for thread_id, thread in snapshot.threads.items():
        issue_id = thread.next_unread_issue_id
        if issue_id is not None and issue_rule_readiness(issue_id, snapshot):
            blocked_thread_ids.add(thread_id)
    return blocked_thread_ids


async def get_sequence_order_blocked_thread_ids(
    user_id: int,
    db: AsyncSession,
) -> set[int]:
    """DEPRECATED: No longer part of Roll authority after cutover.

    Return threads whose next unread is blocked by crossover sequence_order.
    Retained for diagnostic services only.
    """
    snapshot = await load_snapshot(db, user_id)
    blocked_thread_ids: set[int] = set()
    for thread_id, thread in snapshot.threads.items():
        issue_id = thread.next_unread_issue_id
        if issue_id is not None and crossover_order_blockers(issue_id, snapshot):
            blocked_thread_ids.add(thread_id)
    return blocked_thread_ids
