"""Tag-based roll exclusion helpers.

Persistent account-wide tag exclusions are stored on ``UserPreferences``. This
module resolves which threads must leave the roll pool because their next
unread issue's effective tags contain an excluded tag, without touching
snooze, backoff, ratings, or recommendation weighting.
"""

from __future__ import annotations

from sqlalchemy.ext.asyncio import AsyncSession

from app.models.user import User
from app.repositories import tag_repository, thread_repository
from app.repositories.preferences_repository import get_excluded_tag_ids
from app.schemas.roll import RollTagExclusionTag
from app.services.tag_inheritance_service import TagInheritanceService

TAG_EXCLUSION_EMPTY_POOL_DETAIL = "No candidates satisfy the current tag exclusions"


async def get_user_excluded_tag_ids(db: AsyncSession, user_id: int) -> list[int]:
    """Return a user's persisted excluded tag IDs.

    Args:
        db: Database session.
        user_id: Owning user.

    Returns:
        Excluded tag IDs, or an empty list when none are persisted.
    """
    return await get_excluded_tag_ids(db, user_id)


async def list_excluded_tag_summaries(
    db: AsyncSession, user_id: int, excluded_tag_ids: list[int]
) -> list[RollTagExclusionTag]:
    """Resolve exclusion IDs into reader-facing tag summaries.

    Deleted tags stay in the exclusion list (so restoring them later never
    silently changes eligibility) but resolve to no summary here.

    Args:
        db: Database session.
        user_id: Owning user, applied as the visibility boundary.
        excluded_tag_ids: The persisted exclusion IDs to resolve.

    Returns:
        One summary per excluded tag that still exists and is visible to
        ``user_id``, ordered by tag ID.
    """
    if not excluded_tag_ids:
        return []
    tags = await tag_repository.get_visible_tags_by_ids(db, user_id, excluded_tag_ids)
    return [
        RollTagExclusionTag(id=tag.id, name=tag.name, color=tag.color, scope=tag.scope)
        for tag in tags
    ]


async def derive_tag_excluded_thread_ids(
    db: AsyncSession,
    user_id: int,
    *,
    excluded_tag_ids: list[int] | None = None,
) -> set[int]:
    """Resolve threads whose next unread issue carries an excluded tag.

    Args:
        db: Database session.
        user_id: Owning user.
        excluded_tag_ids: Optional exclusion override; loaded from
            preferences when omitted.

    Returns:
        Set of thread IDs that must stay out of the roll pool.
    """
    if excluded_tag_ids is None:
        excluded_tag_ids = await get_excluded_tag_ids(db, user_id)
    if not excluded_tag_ids:
        return set()

    user = await db.get(User, user_id)
    if user is None:
        return set()

    excluded = {int(tag_id) for tag_id in excluded_tag_ids}
    threads = await thread_repository.fetch_active_threads(db, user_id)
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


async def explain_empty_pool_detail(
    db: AsyncSession,
    *,
    user_id: int,
    current_die: int,
    excluded_ids: list[int],
    default_detail: str,
) -> str:
    """Explain an empty roll pool, attributing it to tag exclusions when true.

    Issue #3033 requires the empty-pool state to say that no candidate
    satisfies the active tag exclusions instead of implying the library is
    empty. The attribution only applies when the pool still has candidates
    once the tag-derived exclusions are dropped, so an actually empty library
    keeps its original wording.

    Args:
        db: Database session.
        user_id: Owner of the candidate pool.
        current_die: Die size that bounds the pool.
        excluded_ids: The full exclusion set that produced the empty pool.
        default_detail: Wording to keep when exclusions are not the cause.

    Returns:
        The reader-facing reason the pool is empty.
    """
    excluded_tag_ids = await get_excluded_tag_ids(db, user_id)
    if not excluded_tag_ids:
        return default_detail

    tag_excluded_ids = await derive_tag_excluded_thread_ids(
        db, user_id, excluded_tag_ids=excluded_tag_ids
    )
    if not tag_excluded_ids:
        return default_detail

    untagged_excluded_ids = [
        thread_id for thread_id in excluded_ids if thread_id not in tag_excluded_ids
    ]
    if untagged_excluded_ids == list(excluded_ids):
        return default_detail

    from comic_pile.queue import get_bounded_roll_pool_rows

    remaining_rows = await get_bounded_roll_pool_rows(
        user_id, db, current_die, untagged_excluded_ids
    )
    if not remaining_rows:
        return default_detail
    return TAG_EXCLUSION_EMPTY_POOL_DETAIL
