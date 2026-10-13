"""Roll tag-exclusion query construction and persistence.

All SQLAlchemy access for the ``RollTagExclusion`` model lives here, plus the
bulk effective-tag lookup the roll pool uses to enforce exclusions without
N+1 tag queries. Functions return ORM models or plain values; callers
(services) own transactions and authorization.
"""

from __future__ import annotations

from sqlalchemy import delete, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import RollTagExclusion, Tag
from app.repositories import reading_plan_repository, tag_repository


async def list_excluded_tag_ids(db: AsyncSession, user_id: int) -> list[int]:
    """Return the tag IDs one user excluded from Roll eligibility.

    Args:
        db: Database session.
        user_id: Owner of the exclusions.

    Returns:
        Excluded tag IDs in ascending tag order.
    """
    result = await db.execute(
        select(RollTagExclusion.tag_id)
        .where(RollTagExclusion.user_id == user_id)
        .order_by(RollTagExclusion.tag_id)
    )
    return list(result.scalars().all())


async def list_excluded_tags(db: AsyncSession, user_id: int) -> list[Tag]:
    """Return the excluded tag rows for one user.

    Rows whose tag was deleted disappear via the foreign-key cascade, so every
    returned tag exists. Visibility (global versus another user's private tag)
    is enforced by the service, not here.

    Args:
        db: Database session.
        user_id: Owner of the exclusions.

    Returns:
        Excluded tags ordered by scope then normalized name for stable display.
    """
    result = await db.execute(
        select(Tag)
        .join(RollTagExclusion, RollTagExclusion.tag_id == Tag.id)
        .where(RollTagExclusion.user_id == user_id)
        .order_by(Tag.scope.desc(), Tag.normalized_name)
    )
    return list(result.scalars().all())


async def get_exclusion(
    db: AsyncSession, user_id: int, tag_id: int
) -> RollTagExclusion | None:
    """Return one user's exclusion of one tag, if it exists.

    Args:
        db: Database session.
        user_id: Owner of the exclusion.
        tag_id: Excluded tag.

    Returns:
        The exclusion row, or ``None`` when the user has not excluded the tag.
    """
    result = await db.execute(
        select(RollTagExclusion).where(
            RollTagExclusion.user_id == user_id,
            RollTagExclusion.tag_id == tag_id,
        )
    )
    return result.scalar_one_or_none()


async def add_exclusion(
    db: AsyncSession, user_id: int, tag_id: int
) -> RollTagExclusion:
    """Persist one user's exclusion of one tag.

    The operation is idempotent: an existing row is returned unchanged.

    Args:
        db: Database session.
        user_id: Owner of the exclusion.
        tag_id: Excluded tag.

    Returns:
        The new or existing exclusion row.
    """
    existing = await get_exclusion(db, user_id, tag_id)
    if existing is not None:
        return existing
    exclusion = RollTagExclusion(user_id=user_id, tag_id=tag_id)
    db.add(exclusion)
    await db.flush()
    await db.refresh(exclusion)
    return exclusion


async def remove_exclusion(db: AsyncSession, user_id: int, tag_id: int) -> bool:
    """Remove one user's exclusion of one tag.

    Args:
        db: Database session.
        user_id: Owner of the exclusion.
        tag_id: Excluded tag.

    Returns:
        ``True`` when a row was removed, ``False`` when none existed.
    """
    result = await db.execute(
        delete(RollTagExclusion)
        .where(
            RollTagExclusion.user_id == user_id,
            RollTagExclusion.tag_id == tag_id,
        )
        .execution_options(synchronize_session="fetch")
    )
    return (getattr(result, "rowcount", 0) or 0) > 0


async def delete_exclusions_for_tag(db: AsyncSession, tag_id: int) -> int:
    """Delete every user's exclusion of a tag being deleted.

    Called by the tag-deletion hook consumer so a deleted tag stops filtering
    Roll pools. Assignment rows are handled separately by the tag service.

    Args:
        db: Database session.
        tag_id: Primary key of the deleted tag.

    Returns:
        Number of exclusion rows removed.
    """
    result = await db.execute(
        delete(RollTagExclusion)
        .where(RollTagExclusion.tag_id == tag_id)
        .execution_options(synchronize_session="fetch")
    )
    return getattr(result, "rowcount", 0) or 0


async def count_exclusions_for_tag(db: AsyncSession, tag_id: int) -> int:
    """Count exclusion rows referencing a tag without removing them.

    The tag usage endpoint uses this so the delete-confirmation dialog can
    show whether the tag is referenced by roll exclusions before deletion.

    Args:
        db: Database session.
        tag_id: Primary key of the tag.

    Returns:
        Number of exclusion rows referencing the tag.
    """
    result = await db.execute(
        select(func.count(RollTagExclusion.id)).where(
            RollTagExclusion.tag_id == tag_id
        )
    )
    return result.scalar_one()


async def fetch_effective_tag_ids_for_candidates(
    db: AsyncSession,
    user_id: int,
    candidates: list[tuple[int, int | None]],
) -> dict[int, set[int]]:
    """Return effective tag IDs for many roll candidates in bulk.

    Each candidate is a ``(thread_id, next_unread_issue_id)`` pair from the
    roll pool. Effective tags for a candidate are the union of the tags
    directly assigned to its thread, the tags directly assigned to its next
    unread issue, and the tags of every Reading Plan owned by the viewer that
    contains that issue — the same additive inheritance the tag inheritance
    service computes for a single issue, resolved here in a constant number
    of round trips (one plan-membership query plus one assignment query) so
    the roll path never issues one tag lookup per candidate.

    Only tags visible to the viewer (every global tag plus the viewer's own
    private tags) contribute, so another user's private vocabulary can never
    exclude a candidate.

    Args:
        db: Database session.
        user_id: Viewer whose private vocabulary is included.
        candidates: ``(thread_id, next_unread_issue_id)`` pairs. A ``None``
            issue ID means the thread has no tracked next issue, so only its
            thread tags contribute.

    Returns:
        Map from each requested thread ID to its effective tag ID set. Threads
        with no visible tags map to an empty set.
    """
    thread_ids = list(dict.fromkeys(thread_id for thread_id, _ in candidates))
    issue_ids = list(
        dict.fromkeys(issue_id for _, issue_id in candidates if issue_id is not None)
    )
    if not thread_ids:
        return {}

    plans_by_issue = await reading_plan_repository.plans_containing_issues_for_user(
        db, issue_ids=issue_ids, user_id=user_id
    )
    plan_ids = list(
        dict.fromkeys(
            plan.id for plans in plans_by_issue.values() for plan in plans
        )
    )

    targets: list[tuple[str, int]] = [("Thread", thread_id) for thread_id in thread_ids]
    targets.extend(("Issue", issue_id) for issue_id in issue_ids)
    targets.extend(("ContinuityPlan", plan_id) for plan_id in plan_ids)
    pairs = await tag_repository.list_visible_assignments_for_targets(
        db, user_id, targets
    )

    thread_tag_ids: dict[int, set[int]] = {thread_id: set() for thread_id in thread_ids}
    issue_tag_ids: dict[int, set[int]] = {issue_id: set() for issue_id in issue_ids}
    plan_tag_ids: dict[int, set[int]] = {plan_id: set() for plan_id in plan_ids}
    for tag, assignment in pairs:
        if assignment.target_type == "Thread":
            thread_tag_ids.setdefault(assignment.target_id, set()).add(tag.id)
        elif assignment.target_type == "Issue":
            issue_tag_ids.setdefault(assignment.target_id, set()).add(tag.id)
        elif assignment.target_type == "ContinuityPlan":
            plan_tag_ids.setdefault(assignment.target_id, set()).add(tag.id)

    effective: dict[int, set[int]] = {}
    for thread_id, issue_id in candidates:
        tag_ids = set(thread_tag_ids.get(thread_id, set()))
        if issue_id is not None:
            tag_ids |= issue_tag_ids.get(issue_id, set())
            for plan in plans_by_issue.get(issue_id, []):
                tag_ids |= plan_tag_ids.get(plan.id, set())
        effective[thread_id] = tag_ids
    return effective
