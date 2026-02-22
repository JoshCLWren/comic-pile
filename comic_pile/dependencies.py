"""Dependency logic for hard-blocking queued threads."""

from collections import defaultdict, deque

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.dependency import Dependency
from app.models.thread import Thread


async def get_blocked_thread_ids(user_id: int, db: AsyncSession) -> set[int]:
    """Return thread IDs blocked by unsatisfied dependencies for a user."""
    source = Thread.__table__.alias("source_thread")
    target = Thread.__table__.alias("target_thread")

    result = await db.execute(
        select(Dependency.target_thread_id)
        .join(source, Dependency.source_thread_id == source.c.id)
        .join(target, Dependency.target_thread_id == target.c.id)
        .where(source.c.user_id == user_id)
        .where(target.c.user_id == user_id)
        .where(source.c.status != "completed")
    )
    return {row[0] for row in result.all()}


async def get_blocking_explanations(thread_id: int, user_id: int, db: AsyncSession) -> list[str]:
    """Human-readable reasons a thread is blocked."""
    source = Thread.__table__.alias("source_thread")
    target = Thread.__table__.alias("target_thread")

    result = await db.execute(
        select(source.c.id, source.c.title)
        .join(Dependency, Dependency.source_thread_id == source.c.id)
        .join(target, Dependency.target_thread_id == target.c.id)
        .where(target.c.id == thread_id)
        .where(source.c.user_id == user_id)
        .where(target.c.user_id == user_id)
        .where(source.c.status != "completed")
    )
    return [f"Blocked by {title} (thread #{sid})" for sid, title in result.all()]


async def detect_circular_dependency(
    source_thread_id: int,
    target_thread_id: int,
    db: AsyncSession,
) -> bool:
    """Return True if adding source->target would introduce a cycle."""
    if source_thread_id == target_thread_id:
        return True

    result = await db.execute(select(Dependency.source_thread_id, Dependency.target_thread_id))
    adjacency: dict[int, set[int]] = defaultdict(set)
    for src, tgt in result.all():
        adjacency[src].add(tgt)

    queue = deque([target_thread_id])
    visited: set[int] = set()

    while queue:
        node = queue.popleft()
        if node in visited:
            continue
        visited.add(node)
        if node == source_thread_id:
            return True
        queue.extend(adjacency.get(node, set()))

    return False


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
