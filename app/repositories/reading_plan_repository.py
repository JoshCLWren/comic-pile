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

from dataclasses import dataclass

from sqlalchemy import delete, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.continuity_plan import ContinuityPlan
from app.models.dependency import Dependency
from app.models.issue import Issue
from app.models.reading_plan_membership import (
    ReadingPlanDependency,
    ReadingPlanIssue,
    ReadingPlanSource,
    ReadingPlanSourcePlacement,
)
from app.models.thread import Thread

#: Historical CBL materialization notes are provenance, not hard blockers.
_CBL_ORDER_NOTE_PREFIX = "cbl-order:"


@dataclass(frozen=True, slots=True)
class ReadingPlanIssueIdentity:
    """One plan occurrence joined to its canonical Issue and owning Thread."""

    occurrence_id: str
    issue_id: int
    lane_id: str
    display_position: int
    label: str | None
    reader_role: str | None
    reader_optional: bool | None
    is_checkpoint: bool
    source_metadata: dict[str, object] | None
    issue_number: str
    issue_status: str
    thread_id: int
    thread_title: str
    thread_next_unread_issue_id: int | None


@dataclass(frozen=True, slots=True)
class CanonicalIncomingBlocker:
    """One unread canonical Dependency source targeting a plan Issue."""

    target_issue_id: int
    source_issue_id: int
    source_issue_number: str
    source_thread_id: int
    source_thread_title: str


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


async def plans_containing_issue_for_user(
    db: AsyncSession, *, issue_id: int, user_id: int
) -> list[ContinuityPlan]:
    """Return the viewer's own plans whose membership includes one Issue.

    Only plans owned by ``user_id`` are returned: tag inheritance must never
    reveal another user's plan existence through an inheritance source, and a
    global assignment is visible only to users authorized to view its target
    (#3030). The ``uq_reading_plan_issue_once_per_plan`` invariant (#3037)
    guarantees at most one membership row per plan, so each plan contributes
    its tags at most once and no occurrence-level deduplication is needed.

    Args:
        db: Database session.
        issue_id: Canonical Issue to inspect.
        user_id: Owner whose plans are included.

    Returns:
        Owned containing plans in ascending plan ID order.
    """
    result = await db.execute(
        select(ContinuityPlan)
        .join(ReadingPlanIssue, ReadingPlanIssue.plan_id == ContinuityPlan.id)
        .where(
            ReadingPlanIssue.issue_id == issue_id,
            ContinuityPlan.user_id == user_id,
        )
        .order_by(ContinuityPlan.id)
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


async def list_plan_issue_identities(
    db: AsyncSession, *, plan_id: int
) -> list[ReadingPlanIssueIdentity]:
    """Return plan occurrences joined to Issue and Thread display fields.

    Args:
        db: Database session.
        plan_id: Plan to inspect.

    Returns:
        Occurrence rows ordered by lane then display position, each carrying
        the canonical Issue identity used by the reader surface.
    """
    result = await db.execute(
        select(
            ReadingPlanIssue.occurrence_id,
            ReadingPlanIssue.issue_id,
            ReadingPlanIssue.lane_id,
            ReadingPlanIssue.display_position,
            ReadingPlanIssue.label,
            ReadingPlanIssue.reader_role,
            ReadingPlanIssue.reader_optional,
            ReadingPlanIssue.is_checkpoint,
            ReadingPlanIssue.source_metadata_json,
            Issue.issue_number,
            Issue.status,
            Thread.id.label("thread_id"),
            Thread.title.label("thread_title"),
            Thread.next_unread_issue_id.label("thread_next_unread_issue_id"),
        )
        .join(Issue, Issue.id == ReadingPlanIssue.issue_id)
        .join(Thread, Thread.id == Issue.thread_id)
        .where(ReadingPlanIssue.plan_id == plan_id)
        .order_by(ReadingPlanIssue.lane_id, ReadingPlanIssue.display_position)
    )
    rows: list[ReadingPlanIssueIdentity] = []
    for row in result.all():
        source_metadata = row.source_metadata_json
        rows.append(
            ReadingPlanIssueIdentity(
                occurrence_id=row.occurrence_id,
                issue_id=row.issue_id,
                lane_id=row.lane_id,
                display_position=row.display_position,
                label=row.label,
                reader_role=row.reader_role,
                reader_optional=row.reader_optional,
                is_checkpoint=row.is_checkpoint,
                source_metadata=source_metadata if isinstance(source_metadata, dict) else None,
                issue_number=row.issue_number,
                issue_status=row.status,
                thread_id=row.thread_id,
                thread_title=row.thread_title,
                thread_next_unread_issue_id=row.thread_next_unread_issue_id,
            )
        )
    return rows


async def list_canonical_incoming_blockers(
    db: AsyncSession, *, issue_ids: list[int]
) -> list[CanonicalIncomingBlocker]:
    """Return unread canonical Dependency sources targeting the given Issues.

    Historical ``cbl-order:`` materialization notes are excluded: they record
    source order, not hard prerequisites. Genuine Dependency edges remain the
    runtime blocking authority.

    Args:
        db: Database session.
        issue_ids: Target Issue IDs to inspect.

    Returns:
        Incoming blocker rows ordered by target then source Issue ID.
    """
    if not issue_ids:
        return []
    source_issue = Issue.__table__.alias("source_issue")
    source_thread = Thread.__table__.alias("source_thread")
    result = await db.execute(
        select(
            Dependency.target_issue_id,
            source_issue.c.id,
            source_issue.c.issue_number,
            source_thread.c.id,
            source_thread.c.title,
        )
        .join(source_issue, Dependency.source_issue_id == source_issue.c.id)
        .join(source_thread, source_issue.c.thread_id == source_thread.c.id)
        .where(Dependency.target_issue_id.in_(issue_ids))
        .where(source_issue.c.status != "read")
        .where(
            or_(
                Dependency.note.is_(None),
                ~Dependency.note.startswith(_CBL_ORDER_NOTE_PREFIX),
            )
        )
        .order_by(Dependency.target_issue_id, source_issue.c.id)
    )
    return [
        CanonicalIncomingBlocker(
            target_issue_id=row[0],
            source_issue_id=row[1],
            source_issue_number=row[2],
            source_thread_id=row[3],
            source_thread_title=row[4],
        )
        for row in result.all()
    ]
