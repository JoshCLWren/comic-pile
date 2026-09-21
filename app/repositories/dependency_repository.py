"""Dependency query construction and persistence.

All SQLAlchemy access for the ``Dependency`` model family lives here. Functions
return ORM models or plain values; callers (services) own transactions.
"""


from sqlalchemy import delete, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import Dependency, Issue, Thread


async def get_dependency(db: AsyncSession, dependency_id: int) -> Dependency | None:
    """Return a dependency by primary key.

    Args:
        db: Database session.
        dependency_id: Primary key of the dependency.

    Returns:
        The dependency, or None when it does not exist.
    """
    return await db.get(Dependency, dependency_id)


async def get_thread_dependencies(
    db: AsyncSession, thread_id: int
) -> tuple[list[Dependency], list[Dependency]]:
    """Get dependencies where a thread blocks others and where it is blocked.

    Args:
        db: Database session.
        thread_id: Thread ID to find dependencies for.

    Returns:
        Tuple of (blocking_dependencies, blocked_by_dependencies).
    """
    source_issue = Issue.__table__.alias("source_issue")
    target_issue = Issue.__table__.alias("target_issue")

    blocking_result = await db.execute(
        select(Dependency)
        .join(source_issue, Dependency.source_issue_id == source_issue.c.id)
        .where(source_issue.c.thread_id == thread_id)
    )
    blocked_by_result = await db.execute(
        select(Dependency)
        .join(target_issue, Dependency.target_issue_id == target_issue.c.id)
        .where(target_issue.c.thread_id == thread_id)
    )

    blocking_deps = list(blocking_result.scalars().all())
    blocked_by_deps = list(blocked_by_result.scalars().all())

    return blocking_deps, blocked_by_deps


async def get_issue_dependencies(db: AsyncSession, issue_id: int) -> tuple[list[Dependency], list[Dependency]]:
    """Get all incoming and outgoing dependency edges for a specific issue.

    Args:
        db: Database session.
        issue_id: Issue ID to find dependencies for.

    Returns:
        Tuple of (incoming_dependencies, outgoing_dependencies).
    """
    incoming_result = await db.execute(
        select(Dependency).where(Dependency.target_issue_id == issue_id)
    )
    outgoing_result = await db.execute(
        select(Dependency).where(Dependency.source_issue_id == issue_id)
    )

    incoming_deps = list(incoming_result.scalars().all())
    outgoing_deps = list(outgoing_result.scalars().all())

    return incoming_deps, outgoing_deps


async def get_thread_connected_dependencies(
    db: AsyncSession, thread_id: int
) -> tuple[list[Dependency], list[Dependency]]:
    """Get dependencies connected to a specific thread.

    Args:
        db: Database session.
        thread_id: Thread ID to find connected dependencies for.

    Returns:
        Tuple of (blocking_dependencies, blocked_by_dependencies).
    """
    source_issue = Issue.__table__.alias("source_issue")
    target_issue = Issue.__table__.alias("target_issue")

    blocking_result = await db.execute(
        select(Dependency)
        .join(source_issue, Dependency.source_issue_id == source_issue.c.id)
        .where(source_issue.c.thread_id == thread_id)
    )
    blocked_by_result = await db.execute(
        select(Dependency)
        .join(target_issue, Dependency.target_issue_id == target_issue.c.id)
        .where(target_issue.c.thread_id == thread_id)
    )

    blocking_deps = list(blocking_result.scalars().all())
    blocked_by_deps = list(blocked_by_result.scalars().all())

    return blocking_deps, blocked_by_deps


async def get_dependency_by_ids(
    db: AsyncSession, source_issue_id: int, target_issue_id: int
) -> Dependency | None:
    """Get a dependency by source and target issue IDs.

    Args:
        db: Database session.
        source_issue_id: Source issue ID.
        target_issue_id: Target issue ID.

    Returns:
        The dependency, or None when it does not exist.
    """
    result = await db.execute(
        select(Dependency).where(
            Dependency.source_issue_id == source_issue_id,
            Dependency.target_issue_id == target_issue_id,
        )
    )
    return result.scalar_one_or_none()


async def create_dependency(
    db: AsyncSession, source_issue_id: int, target_issue_id: int
) -> Dependency:
    """Create a new dependency.

    Args:
        db: Database session.
        source_issue_id: Source issue ID.
        target_issue_id: Target issue ID.

    Returns:
        The created dependency.
    """
    dependency = Dependency(
        source_issue_id=source_issue_id,
        target_issue_id=target_issue_id,
    )
    db.add(dependency)
    return dependency


async def update_dependency_note(
    db: AsyncSession, dependency_id: int, note: str | None
) -> Dependency:
    """Update the note on a dependency.

    Args:
        db: Database session.
        dependency_id: Dependency ID to update.
        note: New note value.

    Returns:
        The updated dependency.
    """
    result = await db.execute(
        select(Dependency).where(Dependency.id == dependency_id)
    )
    dependency = result.scalar_one()
    dependency.note = note
    return dependency


async def delete_dependency(db: AsyncSession, dependency_id: int) -> None:
    """Delete a dependency.

    Args:
        db: Database session.
        dependency_id: Dependency ID to delete.
    """
    await db.execute(delete(Dependency).where(Dependency.id == dependency_id))


async def get_issue_dependencies_batch(
    db: AsyncSession, issue_ids: list[int]
) -> list[Dependency]:
    """Get all dependencies involving any of the given issues.

    Args:
        db: Database session.
        issue_ids: Issue identifiers to search for.

    Returns:
        Every dependency where source or target is in ``issue_ids``.
    """
    if not issue_ids:
        return []
    result = await db.execute(
        select(Dependency)
        .where(
            or_(
                Dependency.source_issue_id.in_(issue_ids),
                Dependency.target_issue_id.in_(issue_ids),
            )
        )
        .order_by(Dependency.id)
    )
    return list(result.scalars())


async def is_dependency_owned_by_user(
    dependency: Dependency, user_id: int, db: AsyncSession
) -> bool:
    """Return whether a dependency belongs to the given user.

    Args:
        dependency: Dependency row to validate ownership for.
        user_id: Authenticated user ID to compare against.
        db: Database session used for related Issue lookups.

    Returns:
        True when the dependency belongs to the user; otherwise False.
        Ownership is checked through source_issue_id -> thread.user_id.
    """
    if dependency.source_issue_id is not None:
        from app.repositories import issue_repository
        source_issue = await issue_repository.get_issue(db, dependency.source_issue_id)
        if not source_issue:
            return False
        source_thread = await db.get(Thread, source_issue.thread_id)
        return bool(source_thread and source_thread.user_id == user_id)
    return False
