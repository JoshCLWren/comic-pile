"""Normalized Reading Plan membership query construction and persistence.

All SQLAlchemy access for the ``ReadingPlanIssue`` / ``ReadingPlanDependency``
/ ``ReadingPlanSource`` / ``ReadingPlanSourcePlacement`` model family lives
here. Functions return ORM models or plain values; callers (services) own
transactions.

Lifecycle contract (``docs/READING_GRAPH_PERSISTENCE_DESIGN.md`` section 2):

- plan deletion cascades only to plan-local lanes, occurrences, source
  snapshots/placements, and dependency links via ``ondelete="CASCADE"``;
- shared Issues and canonical Dependencies are never deleted by plan
  lifecycle; unlinking one plan never touches another plan's rows;
- there is no last-link garbage collection: standalone Dependencies with zero
  plan links are legitimate.
"""

from __future__ import annotations

from sqlalchemy import case, delete, func, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.dependency import Dependency
from app.models.issue import Issue
from app.models.reading_plan_membership import (
    ReadingPlanDependency,
    ReadingPlanIssue,
    ReadingPlanSource,
    ReadingPlanSourcePlacement,
)


async def replace_plan_issues(
    db: AsyncSession, *, plan_id: int, rows: list[ReadingPlanIssue]
) -> None:
    """Replace every membership occurrence row for one plan.

    Args:
        db: Database session.
        plan_id: Plan whose membership is replaced.
        rows: Fresh occurrence rows; only issue-type nodes are represented.
    """
    await db.execute(delete(ReadingPlanIssue).where(ReadingPlanIssue.plan_id == plan_id))
    await db.flush()
    for row in rows:
        row.plan_id = plan_id
        db.add(row)
    await db.flush()


async def replace_plan_sources(
    db: AsyncSession,
    *,
    plan_id: int,
    sources: list[ReadingPlanSource],
    placements: list[ReadingPlanSourcePlacement],
) -> None:
    """Replace every source snapshot and placement row for one plan.

    Args:
        db: Database session.
        plan_id: Plan whose provenance is replaced.
        sources: Fresh immutable source snapshots.
        placements: Fresh source-position observations for plan occurrences.
    """
    await db.execute(
        delete(ReadingPlanSourcePlacement).where(
            ReadingPlanSourcePlacement.plan_id == plan_id
        )
    )
    await db.execute(
        delete(ReadingPlanSource).where(ReadingPlanSource.plan_id == plan_id)
    )
    await db.flush()
    for source in sources:
        source.plan_id = plan_id
        db.add(source)
    await db.flush()
    for placement in placements:
        placement.plan_id = plan_id
        db.add(placement)
    await db.flush()


async def add_plan_source_placements(
    db: AsyncSession,
    *,
    plan_id: int,
    placements: list[ReadingPlanSourcePlacement],
) -> None:
    """Append source-position observations for one plan.

    Args:
        db: Database session.
        plan_id: Plan owning the placements.
        placements: Placement rows whose ``plan_source_id`` values reference
            already-persisted snapshots of the same plan.
    """
    for placement in placements:
        placement.plan_id = plan_id
        db.add(placement)
    await db.flush()


async def list_plan_issues(
    db: AsyncSession, *, plan_id: int
) -> list[ReadingPlanIssue]:
    """Return every membership occurrence row for one plan in display order.

    Args:
        db: Database session.
        plan_id: Plan to inspect.

    Returns:
        Occurrence rows ordered by lane then display position.
    """
    result = await db.execute(
        select(ReadingPlanIssue)
        .where(ReadingPlanIssue.plan_id == plan_id)
        .order_by(ReadingPlanIssue.lane_id, ReadingPlanIssue.display_position)
    )
    return list(result.scalars().all())


async def distinct_plan_issue_ids(
    db: AsyncSession, *, plan_id: int
) -> list[int]:
    """Return the distinct canonical Issue IDs referenced by one plan.

    Args:
        db: Database session.
        plan_id: Plan to inspect.

    Returns:
        Distinct Issue IDs; progress counts distinct Issues, not duplicate
        occurrences.
    """
    result = await db.execute(
        select(ReadingPlanIssue.issue_id)
        .where(ReadingPlanIssue.plan_id == plan_id)
        .distinct()
        .order_by(ReadingPlanIssue.issue_id)
    )
    return list(result.scalars().all())


async def list_plan_dependencies(
    db: AsyncSession, *, plan_id: int
) -> list[ReadingPlanDependency]:
    """Return every Dependency provenance link for one plan.

    Args:
        db: Database session.
        plan_id: Plan to inspect.

    Returns:
        Plan-to-Dependency links ordered by dependency ID.
    """
    result = await db.execute(
        select(ReadingPlanDependency)
        .where(ReadingPlanDependency.plan_id == plan_id)
        .order_by(ReadingPlanDependency.dependency_id)
    )
    return list(result.scalars().all())


async def list_plan_dependency_edges(
    db: AsyncSession, *, plan_id: int
) -> list[Dependency]:
    """Return the canonical Dependency edges referenced by one plan.

    Args:
        db: Database session.
        plan_id: Plan to inspect.

    Returns:
        Canonical edges ordered by ID. Multiple incoming edges to one target
        represent convergence; no ContinuityRule primitive is involved.
    """
    result = await db.execute(
        select(Dependency)
        .join(
            ReadingPlanDependency,
            ReadingPlanDependency.dependency_id == Dependency.id,
        )
        .where(ReadingPlanDependency.plan_id == plan_id)
        .order_by(Dependency.id)
    )
    return list(result.scalars().all())


async def link_plan_dependency(
    db: AsyncSession, *, plan_id: int, dependency_id: int, explanation: str | None = None
) -> ReadingPlanDependency:
    """Reference one canonical Dependency edge from one plan.

    Linking is idempotent: an existing link is returned unchanged.

    Args:
        db: Database session.
        plan_id: Plan referencing the edge.
        dependency_id: Canonical edge to reference.
        explanation: Optional human explanation, never an ownership marker.

    Returns:
        The plan-to-Dependency link.
    """
    existing = await db.get(ReadingPlanDependency, (plan_id, dependency_id))
    if existing is not None:
        return existing
    link = ReadingPlanDependency(
        plan_id=plan_id, dependency_id=dependency_id, explanation=explanation
    )
    db.add(link)
    await db.flush()
    return link


async def unlink_plan_dependency(
    db: AsyncSession, *, plan_id: int, dependency_id: int
) -> bool:
    """Remove one plan's reference to a Dependency edge.

    Only this plan's link row is deleted; the canonical edge and every other
    plan's links are untouched.

    Args:
        db: Database session.
        plan_id: Plan to unlink.
        dependency_id: Canonical edge to stop referencing.

    Returns:
        True when a link existed and was removed.
    """
    link = await db.get(ReadingPlanDependency, (plan_id, dependency_id))
    if link is None:
        return False
    await db.delete(link)
    await db.flush()
    return True


async def plans_referencing_dependency(
    db: AsyncSession, *, dependency_id: int
) -> list[int]:
    """Return every plan ID still referencing one Dependency edge.

    Args:
        db: Database session.
        dependency_id: Canonical edge to inspect.

    Returns:
        Referencing plan IDs in ascending order.
    """
    result = await db.execute(
        select(ReadingPlanDependency.plan_id)
        .where(ReadingPlanDependency.dependency_id == dependency_id)
        .order_by(ReadingPlanDependency.plan_id)
    )
    return list(result.scalars().all())


async def plans_containing_issue(
    db: AsyncSession, *, issue_id: int
) -> list[int]:
    """Return every plan ID whose membership includes one Issue.

    Args:
        db: Database session.
        issue_id: Canonical Issue to inspect.

    Returns:
        Containing plan IDs in ascending order.
    """
    result = await db.execute(
        select(ReadingPlanIssue.plan_id)
        .where(ReadingPlanIssue.issue_id == issue_id)
        .distinct()
        .order_by(ReadingPlanIssue.plan_id)
    )
    return list(result.scalars().all())


async def list_plan_sources(
    db: AsyncSession, *, plan_id: int
) -> list[ReadingPlanSource]:
    """Return every preserved source snapshot for one plan.

    Args:
        db: Database session.
        plan_id: Plan to inspect.

    Returns:
        Source snapshots ordered by ID.
    """
    result = await db.execute(
        select(ReadingPlanSource)
        .where(ReadingPlanSource.plan_id == plan_id)
        .order_by(ReadingPlanSource.id)
    )
    return list(result.scalars().all())


async def list_plan_source_placements(
    db: AsyncSession, *, plan_id: int
) -> list[ReadingPlanSourcePlacement]:
    """Return every preserved source placement for one plan.

    Args:
        db: Database session.
        plan_id: Plan to inspect.

    Returns:
        Placement rows ordered by ID.
    """
    result = await db.execute(
        select(ReadingPlanSourcePlacement)
        .where(ReadingPlanSourcePlacement.plan_id == plan_id)
        .order_by(ReadingPlanSourcePlacement.id)
    )
    return list(result.scalars().all())


async def count_distinct_read_issues(
    db: AsyncSession, *, plan_id: int
) -> int:
    """Count distinct member Issues of one plan whose global state is read.

    Issue read state is canonical and global: reading an Issue advances every
    overlapping plan at once.

    Args:
        db: Database session.
        plan_id: Plan to measure.

    Returns:
        Number of distinct member Issues with status ``"read"``.
    """
    result = await db.execute(
        select(func.count(func.distinct(ReadingPlanIssue.issue_id)))
        .join(Issue, Issue.id == ReadingPlanIssue.issue_id)
        .where(ReadingPlanIssue.plan_id == plan_id, Issue.status == "read")
    )
    return int(result.scalar_one())


async def list_plan_issue_occurrences_by_issue(
    db: AsyncSession, *, plan_id: int
) -> list[ReadingPlanIssue]:
    """Return every membership row for one plan in deterministic audit order.

    Ordering by canonical Issue, then display position, then occurrence ID makes
    the deterministic duplicate-collapse rule reproducible without relying on
    physical row order.

    Args:
        db: Database session.
        plan_id: Plan to inspect.

    Returns:
        Membership rows ordered by issue ID, display position, occurrence ID.
    """
    result = await db.execute(
        select(ReadingPlanIssue)
        .where(ReadingPlanIssue.plan_id == plan_id)
        .order_by(
            ReadingPlanIssue.issue_id,
            ReadingPlanIssue.display_position,
            ReadingPlanIssue.occurrence_id,
        )
    )
    return list(result.scalars().all())


async def list_plan_ids_with_membership(db: AsyncSession) -> list[int]:
    """Return every plan ID that owns at least one membership row.

    Args:
        db: Database session.

    Returns:
        Distinct plan IDs in ascending order.
    """
    result = await db.execute(
        select(ReadingPlanIssue.plan_id).distinct().order_by(ReadingPlanIssue.plan_id)
    )
    return list(result.scalars().all())


async def prune_redundant_plan_source_placements(
    db: AsyncSession, *, plan_id: int, occurrence_map: dict[str, str]
) -> None:
    """Drop provenance that a collapse would make indistinguishable.

    Re-pointing a collapsed occurrence's placements onto its survivor can
    collide with provenance the survivor already owns, and the unique placement
    key forbids the rewrite. Within each post-collapse
    ``(occurrence, source, position)`` group the lowest-ID placement survives, so
    collapsing membership never discards an observation another row already
    duplicates exactly.

    Args:
        db: Database session.
        plan_id: Plan whose placements are pruned.
        occurrence_map: Collapsed occurrence ID to surviving occurrence ID.
    """
    result = await db.execute(
        select(ReadingPlanSourcePlacement)
        .where(ReadingPlanSourcePlacement.plan_id == plan_id)
        .order_by(ReadingPlanSourcePlacement.id)
    )
    seen: set[tuple[str, int, int | None]] = set()
    redundant: list[int] = []
    for placement in result.scalars():
        target = occurrence_map.get(
            placement.occurrence_id, placement.occurrence_id
        )
        key = (target, placement.plan_source_id, placement.source_position)
        if key in seen:
            redundant.append(placement.id)
            continue
        seen.add(key)
    if not redundant:
        return
    await db.execute(
        delete(ReadingPlanSourcePlacement).where(
            ReadingPlanSourcePlacement.id.in_(redundant)
        )
    )
    await db.flush()


async def repoint_plan_source_placements(
    db: AsyncSession, *, plan_id: int, occurrence_map: dict[str, str]
) -> None:
    """Re-point source placements from collapsed occurrences to their survivor.

    A placement whose re-pointed row would collide with a placement the
    survivor already owns is left untouched so the caller can decide to drop it;
    collapsing membership must never silently discard an existing observation.

    Args:
        db: Database session.
        plan_id: Plan whose placements are re-pointed.
        occurrence_map: Collapsed occurrence ID to surviving occurrence ID.
    """
    if not occurrence_map:
        return
    await db.execute(
        update(ReadingPlanSourcePlacement)
        .where(
            ReadingPlanSourcePlacement.plan_id == plan_id,
            ReadingPlanSourcePlacement.occurrence_id.in_(occurrence_map),
        )
        .values(
            occurrence_id=case(
                occurrence_map,
                value=ReadingPlanSourcePlacement.occurrence_id,
            )
        )
    )
    await db.flush()


async def delete_plan_source_placements_for_occurrences(
    db: AsyncSession, *, plan_id: int, occurrence_ids: list[str]
) -> None:
    """Delete source placements that still reference collapsed occurrences.

    Args:
        db: Database session.
        plan_id: Plan whose placements are pruned.
        occurrence_ids: Occurrence IDs that no longer exist as membership rows.
    """
    if not occurrence_ids:
        return
    await db.execute(
        delete(ReadingPlanSourcePlacement).where(
            ReadingPlanSourcePlacement.plan_id == plan_id,
            ReadingPlanSourcePlacement.occurrence_id.in_(occurrence_ids),
        )
    )
    await db.flush()


async def delete_plan_issue_occurrences(
    db: AsyncSession, *, plan_id: int, occurrence_ids: list[str]
) -> None:
    """Delete the collapsed membership rows for one plan.

    Args:
        db: Database session.
        plan_id: Plan whose membership rows are collapsed.
        occurrence_ids: Occurrence IDs to remove.
    """
    if not occurrence_ids:
        return
    await db.execute(
        delete(ReadingPlanIssue).where(
            ReadingPlanIssue.plan_id == plan_id,
            ReadingPlanIssue.occurrence_id.in_(occurrence_ids),
        )
    )
    await db.flush()
