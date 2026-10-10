"""Persistence for canonical hard constraints compiled at authoring boundaries."""

from sqlalchemy import delete, or_, select, text, tuple_, update
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.continuity_plan import ContinuityPlan
from app.models.continuity_rule import ContinuityRule
from app.models.dependency import Dependency
from app.models.issue import Issue
from app.models.reading_plan_membership import ReadingPlanDependency
from app.models.thread import Thread

COMPILED_NOTE = "canonical:compiled-hard-constraint"
COMPILED_EXPLANATION = "Compiled hard constraint"


async def authoring_constraints(
    db: AsyncSession, user_id: int
) -> tuple[list[ContinuityRule], list[ContinuityPlan]]:
    """Load compatibility authoring records, never used by Roll reads."""
    rules = list(
        (await db.scalars(select(ContinuityRule).where(ContinuityRule.user_id == user_id))).all()
    )
    plans = list(
        (await db.scalars(select(ContinuityPlan).where(ContinuityPlan.user_id == user_id))).all()
    )
    return rules, plans


async def owned_issue_positions(
    db: AsyncSession, user_id: int, issue_ids: set[int]
) -> dict[int, tuple[int, int]]:
    """Return owned Issue thread/position pairs for compilation validation."""
    positions: dict[int, tuple[int, int]] = {}
    ids = sorted(issue_ids)
    for offset in range(0, len(ids), 10000):
        rows = await db.execute(
            select(Issue.id, Issue.thread_id, Issue.position)
            .join(Thread, Thread.id == Issue.thread_id)
            .where(Thread.user_id == user_id, Issue.id.in_(ids[offset : offset + 10000]))
        )
        positions.update(
            {issue_id: (thread_id, position) for issue_id, thread_id, position in rows}
        )
    return positions


async def persist_compiled_constraints(
    db: AsyncSession,
    user_id: int,
    pairs: set[tuple[int, int]],
    plan_pairs: dict[int, set[tuple[int, int]]],
    rules: list[ContinuityRule],
) -> int:
    """Converge one user's canonical rows and generated plan links transactionally.

    Existing standalone edges keep their provenance. Generated edges are removed
    only when no authoring constraint or independent plan link still references
    them. The caller owns the transaction and blocked-state refresh.
    """
    deps = list(
        (
            await db.scalars(
                select(Dependency)
                .join(Issue, Issue.id == Dependency.target_issue_id)
                .join(Thread, Thread.id == Issue.thread_id)
                .where(Thread.user_id == user_id)
                .where(or_(Dependency.note.is_(None), ~Dependency.note.like("cbl-order:%")))
            )
        ).all()
    )
    by_pair = {(dep.source_issue_id, dep.target_issue_id): dep for dep in deps}
    ids = sorted(pairs)
    for offset in range(0, len(ids), 5000):
        collisions = list(
            (
                await db.scalars(
                    select(Dependency).where(
                        tuple_(Dependency.source_issue_id, Dependency.target_issue_id).in_(
                            ids[offset : offset + 5000]
                        ),
                        Dependency.note.like("cbl-order:%"),
                    )
                )
            ).all()
        )
        deps.extend(collisions)
        by_pair.update({(dep.source_issue_id, dep.target_issue_id): dep for dep in collisions})
    inserted = 0
    # An older migration fixture may still have the reverse compatibility trigger.
    # Preserve exact authoring metadata if that trigger attempts to rewrite it.
    snapshots = [
        {
            "id": rule.id,
            "note": rule.note,
            "legacy_dependency_id": rule.legacy_dependency_id,
            "satisfaction_type": rule.satisfaction_type,
            "checkpoint_issue_id": rule.checkpoint_issue_id,
            "convergence_targets": rule.convergence_targets,
            "updated_at": rule.updated_at,
        }
        for rule in rules
    ]
    for source, target in sorted(pairs):
        existing = by_pair.get((source, target))
        if existing is not None and (existing.note or "").startswith("cbl-order:"):
            # Promotion requires independent hard authoring evidence, not a mirror.
            existing.note = COMPILED_NOTE
            await db.flush()
        elif existing is None:
            dep_id = await db.scalar(
                insert(Dependency)
                .values(source_issue_id=source, target_issue_id=target, note=COMPILED_NOTE)
                .on_conflict_do_nothing(
                    index_elements=[Dependency.source_issue_id, Dependency.target_issue_id]
                )
                .returning(Dependency.id)
            )
            if dep_id is not None:
                inserted += 1
            existing = await db.scalar(
                select(Dependency).where(
                    Dependency.source_issue_id == source, Dependency.target_issue_id == target
                )
            )
            assert existing is not None
            by_pair[(source, target)] = existing
    # Restore only the loaded legacy records. No rule becomes execution authority:
    # all eligibility reads below this boundary use the persisted Dependency set.
    reverse_bridge = await db.scalar(
        text("""
        SELECT EXISTS (
            SELECT 1 FROM pg_trigger
            WHERE tgrelid = 'dependencies'::regclass AND NOT tgisinternal
        )
    """)
    )
    for snapshot in snapshots if reverse_bridge else []:
        rule_id = snapshot["id"]
        values = {key: value for key, value in snapshot.items() if key != "id"}
        await db.execute(
            update(ContinuityRule).where(ContinuityRule.id == rule_id).values(**values)
        )

    plan_ids = list(plan_pairs)
    if plan_ids:
        await db.execute(
            delete(ReadingPlanDependency).where(
                ReadingPlanDependency.plan_id.in_(plan_ids),
                ReadingPlanDependency.explanation == COMPILED_EXPLANATION,
            )
        )
    for plan_id, edges in plan_pairs.items():
        for pair in sorted(edges):
            await db.execute(
                insert(ReadingPlanDependency)
                .values(
                    plan_id=plan_id,
                    dependency_id=by_pair[pair].id,
                    explanation=COMPILED_EXPLANATION,
                )
                .on_conflict_do_nothing()
            )
    await db.flush()
    for dep in deps:
        pair = (dep.source_issue_id, dep.target_issue_id)
        if dep.note == COMPILED_NOTE and pair not in pairs:
            referenced = await db.scalar(
                select(ReadingPlanDependency.plan_id)
                .where(ReadingPlanDependency.dependency_id == dep.id)
                .limit(1)
            )
            if referenced is None:
                await db.delete(dep)
    await db.flush()
    return inserted


async def legacy_restore_conflicts(
    db: AsyncSession, plan_id: int, edges: list[tuple[int, int]]
) -> list[int]:
    """Find edges a legacy rollback cannot restore without erasing hard intent."""
    conflicts: list[int] = []
    for source, target in edges:
        dep = await db.scalar(
            select(Dependency).where(
                Dependency.source_issue_id == source, Dependency.target_issue_id == target
            )
        )
        if dep is None:
            continue
        links = list(
            (
                await db.scalars(
                    select(ReadingPlanDependency.plan_id).where(
                        ReadingPlanDependency.dependency_id == dep.id
                    )
                )
            ).all()
        )
        standalone = await db.scalar(
            select(ContinuityRule.id)
            .where(
                ContinuityRule.source_type == "issue",
                ContinuityRule.source_id == source,
                ContinuityRule.target_type == "issue",
                ContinuityRule.target_id == target,
                or_(
                    ContinuityRule.note.is_(None),
                    ContinuityRule.note != f"continuity-plan:{plan_id}",
                ),
                (ContinuityRule.note.is_(None) | (ContinuityRule.note != COMPILED_NOTE)),
                or_(ContinuityRule.note.is_(None), ~ContinuityRule.note.like("cbl-order:%")),
            )
            .limit(1)
        )
        if dep.note != COMPILED_NOTE or links != [plan_id] or standalone is not None:
            conflicts.append(dep.id)
    return conflicts


async def canonical_dependencies(
    db: AsyncSession, user_id: int, *, limit: int | None = None
) -> list[Dependency]:
    """Read only owned canonical pairs for factual graph consumers."""
    target_issue = Issue.__table__.alias("canonical_target")
    target_thread = Thread.__table__.alias("canonical_target_thread")
    statement = (
        select(Dependency)
        .join(Issue, Issue.id == Dependency.source_issue_id)
        .join(Thread, Thread.id == Issue.thread_id)
        .join(target_issue, target_issue.c.id == Dependency.target_issue_id)
        .join(target_thread, target_thread.c.id == target_issue.c.thread_id)
        .where(Thread.user_id == user_id, target_thread.c.user_id == user_id)
        .where(or_(Dependency.note.is_(None), ~Dependency.note.like("cbl-order:%")))
        .order_by(Dependency.id)
    )
    if limit is not None:
        statement = statement.limit(limit)
    return list((await db.scalars(statement)).all())


async def canonical_frontier_blockers(
    db: AsyncSession, user_id: int, thread_ids: list[int] | None = None
) -> list[tuple[int, int, str, int, str]]:
    """Return target Thread and unread prerequisite details from one authority."""
    source_issue = Issue.__table__.alias("source_issue")
    frontier = Issue.__table__.alias("frontier")
    source_thread = Thread.__table__.alias("source_thread")
    target_thread = Thread.__table__.alias("target_thread")
    statement = (
        select(
            target_thread.c.id,
            source_thread.c.id,
            source_thread.c.title,
            source_issue.c.id,
            source_issue.c.issue_number,
        )
        .select_from(target_thread)
        .join(frontier, frontier.c.id == target_thread.c.next_unread_issue_id)
        .join(Dependency, Dependency.target_issue_id == frontier.c.id)
        .join(source_issue, source_issue.c.id == Dependency.source_issue_id)
        .join(source_thread, source_thread.c.id == source_issue.c.thread_id)
        .where(target_thread.c.user_id == user_id, source_thread.c.user_id == user_id)
        .where(frontier.c.thread_id == target_thread.c.id)
        .where(source_issue.c.status != "read")
        .where(or_(Dependency.note.is_(None), ~Dependency.note.like("cbl-order:%")))
        .order_by(
            target_thread.c.id, source_thread.c.id, source_issue.c.position, source_issue.c.id
        )
    )
    if thread_ids is not None:
        if not thread_ids:
            return []
        statement = statement.where(target_thread.c.id.in_(thread_ids))
    rows = await db.execute(statement)
    return [(target, source, title, issue, number) for target, source, title, issue, number in rows]
