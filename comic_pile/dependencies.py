"""Dependency logic for hard-blocking queued threads."""

from collections import defaultdict, deque

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.dependency import Dependency
from app.models.issue import Issue
from app.models.thread import Thread


async def get_blocked_thread_ids(user_id: int, db: AsyncSession) -> set[int]:
    """Return thread IDs blocked by unsatisfied issue-level dependencies for a user."""
    source_issue = Issue.__table__.alias("source_issue")
    dep_target_issue = Issue.__table__.alias("dep_target_issue")
    target_next_unread = Issue.__table__.alias("target_next_unread")
    target_thread = Thread.__table__.alias("target_thread")
    source = Thread.__table__.alias("source_thread")

    issue_result = await db.execute(
        select(target_thread.c.id)
        .join(
            target_next_unread,
            target_next_unread.c.id == target_thread.c.next_unread_issue_id,
        )
        .join(
            dep_target_issue,
            (dep_target_issue.c.thread_id == target_thread.c.id)
            & (dep_target_issue.c.position >= target_next_unread.c.position),
        )
        .join(Dependency, Dependency.target_issue_id == dep_target_issue.c.id)
        .join(source_issue, Dependency.source_issue_id == source_issue.c.id)
        .join(source, source_issue.c.thread_id == source.c.id)
        .where(target_thread.c.user_id == user_id)
        .where(source.c.user_id == user_id)
        .where(source_issue.c.status != "read")
        .where(target_thread.c.next_unread_issue_id.isnot(None))
        .distinct()
    )
    return {row[0] for row in issue_result.all()}


async def get_blocking_explanations(thread_id: int, user_id: int, db: AsyncSession) -> list[str]:
    """Human-readable reasons a thread is blocked."""
    source_issue = Issue.__table__.alias("source_issue")
    dep_target_issue = Issue.__table__.alias("dep_target_issue")
    target_next_unread = Issue.__table__.alias("target_next_unread")
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
            target_next_unread,
            target_next_unread.c.id == target_thread.c.next_unread_issue_id,
        )
        .join(
            dep_target_issue,
            (dep_target_issue.c.thread_id == target_thread.c.id)
            & (dep_target_issue.c.position >= target_next_unread.c.position),
        )
        .join(Dependency, Dependency.target_issue_id == dep_target_issue.c.id)
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
    blocked_ids = await get_blocked_thread_ids(user_id, db)
    await db.execute(
        update(Thread)
        .where(Thread.id == thread_id)
        .where(Thread.user_id == user_id)
        .values(is_blocked=thread_id in blocked_ids)
    )


async def refresh_user_blocked_status(user_id: int, db: AsyncSession) -> None:
    """Recalculate blocked flags for all threads of a user."""
    blocked_ids = await get_blocked_thread_ids(user_id, db)

    await db.execute(update(Thread).where(Thread.user_id == user_id).values(is_blocked=False))

    if blocked_ids:
        await db.execute(
            update(Thread)
            .where(Thread.user_id == user_id)
            .where(Thread.id.in_(blocked_ids))
            .values(is_blocked=True)
        )
