"""Dependency query construction and persistence.

All SQLAlchemy access for the ``Dependency`` model family lives here. Functions
return ORM models or plain values; callers (services) own transactions.
"""


from dataclasses import dataclass

from sqlalchemy import delete, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import Dependency, Issue, Thread


@dataclass(frozen=True)
class ReaderDependencyGraph:
    """Reader-scoped dependency edges together with the issues they connect.

    Attributes:
        edges: Canonical ``(source_issue_id, target_issue_id)`` prerequisite
            pairs. Inert ``cbl-order:`` materialization rows are excluded
            because they can never constrain the reader.
        issues: ``(issue_id, thread_id, position, status)`` for every issue on
            either side of ``edges``. ``position`` is the canonical
            within-series reading order needed to complete the precedence
            graph.
    """

    edges: tuple[tuple[int, int], ...]
    issues: tuple[tuple[int, int, int, str], ...]


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
    db: AsyncSession, thread_id: int, *, reader_only: bool = False
) -> tuple[list[Dependency], list[Dependency]]:
    """Get dependencies connected to a specific thread.

    Args:
        db: Database session.
        thread_id: Thread ID to find connected dependencies for.
        reader_only: Restrict canonical connection displays to explicit reader intent.

    Returns:
        Tuple of (blocking_dependencies, blocked_by_dependencies).
    """
    source_issue = Issue.__table__.alias("source_issue")
    target_issue = Issue.__table__.alias("target_issue")

    blocking_statement = (
        select(Dependency)
        .join(source_issue, Dependency.source_issue_id == source_issue.c.id)
        .where(source_issue.c.thread_id == thread_id)
    )
    blocked_by_statement = (
        select(Dependency)
        .join(target_issue, Dependency.target_issue_id == target_issue.c.id)
        .where(target_issue.c.thread_id == thread_id)
    )
    if reader_only:
        blocking_statement = blocking_statement.where(Dependency.origin == "reader")
        blocked_by_statement = blocked_by_statement.where(Dependency.origin == "reader")
    blocking_result = await db.execute(blocking_statement)
    blocked_by_result = await db.execute(blocked_by_statement)

    blocking_deps = list(blocking_result.scalars().all())
    blocked_by_deps = list(blocked_by_result.scalars().all())

    return blocking_deps, blocked_by_deps


async def get_reader_dependency_graph(
    db: AsyncSession, user_id: int
) -> ReaderDependencyGraph:
    """Get every live dependency edge touching one reader's issues, with issue order.

    The issue -> issue dependency graph is the authority for circularity: a
    cycle in it is the only reading order that is impossible. Reading the
    whole reader-scoped graph keeps that verdict independent of which thread
    the caller happens to be looking at. Each endpoint's series position
    travels with the edge because the required within-series order is an
    implicit precedence constraint that the stored rows do not contain.

    Only canonical Dependency rows take part. Historical ``cbl-order:``
    materialization rows are inert for the frozen canonical runtime
    (``comic_pile.dependencies``): they can never block, so they can never
    make a reading order impossible and must not manufacture a circular
    verdict. They are also the overwhelming majority of a real reader's rows,
    so excluding them keeps this reader-wide read proportional to the live
    constraints instead of the whole materialization history.

    Args:
        db: Database session.
        user_id: Reader whose dependency edges are read.

    Returns:
        Canonical stored edges plus the issue rows needed to complete the
        precedence graph with the required within-series order.
    """
    source_issue = Issue.__table__.alias("graph_source_issue")
    target_issue = Issue.__table__.alias("graph_target_issue")
    source_thread = Thread.__table__.alias("graph_source_thread")
    target_thread = Thread.__table__.alias("graph_target_thread")

    # Imported here because the legacy package's module init reaches back into
    # ``app.repositories``; a module-level import would close that cycle.
    from comic_pile.dependencies import _canonical_dependency_filter

    result = await db.execute(
        select(
            Dependency.source_issue_id.label("source_issue_id"),
            Dependency.target_issue_id.label("target_issue_id"),
        )
        .join(source_issue, source_issue.c.id == Dependency.source_issue_id)
        .join(source_thread, source_thread.c.id == source_issue.c.thread_id)
        .join(target_issue, target_issue.c.id == Dependency.target_issue_id)
        .join(target_thread, target_thread.c.id == target_issue.c.thread_id)
        .where(
            or_(
                source_thread.c.user_id == user_id,
                target_thread.c.user_id == user_id,
            )
        )
        .where(_canonical_dependency_filter())
    )

    edges: list[tuple[int, int]] = []
    issue_ids: set[int] = set()
    for source_issue_id, target_issue_id in result.all():
        edges.append((source_issue_id, target_issue_id))
        issue_ids.add(source_issue_id)
        issue_ids.add(target_issue_id)

    if not issue_ids:
        return ReaderDependencyGraph(edges=tuple(edges), issues=())

    issue_result = await db.execute(
        select(
            Issue.id.label("issue_id"),
            Issue.thread_id.label("thread_id"),
            Issue.position.label("position"),
            Issue.status.label("status"),
        ).where(Issue.id.in_(issue_ids))
    )
    issues = tuple(
        (row.issue_id, row.thread_id, row.position, row.status)
        for row in issue_result.all()
    )

    return ReaderDependencyGraph(edges=tuple(edges), issues=issues)


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
