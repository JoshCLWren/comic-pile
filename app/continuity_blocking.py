"""Legacy continuity-derived blocked-state helpers.

These functions are retained for backward compatibility and migration scenarios.
The canonical runtime authority for Roll eligibility is now in
`comic_pile/dependencies.py`, which uses Thread frontiers plus canonical
Dependencies only.
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
    """Return threads blocked by legacy continuity rules (deprecated).

    This function evaluates ContinuityRule rows plus crossover ordering, which
    are no longer runtime authorities after the canonical dependency cutover.
    Use `comic_pile.dependencies._get_blocked_thread_ids_uncached` for the
    canonical runtime behavior.

    Retained for backward compatibility and migration scenarios.
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
    """Return threads blocked by ContinuityRule rows only (deprecated).

    This function evaluates only ContinuityRule rows, excluding crossover ordering.
    However, ContinuityRules are no longer runtime authorities after the canonical
    dependency cutover. Use `comic_pile.dependencies._get_blocked_thread_ids_uncached`
    for the canonical runtime behavior.

    Retained for backward compatibility and migration scenarios.
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
    """Return threads whose frontier issue is blocked by crossover ordering.

    ``DependencyGroupMembership.sequence_order`` is not a Roll authority after the
    canonical dependency cutover. This helper exists only so
    :mod:`app.services.reader_order_cutover` can *measure* how many threads that
    retired ordering would have blocked, and fail the release gate when the
    measurement is non-empty. It must never feed eligibility or explanations.
    """
    snapshot = await load_snapshot(db, user_id)
    blocked_thread_ids: set[int] = set()
    for thread_id, thread in snapshot.threads.items():
        issue_id = thread.next_unread_issue_id
        if issue_id is not None and crossover_order_blockers(issue_id, snapshot):
            blocked_thread_ids.add(thread_id)
    return blocked_thread_ids

