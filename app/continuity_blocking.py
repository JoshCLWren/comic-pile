"""Unified continuity-derived blocked-state helpers."""

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
    """Return threads whose current unread issue is blocked by continuity rules.

    The readiness graph is loaded once, then every owned thread is evaluated against
    the same snapshot. This keeps Queue/Roll blocked-state refreshes bounded instead
    of issuing one readiness query set per thread.
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
    """Return threads blocked only by compiled ContinuityRule rows.

    Unlike :func:`get_continuity_blocked_thread_ids`, this deliberately ignores
    ``DependencyGroupMembership.sequence_order`` crossover ordering so cutover
    audits cannot treat forbidden sequence-order authority as canonical coverage.
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
    """Return threads whose next unread is blocked by crossover sequence_order."""
    snapshot = await load_snapshot(db, user_id)
    blocked_thread_ids: set[int] = set()
    for thread_id, thread in snapshot.threads.items():
        issue_id = thread.next_unread_issue_id
        if issue_id is not None and crossover_order_blockers(issue_id, snapshot):
            blocked_thread_ids.add(thread_id)
    return blocked_thread_ids
