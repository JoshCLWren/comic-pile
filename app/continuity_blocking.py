"""Unified continuity-derived blocked-state helpers."""

from sqlalchemy.ext.asyncio import AsyncSession

from app.continuity_readiness import _issue_readiness, _load_snapshot


async def get_continuity_blocked_thread_ids(
    user_id: int,
    db: AsyncSession,
) -> set[int]:
    """Return threads whose current unread issue is blocked by continuity rules.

    The readiness graph is loaded once, then every owned thread is evaluated against
    the same snapshot. This keeps Queue/Roll blocked-state refreshes bounded instead
    of issuing one readiness query set per thread.
    """
    snapshot = await _load_snapshot(db, user_id)
    blocked_thread_ids: set[int] = set()
    for thread_id, thread in snapshot.threads.items():
        issue_id = thread.next_unread_issue_id
        if issue_id is not None and _issue_readiness(issue_id, snapshot):
            blocked_thread_ids.add(thread_id)
    return blocked_thread_ids
