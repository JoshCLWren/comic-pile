"""Compile authoring-level ContinuityRules into canonical Dependency edges (#2553).

The Dependency edge is the runtime authority for Roll blocking; the
ContinuityRule is the human-authoring record. This module keeps the two in sync
inside the author's write transaction so rule authoring keeps its intended
behavior after ContinuityRule leaves the Roll eligibility path.

Live Reading Plan writes no longer invent list-adjacency or thread-entry
edges; ``continuity_plan_writer`` retains existing plan-owned ``item_read``
pairs and compiles only explicit checkpoints/convergence. Held migration
scripts may still select pairs via ``strict_plan_constraints``. This module
does not invent adjacency.
"""

from __future__ import annotations

from collections.abc import Collection

from sqlalchemy import delete, or_, select, tuple_, update
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.sql.elements import ColumnElement

from app.models.continuity_rule import ContinuityRule
from app.models.dependency import Dependency
from app.models.reading_plan_membership import ReadingPlanDependency

EDGE_NOTE_PREFIX = "canonical:rule:"
BACKFILL_EDGE_NOTE_PREFIX = "canonical:rule-backfill:"


def rule_compiled_note_filter() -> ColumnElement[bool]:
    """Match live write-path notes and migration-backfilled notes.

    The two prefixes stay distinct so Alembic downgrade can delete only the
    rows the cutover inserted, while retirement still finds both.
    """
    return or_(
        Dependency.note.like(f"{EDGE_NOTE_PREFIX}%"),
        Dependency.note.like(f"{BACKFILL_EDGE_NOTE_PREFIX}%"),
    )


def rule_edge_pairs(rule: ContinuityRule) -> list[tuple[int, int]]:
    """Return the canonical (source_issue_id, target_issue_id) pairs a rule compiles to.

    Empty for rule forms with no canonical runtime meaning (crossover
    endpoints, member-list satisfactions). Those rules are kept as data but
    never block Roll.
    """
    if rule.satisfaction_type in ("item_read", "checkpoint"):
        if rule.source_type == "issue" and rule.target_type == "issue":
            source_id = rule.checkpoint_issue_id or rule.source_id
            return [(source_id, rule.target_id)]
        return []
    if rule.satisfaction_type == "converged" and rule.target_type == "issue":
        pairs: list[tuple[int, int]] = []
        for target_info in rule.convergence_targets or []:
            if not isinstance(target_info, dict):
                continue
            if str(target_info.get("type")) != "issue":
                continue
            prereq_id = int(target_info["id"])
            if prereq_id != rule.target_id:
                pairs.append((prereq_id, rule.target_id))
        return pairs
    return []


def validate_rule_compiles(rule: ContinuityRule) -> None:
    """Raise ValueError if a rule would not fully compile to canonical edges.

    Crossover and member-based rules are accepted by the schema but the
    canonical compiler generates no edges for them; saving such a rule
    would silently create a constraint Roll never enforces (#2553 P1).

    Also rejects converged rules with non-issue prerequisites: the compiler
    silently skips those, losing part of the constraint.
    """
    if rule.satisfaction_type == "converged":
        non_issue = [
            t for t in (rule.convergence_targets or [])
            if isinstance(t, dict) and str(t.get("type")) != "issue"
        ]
        if non_issue:
            raise ValueError(
                f"Converged rule has {len(non_issue)} non-issue prerequisite(s); "
                "all convergence targets must be issues to compile to canonical edges"
            )
    if not rule_edge_pairs(rule):
        raise ValueError(
            f"Rule with satisfaction_type={rule.satisfaction_type}, "
            f"source_type={rule.source_type}, target_type={rule.target_type} "
            "does not compile to canonical edges and would never block Roll"
        )


async def compile_rule_edges(
    db: AsyncSession,
    rule: ContinuityRule,
    *,
    plan_id: int | None = None,
    promote_cbl_occupants: bool = False,
) -> None:
    """Insert canonical Dependency edges for a rule.

    Must be called after the rule is flushed (so rule.id exists) and before
    the author's transaction commits. Existing edges are shared, never
    duplicated; notes are refreshed to the compiling rule.

    Raises ValueError if a historical cbl-order row occupies a pair the rule
    must compile and ``promote_cbl_occupants`` is false: ON CONFLICT DO UPDATE
    would silently leave the inert row, and the hard constraint would never
    block Roll. Strict-plan compilation passes ``promote_cbl_occupants=True``
    so an inferred thread-entry gate can promote *that pair only* from inert
    CBL materialization into a canonical blocker. Unrelated ``cbl-order:%``
    rows stay inert.

    When plan_id is given, also links each compiled edge through
    reading_plan_dependencies for provenance (#2553 P2).
    """
    pairs = rule_edge_pairs(rule)
    if pairs:
        # Check for cbl-order collisions before inserting.
        cbl_occupants = (
            (
                await db.execute(
                    select(Dependency.source_issue_id, Dependency.target_issue_id).where(
                        tuple_(Dependency.source_issue_id, Dependency.target_issue_id).in_(
                            pairs
                        ),
                        Dependency.note.like("cbl-order:%"),
                    )
                )
            )
            .all()
        )
        if cbl_occupants and not promote_cbl_occupants:
            raise ValueError(
                f"Rule {rule.id} collides with historical cbl-order rows on "
                f"{len(cbl_occupants)} pair(s); resolve the overlap before saving"
            )
        if cbl_occupants and promote_cbl_occupants:
            await db.execute(
                update(Dependency)
                .where(
                    tuple_(Dependency.source_issue_id, Dependency.target_issue_id).in_(
                        list(cbl_occupants)
                    ),
                    Dependency.note.like("cbl-order:%"),
                )
                .values(note=f"{EDGE_NOTE_PREFIX}{rule.id}")
            )
    for source_id, target_id in pairs:
        result = await db.execute(
            pg_insert(Dependency)
            .values(
                source_issue_id=source_id,
                target_issue_id=target_id,
                note=f"{EDGE_NOTE_PREFIX}{rule.id}",
            )
            .on_conflict_do_update(
                index_elements=["source_issue_id", "target_issue_id"],
                set_={"note": f"{EDGE_NOTE_PREFIX}{rule.id}"},
                # Never overwrite a standalone reader-created edge's note;
                # only refresh notes on previously rule-compiled edges,
                # including rows the cutover backfill inserted.
                where=rule_compiled_note_filter(),
            )
            .returning(Dependency.id)
        )
        # scalar_one_or_none: the WHERE clause may skip the update for
        # standalone edges, in which case no row is returned. Fall back to
        # a lookup so provenance linking still works.
        dep_id = result.scalar_one_or_none()
        if dep_id is None and plan_id is not None:
            dep_id = (
                await db.execute(
                    select(Dependency.id).where(
                        Dependency.source_issue_id == source_id,
                        Dependency.target_issue_id == target_id,
                    )
                )
            ).scalar_one_or_none()
        if plan_id is not None and dep_id is not None:
            # Link the edge to the plan for provenance. ON CONFLICT DO NOTHING
            # keeps it idempotent across re-saves.
            await db.execute(
                pg_insert(ReadingPlanDependency)
                .values(
                    plan_id=plan_id,
                    dependency_id=dep_id,
                    explanation=f"{EDGE_NOTE_PREFIX}{rule.id}",
                )
                .on_conflict_do_nothing(
                    index_elements=["plan_id", "dependency_id"]
                )
            )


async def _pair_has_other_rule(
    db: AsyncSession,
    *,
    user_id: int,
    pair: tuple[int, int],
    exclude_rule_ids: Collection[int],
) -> bool:
    """Whether another of the user's rules still compiles to the pair."""
    query = select(ContinuityRule).where(
        ContinuityRule.user_id == user_id,
        ContinuityRule.satisfaction_type.in_(
            ("item_read", "checkpoint", "converged")
        ),
    )
    if exclude_rule_ids:
        query = query.where(ContinuityRule.id.not_in(list(exclude_rule_ids)))
    rules = ((await db.execute(query)).scalars().all())
    return any(pair in rule_edge_pairs(other) for other in rules)


async def retire_rule_edges(
    db: AsyncSession,
    *,
    user_id: int,
    pairs: list[tuple[int, int]],
    exclude_rule_id: int | None = None,
    exclude_rule_ids: Collection[int] | None = None,
) -> None:
    """Delete rule-compiled edges for retired pairs unless still intended.

    An edge is removed only when no other rule of the user compiles to the
    same pair and the edge is a rule-compiled edge (never a standalone
    reader-created Dependency). Backfilled ``canonical:rule-backfill:`` notes
    are included so plan rollback and rule deletion retire the cutover rows.
    """
    excluded = set(exclude_rule_ids or ())
    if exclude_rule_id is not None:
        excluded.add(exclude_rule_id)
    for source_id, target_id in set(pairs):
        if await _pair_has_other_rule(
            db, user_id=user_id, pair=(source_id, target_id), exclude_rule_ids=excluded
        ):
            continue
        await db.execute(
            delete(Dependency).where(
                Dependency.source_issue_id == source_id,
                Dependency.target_issue_id == target_id,
                rule_compiled_note_filter(),
            )
        )
