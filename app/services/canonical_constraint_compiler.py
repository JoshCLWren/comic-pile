"""Compile authoring-level ContinuityRules into canonical Dependency edges (#2553).

The Dependency edge is the runtime authority for Roll blocking; the
ContinuityRule is the human-authoring record. This module keeps the two in sync
inside the author's write transaction so rule authoring keeps its intended
behavior after ContinuityRule leaves the Roll eligibility path.

Strict-sequential adjacent plan edges are intentionally NOT compiled here;
that inference needs the Wild Hunt exception decision (Phase B of #2553).
"""

from __future__ import annotations

from sqlalchemy import delete, select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.continuity_rule import ContinuityRule
from app.models.dependency import Dependency

EDGE_NOTE_PREFIX = "canonical:rule:"


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


async def compile_rule_edges(db: AsyncSession, rule: ContinuityRule) -> None:
    """Insert canonical Dependency edges for a rule.

    Must be called after the rule is flushed (so rule.id exists) and before
    the author's transaction commits. Existing edges are shared, never
    duplicated.
    """
    for source_id, target_id in rule_edge_pairs(rule):
        await db.execute(
            pg_insert(Dependency)
            .values(
                source_issue_id=source_id,
                target_issue_id=target_id,
                note=f"{EDGE_NOTE_PREFIX}{rule.id}",
            )
            .on_conflict_do_nothing(index_elements=["source_issue_id", "target_issue_id"])
        )


async def _pair_has_other_rule(
    db: AsyncSession,
    *,
    user_id: int,
    pair: tuple[int, int],
    exclude_rule_id: int,
) -> bool:
    """Whether another of the user's rules still compiles to the pair."""
    rules = (
        (
            await db.execute(
                select(ContinuityRule).where(
                    ContinuityRule.user_id == user_id,
                    ContinuityRule.id != exclude_rule_id,
                    ContinuityRule.satisfaction_type.in_(
                        ("item_read", "checkpoint", "converged")
                    ),
                )
            )
        )
        .scalars()
        .all()
    )
    return any(pair in rule_edge_pairs(other) for other in rules)


async def retire_rule_edges(
    db: AsyncSession,
    *,
    user_id: int,
    pairs: list[tuple[int, int]],
    exclude_rule_id: int,
) -> None:
    """Delete rule-compiled edges for retired pairs unless still intended.

    An edge is removed only when no other rule of the user compiles to the
    same pair and the edge is a rule-compiled edge (never a standalone
    reader-created Dependency).
    """
    for source_id, target_id in set(pairs):
        if await _pair_has_other_rule(
            db, user_id=user_id, pair=(source_id, target_id), exclude_rule_id=exclude_rule_id
        ):
            continue
        await db.execute(
            delete(Dependency).where(
                Dependency.source_issue_id == source_id,
                Dependency.target_issue_id == target_id,
                Dependency.note.like(f"{EDGE_NOTE_PREFIX}%"),
            )
        )
