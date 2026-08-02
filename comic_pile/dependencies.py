"""Dependency logic for hard-blocking queued threads."""

from collections import defaultdict, deque

from sqlalchemy import or_, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.cache import TTL, cached
from app.models.dependency import Dependency
from app.models.issue import Issue
from app.models.thread import Thread


async def _get_blocked_thread_ids_uncached(user_id: int, db: AsyncSession) -> set[int]:
    """Read blocked thread IDs directly from the current database transaction."""
    source_issue = Issue.__table__.alias("source_issue")
    next_unread_issue = Issue.__table__.alias("next_unread_issue")
    target_thread = Thread.__table__.alias("target_thread")
    source = Thread.__table__.alias("source_thread")

    issue_result = await db.execute(
        select(target_thread.c.id)
        .join(
            next_unread_issue,
            next_unread_issue.c.id == target_thread.c.next_unread_issue_id,
        )
        .join(Dependency, Dependency.target_issue_id == next_unread_issue.c.id)
        .join(source_issue, Dependency.source_issue_id == source_issue.c.id)
        .join(source, source_issue.c.thread_id == source.c.id)
        .where(target_thread.c.user_id == user_id)
        .where(source.c.user_id == user_id)
        .where(source_issue.c.status != "read")
        .where(target_thread.c.next_unread_issue_id.isnot(None))
        .distinct()
    )
    return {row[0] for row in issue_result.all()}


@cached(ttl=TTL.SHORT)
async def get_blocked_thread_ids(user_id: int, db: AsyncSession) -> set[int]:
    """Return cached blocked thread IDs for non-transactional reads."""
    return await _get_blocked_thread_ids_uncached(user_id, db)


async def get_blocking_explanations(thread_id: int, user_id: int, db: AsyncSession) -> list[str]:
    """Human-readable reasons a thread is blocked."""
    source_issue = Issue.__table__.alias("source_issue")
    next_unread_issue = Issue.__table__.alias("next_unread_issue")
    source_thread = Thread.__table__.alias("source_thread")
    target_thread = Thread.__table__.alias("target_thread")

    issue_result = await db.execute(
        select(
            source_thread.c.id,
            source_thread.c.title,
            source_issue.c.id,
            source_issue.c.issue_number,
        )
        .select_from(target_thread)
        .join(
            next_unread_issue,
            next_unread_issue.c.id == target_thread.c.next_unread_issue_id,
        )
        .join(Dependency, Dependency.target_issue_id == next_unread_issue.c.id)
        .join(source_issue, Dependency.source_issue_id == source_issue.c.id)
        .join(source_thread, source_issue.c.thread_id == source_thread.c.id)
        .where(target_thread.c.id == thread_id)
        .where(target_thread.c.user_id == user_id)
        .where(source_thread.c.user_id == user_id)
        .where(source_issue.c.status != "read")
        .where(target_thread.c.next_unread_issue_id.isnot(None))
        .distinct()
    )
    return [
        f"Blocked by issue #{issue_number} in {thread_title} (thread #{thread_id_val})"
        for thread_id_val, thread_title, _issue_id, issue_number in issue_result.all()
    ]


async def get_blocking_explanations_batch(
    thread_ids: list[int],
    user_id: int,
    db: AsyncSession,
) -> dict[int, list[str]]:
    """Human-readable blocking reasons for multiple threads in one query."""
    if not thread_ids:
        return {}

    source_issue = Issue.__table__.alias("source_issue")
    next_unread_issue = Issue.__table__.alias("next_unread_issue")
    source_thread = Thread.__table__.alias("source_thread")
    target_thread = Thread.__table__.alias("target_thread")

    result = await db.execute(
        select(
            target_thread.c.id,
            source_thread.c.id,
            source_thread.c.title,
            source_issue.c.id,
            source_issue.c.issue_number,
        )
        .join(
            next_unread_issue,
            next_unread_issue.c.id == target_thread.c.next_unread_issue_id,
        )
        .join(Dependency, Dependency.target_issue_id == next_unread_issue.c.id)
        .join(source_issue, Dependency.source_issue_id == source_issue.c.id)
        .join(source_thread, source_issue.c.thread_id == source_thread.c.id)
        .where(target_thread.c.id.in_(thread_ids))
        .where(target_thread.c.user_id == user_id)
        .where(source_thread.c.user_id == user_id)
        .where(source_issue.c.status != "read")
        .where(target_thread.c.next_unread_issue_id.isnot(None))
    )

    reasons_map: dict[int, list[str]] = {}
    for target_tid, src_tid, src_title, _src_iid, src_issue_num in result.all():
        reasons_map.setdefault(target_tid, []).append(
            f"Blocked by issue #{src_issue_num} in {src_title} (thread #{src_tid})"
        )
    return reasons_map


async def validate_position_dependency_consistency(
    thread_id: int,
    user_id: int,
    db: AsyncSession,
) -> list[str]:
    """Return warnings where in-thread dependency order conflicts with issue positions."""
    source_issue = Issue.__table__.alias("source_issue")
    target_issue = Issue.__table__.alias("target_issue")
    thread = Thread.__table__.alias("thread")

    result = await db.execute(
        select(
            thread.c.title,
            source_issue.c.issue_number,
            source_issue.c.position,
            target_issue.c.issue_number,
            target_issue.c.position,
        )
        .select_from(Dependency)
        .join(source_issue, Dependency.source_issue_id == source_issue.c.id)
        .join(target_issue, Dependency.target_issue_id == target_issue.c.id)
        .join(thread, source_issue.c.thread_id == thread.c.id)
        .where(thread.c.id == thread_id)
        .where(thread.c.user_id == user_id)
        .where(target_issue.c.thread_id == thread.c.id)
        .where(source_issue.c.position >= target_issue.c.position)
        .order_by(source_issue.c.position, target_issue.c.position, Dependency.id)
    )

    return [
        (
            f'In thread "{thread_title}", issue #{source_issue_number} '
            f"(position {source_position}) blocks issue #{target_issue_number} "
            f"(position {target_position}). Position is canonical for in-thread order."
        )
        for (
            thread_title,
            source_issue_number,
            source_position,
            target_issue_number,
            target_position,
        ) in result.all()
    ]


async def detect_circular_dependency(
    source_id: int,
    target_id: int,
    dependency_type: str,
    db: AsyncSession,
) -> bool:
    """Return True if adding source->target would introduce a cycle."""
    if source_id == target_id:
        return True

    if dependency_type == "issue":
        result = await db.execute(select(Dependency.source_issue_id, Dependency.target_issue_id))
    else:
        return False

    adjacency: dict[int, set[int]] = defaultdict(set)
    for src, tgt in result.all():
        if src is None or tgt is None:
            continue
        adjacency[src].add(tgt)

    queue = deque([target_id])
    visited: set[int] = set()

    while queue:
        node = queue.popleft()
        if node in visited:
            continue
        visited.add(node)
        if node == source_id:
            return True
        queue.extend(adjacency.get(node, set()))

    return False


async def get_dependency_order_conflicts(
    thread_id: int,
    user_id: int,
    db: AsyncSession,
) -> list[dict]:
    """Return structured conflicts where dependency order disagrees with issue position order.

    Args:
        thread_id: Thread to check for conflicts.
        user_id: Authenticated user ID for ownership validation.
        db: Database session.

    Returns:
        List of conflict dictionaries with issue details and dependency requirements.
    """
    source_issue = Issue.__table__.alias("source_issue")
    target_issue = Issue.__table__.alias("target_issue")
    thread = Thread.__table__.alias("thread")

    result = await db.execute(
        select(
            thread.c.id,
            thread.c.title,
            source_issue.c.id.label("source_issue_id"),
            source_issue.c.issue_number.label("source_issue_number"),
            source_issue.c.position.label("source_position"),
            target_issue.c.id.label("target_issue_id"),
            target_issue.c.issue_number.label("target_issue_number"),
            target_issue.c.position.label("target_position"),
        )
        .select_from(Dependency)
        .join(source_issue, Dependency.source_issue_id == source_issue.c.id)
        .join(target_issue, Dependency.target_issue_id == target_issue.c.id)
        .join(thread, source_issue.c.thread_id == thread.c.id)
        .where(thread.c.id == thread_id)
        .where(thread.c.user_id == user_id)
        .where(target_issue.c.thread_id == thread.c.id)
        .where(source_issue.c.position >= target_issue.c.position)
        .order_by(source_issue.c.position, target_issue.c.position, Dependency.id)
    )

    conflicts: list[dict] = []
    for row in result.all():
        conflicts.append(
            {
                "issue_id": row.source_issue_id,
                "issue_number": row.source_issue_number,
                "position": row.source_position,
                "dependency_requires_before": [
                    {
                        "issue_id": row.target_issue_id,
                        "issue_number": row.target_issue_number,
                        "position": row.target_position,
                    }
                ],
                "conflict": f"position {row.source_position} comes after issue at position {row.target_position}, but dependency says it must come before",
            }
        )

    return conflicts


async def update_thread_blocked_status(thread_id: int, user_id: int, db: AsyncSession) -> None:
    """Recalculate one thread's denormalized blocked flag."""
    blocked_ids = await _get_blocked_thread_ids_uncached(user_id, db)
    await db.execute(
        update(Thread)
        .where(Thread.id == thread_id)
        .where(Thread.user_id == user_id)
        .values(is_blocked=thread_id in blocked_ids)
    )


async def refresh_user_blocked_status(
    user_id: int,
    db: AsyncSession,
) -> dict[int, bool]:
    """Recalculate blocked flags and return prior values that changed.

    Args:
        user_id: Thread owner.
        db: Database session.

    Returns:
        Mapping of changed thread IDs to their previous blocked flag.
    """
    blocked_ids = await _get_blocked_thread_ids_uncached(user_id, db)

    candidate_filter = Thread.is_blocked.is_(True)
    if blocked_ids:
        candidate_filter = or_(candidate_filter, Thread.id.in_(blocked_ids))

    result = await db.execute(
        select(Thread.id, Thread.is_blocked)
        .where(Thread.user_id == user_id)
        .where(candidate_filter)
    )
    prior_values = {row.id: row.is_blocked for row in result.all()}
    changes = {
        thread_id: old_value
        for thread_id, old_value in prior_values.items()
        if old_value != (thread_id in blocked_ids)
    }

    to_unblock = [thread_id for thread_id in changes if thread_id not in blocked_ids]
    if to_unblock:
        await db.execute(
            update(Thread)
            .where(Thread.user_id == user_id)
            .where(Thread.id.in_(to_unblock))
            .values(is_blocked=False)
        )

    to_block = [thread_id for thread_id in changes if thread_id in blocked_ids]
    if to_block:
        await db.execute(
            update(Thread)
            .where(Thread.user_id == user_id)
            .where(Thread.id.in_(to_block))
            .values(is_blocked=True)
        )

    return changes
