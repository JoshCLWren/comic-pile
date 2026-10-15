"""Tag-based roll exclusion helpers.

Persistent account-wide tag exclusions are stored on ``UserPreferences``. This
module resolves which threads must leave the roll pool because their next
unread issue's effective tags contain an excluded tag, without touching
snooze, backoff, ratings, or recommendation weighting.
"""

from __future__ import annotations

from sqlalchemy.ext.asyncio import AsyncSession

from app.models.user import User
from app.repositories import thread_repository
from app.repositories.preferences_repository import get_excluded_tag_ids
from app.services.tag_inheritance_service import TagInheritanceService


async def get_user_excluded_tag_ids(db: AsyncSession, user_id: int) -> list[int]:
    """Return a user's persisted excluded tag IDs.

    Args:
        db: Database session.
        user_id: Owning user.

    Returns:
        Excluded tag IDs, or an empty list when none are persisted.
    """
    return await get_excluded_tag_ids(db, user_id)


async def derive_tag_excluded_thread_ids(
    db: AsyncSession,
    user: User,
    excluded_tag_ids: list[int] | None = None,
) -> set[int]:
    """Resolve threads whose next unread issue carries an excluded tag.

    Args:
        db: Database session.
        user: Owning user.
        excluded_tag_ids: Optional exclusion override; loaded from
            preferences when omitted.

    Returns:
        Set of thread IDs that must stay out of the roll pool.
    """
    if excluded_tag_ids is None:
        excluded_tag_ids = await get_excluded_tag_ids(db, user.id)
    if not excluded_tag_ids:
        return set()

    excluded = {int(tag_id) for tag_id in excluded_tag_ids}
    threads = await thread_repository.fetch_active_threads(db, user.id)
    candidates = [
        thread
        for thread in threads
        if thread.queue_position >= 1
        and not thread.is_blocked
        and thread.next_unread_issue_id is not None
    ]
    if not candidates:
        return set()

    tag_ids_by_issue = await TagInheritanceService(db).issue_effective_tag_ids(
        user, [thread.next_unread_issue_id for thread in candidates]
    )
    result: set[int] = set()
    for thread in candidates:
        issue_tag_ids = tag_ids_by_issue.get(thread.next_unread_issue_id, set())
        if issue_tag_ids & excluded:
            result.add(thread.id)
    return result
