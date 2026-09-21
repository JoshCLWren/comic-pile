"""Dependency-group persistence and crossover query construction.

All SQLAlchemy access for user-owned named dependency groups, memberships,
crossover plan lookups, and membership metadata reads lives here. Functions
return ORM models, plain tuples, or dicts; orchestration and response
building live in ``app/services/dependency_group_service.py``.
"""

from collections.abc import Sequence

from sqlalchemy import func, or_, select, union_all
from sqlalchemy.dialects.postgresql import JSONB, insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.models import DependencyGroup, DependencyGroupMembership, Issue, Thread
from app.models.continuity_plan import ContinuityPlan


async def find_owned_group(
    db: AsyncSession,
    group_id: int,
    user_id: int,
) -> DependencyGroup | None:
    """Return one user-owned group with memberships, or ``None``.

    Args:
        db: The asynchronous database session.
        group_id: The dependency group identifier.
        user_id: The authenticated group owner.

    Returns:
        The owned group with memberships loaded, or ``None`` when the group
        does not exist or is not owned by the user.
    """
    result = await db.execute(
        select(DependencyGroup)
        .options(selectinload(DependencyGroup.memberships))
        .where(DependencyGroup.id == group_id, DependencyGroup.user_id == user_id)
    )
    return result.scalar_one_or_none()


async def list_groups_for_user(db: AsyncSession, user_id: int) -> list[DependencyGroup]:
    """Return every group owned by a user ordered by name and identifier.

    Args:
        db: The asynchronous database session.
        user_id: The authenticated group owner.

    Returns:
        The user's groups with memberships loaded.
    """
    result = await db.execute(
        select(DependencyGroup)
        .options(selectinload(DependencyGroup.memberships))
        .where(DependencyGroup.user_id == user_id)
        .order_by(DependencyGroup.name, DependencyGroup.id)
    )
    return list(result.scalars().unique())


async def list_memberships(
    db: AsyncSession,
    group_id: int,
) -> list[DependencyGroupMembership]:
    """Return one group's memberships ordered by membership identifier.

    Args:
        db: The asynchronous database session.
        group_id: The dependency group identifier.

    Returns:
        The persisted memberships sorted by insertion order.
    """
    result = await db.execute(
        select(DependencyGroupMembership)
        .where(DependencyGroupMembership.group_id == group_id)
        .order_by(DependencyGroupMembership.id)
    )
    return list(result.scalars())


async def thread_titles_by_id(db: AsyncSession, thread_ids: set[int]) -> dict[int, str]:
    """Resolve thread titles for a set of thread identifiers.

    Args:
        db: The asynchronous database session.
        thread_ids: Thread identifiers to describe.

    Returns:
        Mapping of thread ID to its title for every resolvable thread.
    """
    if not thread_ids:
        return {}
    result = await db.execute(select(Thread.id, Thread.title).where(Thread.id.in_(thread_ids)))
    return {row.id: row.title for row in result}


async def issue_series_metadata_by_id(
    db: AsyncSession,
    issue_ids: set[int],
) -> dict[int, tuple[str | None, str | None]]:
    """Resolve ``(issue number, series title)`` metadata for issues.

    Args:
        db: The asynchronous database session.
        issue_ids: Issue identifiers to describe.

    Returns:
        Mapping of issue ID to its number and owning thread title for every
        resolvable issue.
    """
    if not issue_ids:
        return {}
    result = await db.execute(
        select(Issue.id, Issue.issue_number, Thread.title)
        .join(Thread, Issue.thread_id == Thread.id)
        .where(Issue.id.in_(issue_ids))
    )
    return {row.id: (row.issue_number, row.title) for row in result}


async def get_owned_thread(
    db: AsyncSession,
    thread_id: int,
    user_id: int,
) -> Thread | None:
    """Return one thread owned by a user, or ``None``.

    Args:
        db: The asynchronous database session.
        thread_id: The thread identifier.
        user_id: The authenticated thread owner.

    Returns:
        The owned thread, or ``None`` when the thread is missing or foreign.
    """
    thread = await db.get(Thread, thread_id)
    if thread is None or thread.user_id != user_id:
        return None
    return thread


async def get_owned_thread_ids(
    db: AsyncSession,
    thread_ids: list[int],
    user_id: int,
) -> set[int]:
    """Return the identifiers of requested threads owned by a user.

    Args:
        db: The asynchronous database session.
        thread_ids: Thread identifiers to check for ownership.
        user_id: The authenticated thread owner.

    Returns:
        The subset of ``thread_ids`` that belong to the user, resolved in a
        single query rather than one lookup per thread.
    """
    if not thread_ids:
        return set()
    result = await db.execute(
        select(Thread.id).where(
            Thread.id.in_(thread_ids),
            Thread.user_id == user_id,
        )
    )
    return set(result.scalars().all())


async def get_owned_issue(
    db: AsyncSession,
    issue_id: int,
    user_id: int,
) -> Issue | None:
    """Return one issue whose owning thread belongs to a user, or ``None``.

    Args:
        db: The asynchronous database session.
        issue_id: The issue identifier.
        user_id: The authenticated thread owner.

    Returns:
        The issue when its parent thread is owned by the user, otherwise
        ``None`` for a missing issue, a missing parent thread, or foreign
        ownership.
    """
    issue = await db.get(Issue, issue_id)
    if issue is None:
        return None
    thread = await db.get(Thread, issue.thread_id)
    if thread is None or thread.user_id != user_id:
        return None
    return issue


async def get_membership(
    db: AsyncSession,
    member_id: int,
) -> DependencyGroupMembership | None:
    """Return one membership row by identifier, or ``None``.

    Args:
        db: The asynchronous database session.
        member_id: The membership identifier.

    Returns:
        The persisted membership, or ``None`` when it does not exist.
    """
    return await db.get(DependencyGroupMembership, member_id)


async def sequence_occupied(
    db: AsyncSession,
    group_id: int,
    sequence_order: int,
) -> bool:
    """Return whether a crossover sequence position is already occupied.

    Args:
        db: The asynchronous database session.
        group_id: The dependency group identifier.
        sequence_order: The proposed authoritative reading sequence position.

    Returns:
        ``True`` when another membership in the group already uses the
        position.
    """
    result = await db.execute(
        select(DependencyGroupMembership.id).where(
            DependencyGroupMembership.group_id == group_id,
            DependencyGroupMembership.sequence_order == sequence_order,
        )
    )
    return result.scalar_one_or_none() is not None


async def issue_memberships_by_issue(
    db: AsyncSession,
    group_id: int,
) -> dict[int, DependencyGroupMembership]:
    """Index a group's issue-level memberships by their issue identifier.

    Args:
        db: The asynchronous database session.
        group_id: The dependency group identifier.

    Returns:
        Mapping of issue ID to its membership for every issue-level member.
    """
    result = await db.execute(
        select(DependencyGroupMembership)
        .where(DependencyGroupMembership.group_id == group_id)
        .where(DependencyGroupMembership.issue_id.isnot(None))
    )
    memberships = list(result.scalars())
    return {
        membership.issue_id: membership
        for membership in memberships
        if membership.issue_id is not None
    }


async def threads_by_id(db: AsyncSession, thread_ids: set[int]) -> dict[int, Thread]:
    """Resolve thread models by identifier.

    Args:
        db: The asynchronous database session.
        thread_ids: Thread identifiers to load.

    Returns:
        Mapping of thread ID to its model for every resolvable thread.
    """
    if not thread_ids:
        return {}
    result = await db.execute(select(Thread).where(Thread.id.in_(thread_ids)))
    return {thread.id: thread for thread in result.scalars()}


async def issues_by_id(db: AsyncSession, issue_ids: set[int]) -> dict[int, Issue]:
    """Resolve issue models by identifier.

    Args:
        db: The asynchronous database session.
        issue_ids: Issue identifiers to load.

    Returns:
        Mapping of issue ID to its model for every resolvable issue.
    """
    if not issue_ids:
        return {}
    result = await db.execute(select(Issue).where(Issue.id.in_(issue_ids)))
    return {issue.id: issue for issue in result.scalars()}


async def issue_parent_thread_ids(
    db: AsyncSession,
    issue_ids: set[int],
) -> dict[int, int]:
    """Resolve each issue's parent thread identifier.

    Args:
        db: The asynchronous database session.
        issue_ids: Issue identifiers to describe.

    Returns:
        Mapping of issue ID to its parent thread identifier.
    """
    if not issue_ids:
        return {}
    result = await db.execute(select(Issue.id, Issue.thread_id).where(Issue.id.in_(issue_ids)))
    return {row.id: row.thread_id for row in result}


async def owned_issues_by_id(
    db: AsyncSession,
    issue_ids: set[int],
    user_id: int,
) -> dict[int, Issue]:
    """Resolve issues whose owning threads belong to a user.

    Args:
        db: The asynchronous database session.
        issue_ids: Issue identifiers to load.
        user_id: The authenticated thread owner.

    Returns:
        Mapping of issue ID to its model for every issue whose parent thread
        is owned by the user.
    """
    if not issue_ids:
        return {}
    issues = await issues_by_id(db, issue_ids)
    thread_ids = {issue.thread_id for issue in issues.values() if issue.thread_id is not None}
    threads = await threads_by_id(db, thread_ids)
    owned: dict[int, Issue] = {}
    for issue_id, issue in issues.items():
        thread = threads.get(issue.thread_id) if issue.thread_id is not None else None
        if thread is not None and thread.user_id == user_id:
            owned[issue_id] = issue
    return owned


async def thread_group_summaries(
    db: AsyncSession,
    thread_id: int,
    user_id: int,
) -> list[tuple[int, str]]:
    """List distinct owned group summaries referencing a thread or its issues.

    Args:
        db: The asynchronous database session.
        thread_id: The owned thread identifier used for the lookup.
        user_id: The authenticated thread and group owner.

    Returns:
        Distinct ``(group id, group name)`` rows ordered by name then id.
    """
    issue_ids = select(Issue.id).where(Issue.thread_id == thread_id)
    result = await db.execute(
        select(DependencyGroup.id, DependencyGroup.name)
        .join(DependencyGroupMembership)
        .where(
            DependencyGroup.user_id == user_id,
            or_(
                DependencyGroupMembership.thread_id == thread_id,
                DependencyGroupMembership.issue_id.in_(issue_ids),
            ),
        )
        .distinct()
        .order_by(DependencyGroup.name, DependencyGroup.id)
    )
    return [(row.id, row.name) for row in result]


async def issues_in_range(
    db: AsyncSession,
    thread_id: int,
    start_position: int,
    end_position: int,
) -> list[Issue]:
    """Return an owned thread's issues within an inclusive position range.

    Args:
        db: The asynchronous database session.
        thread_id: The thread whose issues are resolved.
        start_position: Inclusive lower issue position.
        end_position: Inclusive upper issue position.

    Returns:
        The thread's issues in that range ordered by position.
    """
    result = await db.execute(
        select(Issue)
        .where(
            Issue.thread_id == thread_id,
            Issue.position >= start_position,
            Issue.position <= end_position,
        )
        .order_by(Issue.position)
    )
    return list(result.scalars())


async def insert_issue_memberships(
    db: AsyncSession,
    group_id: int,
    issue_ids: Sequence[int],
) -> list[int]:
    """Persist issue memberships while ignoring already-present duplicates.

    Args:
        db: The asynchronous database session.
        group_id: The dependency group identifier.
        issue_ids: Issue identifiers to add to the group.

    Returns:
        The issue identifiers actually inserted.
    """
    statement = (
        pg_insert(DependencyGroupMembership)
        .values([{"group_id": group_id, "issue_id": issue_id} for issue_id in issue_ids])
        .on_conflict_do_nothing(constraint="uq_dependency_group_issue")
        .returning(DependencyGroupMembership.issue_id)
    )
    return list(filter(None, (await db.execute(statement)).scalars()))


async def other_crossover_group_names_by_thread(
    db: AsyncSession,
    group_id: int,
    user_id: int,
    thread_ids: set[int],
) -> dict[int, list[str]]:
    """Resolve other crossover group names per referenced thread.

    Other groups (excluding ``group_id``) that reference a thread directly or
    through one of its issues are collected for each requested thread,
    ordered by group name.

    Args:
        db: The asynchronous database session.
        group_id: The group being excluded from the crossover list.
        user_id: The authenticated owner of the other groups.
        thread_ids: Thread identifiers whose cross-reference groups are wanted.

    Returns:
        Mapping of thread ID to its other crossover group names in input order
        per thread.
    """
    if not thread_ids:
        return {}

    thread_subquery = (
        select(DependencyGroupMembership.group_id.label("group_id"))
        .where(
            DependencyGroupMembership.thread_id.in_(thread_ids),
            DependencyGroupMembership.group_id != group_id,
        )
        .distinct()
    )
    issue_subquery = (
        select(DependencyGroupMembership.group_id.label("group_id"))
        .join(Issue, Issue.id == DependencyGroupMembership.issue_id)
        .where(
            Issue.thread_id.in_(thread_ids),
            DependencyGroupMembership.group_id != group_id,
        )
        .distinct()
    )
    combined = union_all(thread_subquery, issue_subquery).subquery()
    group_result = await db.execute(
        select(DependencyGroup.id, DependencyGroup.name)
        .where(
            DependencyGroup.user_id == user_id,
            DependencyGroup.id.in_(select(combined.c.group_id)),
        )
        .order_by(DependencyGroup.name)
    )
    group_name_map = {row.id: row.name for row in group_result}

    membership_result = await db.execute(
        select(
            DependencyGroupMembership.group_id,
            DependencyGroupMembership.thread_id,
            Issue.thread_id.label("issue_thread_id"),
        )
        .outerjoin(Issue, Issue.id == DependencyGroupMembership.issue_id)
        .where(
            or_(
                DependencyGroupMembership.thread_id.in_(thread_ids),
                Issue.thread_id.in_(thread_ids),
            ),
            DependencyGroupMembership.group_id != group_id,
        )
    )

    other_crossovers: dict[int, list[str]] = {thread_id: [] for thread_id in thread_ids}
    for row in membership_result:
        if row.thread_id is not None:
            thread_id = row.thread_id
        elif row.issue_thread_id is not None:
            thread_id = row.issue_thread_id
        else:
            continue
        if thread_id in other_crossovers and row.group_id in group_name_map:
            name = group_name_map[row.group_id]
            if name not in other_crossovers[thread_id]:
                other_crossovers[thread_id].append(name)
    return other_crossovers


async def thread_group_summaries_batch(
    db: AsyncSession,
    thread_ids: list[int],
    user_id: int,
) -> list[tuple[int, str, int]]:
    """List group summaries for multiple threads in one query.

    Each row is ``(group_id, group_name, thread_id)`` where ``thread_id``
    is the thread that the group relationship references (either directly or
    through an issue).

    Args:
        db: The asynchronous database session.
        thread_ids: The bounded thread identifiers to resolve.
        user_id: The authenticated group owner.

    Returns:
        Distinct ``(group id, group name, thread id)`` rows ordered by
        group name then identifier.
    """
    if not thread_ids:
        return []

    thread_membership = (
        select(
            DependencyGroupMembership.group_id,
            DependencyGroupMembership.thread_id.label("thread_id"),
        )
        .where(DependencyGroupMembership.thread_id.in_(thread_ids))
    )
    issue_membership = (
        select(
            DependencyGroupMembership.group_id,
            Issue.thread_id.label("thread_id"),
        )
        .join(Issue, Issue.id == DependencyGroupMembership.issue_id)
        .where(Issue.thread_id.in_(thread_ids))
    )
    combined = union_all(thread_membership, issue_membership).subquery()
    result = await db.execute(
        select(
            DependencyGroup.id,
            DependencyGroup.name,
            combined.c.thread_id,
        )
        .join(DependencyGroup, DependencyGroup.id == combined.c.group_id)
        .where(DependencyGroup.user_id == user_id)
        .distinct()
        .order_by(DependencyGroup.name, DependencyGroup.id)
    )
    return [(row.id, row.name, row.thread_id) for row in result]


async def linked_plan_summaries(
    db: AsyncSession,
    group_id: int,
    user_id: int,
) -> list[tuple[int, str]]:
    """List continuity plans that reference a crossover as a node.

    Args:
        db: The asynchronous database session.
        group_id: The dependency group identifier.
        user_id: The authenticated plan owner.

    Returns:
        ``(plan id, plan name)`` rows ordered by plan name then identifier.
    """
    crossover_node = {"node_type": "crossover", "ref_id": group_id}
    result = await db.execute(
        select(ContinuityPlan.id, ContinuityPlan.name)
        .where(
            ContinuityPlan.user_id == user_id,
            func.cast(ContinuityPlan.nodes_json, JSONB).contains([crossover_node]),
        )
        .order_by(ContinuityPlan.name, ContinuityPlan.id)
    )
    return [(row.id, row.name) for row in result]
