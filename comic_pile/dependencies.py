"""Dependency logic for hard-blocking queued threads."""

from collections import defaultdict, deque

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.dependency import Dependency
from app.models.issue import Issue
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
    blocked_by_threads = {row[0] for row in result.all()}

    source_issue = Issue.__table__.alias("source_issue")
    target_issue = Issue.__table__.alias("target_issue")
    target_thread = Thread.__table__.alias("target_thread")

    issue_result = await db.execute(
        select(target_thread.c.id)
        .join(target_issue, target_thread.c.next_unread_issue_id == target_issue.c.id)
        .join(Dependency, Dependency.target_issue_id == target_issue.c.id)
        .join(source_issue, Dependency.source_issue_id == source_issue.c.id)
        .join(source, source_issue.c.thread_id == source.c.id)
        .where(target_thread.c.user_id == user_id)
        .where(source.c.user_id == user_id)
        .where(source_issue.c.status != "read")
    )
    blocked_by_issues = {row[0] for row in issue_result.all()}
    return blocked_by_threads | blocked_by_issues


async def get_blocking_explanations(thread_id: int, user_id: int, db: AsyncSession) -> list[str]:
    """Human-readable reasons a thread is blocked."""
    source = Thread.__table__.alias("source_thread")
    target = Thread.__table__.alias("target_thread")

    thread_result = await db.execute(
        select(source.c.id, source.c.title)
        .join(Dependency, Dependency.source_thread_id == source.c.id)
        .join(target, Dependency.target_thread_id == target.c.id)
        .where(target.c.id == thread_id)
        .where(source.c.user_id == user_id)
        .where(target.c.user_id == user_id)
        .where(source.c.status != "completed")
    )
    thread_reasons = [f"Blocked by {title} (thread #{sid})" for sid, title in thread_result.all()]

    source_issue = Issue.__table__.alias("source_issue")
    target_issue = Issue.__table__.alias("target_issue")
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
        .join(target_issue, target_thread.c.next_unread_issue_id == target_issue.c.id)
        .join(Dependency, Dependency.target_issue_id == target_issue.c.id)
        .join(source_issue, Dependency.source_issue_id == source_issue.c.id)
        .join(source_thread, source_issue.c.thread_id == source_thread.c.id)
        .where(target_thread.c.id == thread_id)
        .where(target_thread.c.user_id == user_id)
        .where(source_thread.c.user_id == user_id)
        .where(source_issue.c.status != "read")
    )
    issue_reasons = [
        f"Blocked by issue #{issue_number} in {thread_title} (thread #{thread_id_val})"
        for thread_id_val, thread_title, _issue_id, issue_number in issue_result.all()
    ]
    return thread_reasons + issue_reasons


async def detect_circular_dependency(
    source_id: int,
    target_id: int,
    dependency_type: str,
    db: AsyncSession,
) -> bool:
    """Return True if adding source->target would introduce a cycle."""
    if source_id == target_id:
        return True

    if dependency_type == "thread":
        result = await db.execute(select(Dependency.source_thread_id, Dependency.target_thread_id))
    elif dependency_type == "issue":
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
