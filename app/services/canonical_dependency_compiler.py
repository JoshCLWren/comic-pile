"""Canonical issue-to-issue Dependency compilation for hard ContinuityRule semantics.

``docs/READING_GRAPH_ADR.md`` section 2 makes ``Dependency`` the only executable hard
edge and section 9 makes ``ContinuityRule`` transitional. Roll eligibility is computed
from canonical Dependency rows alone (see ``comic_pile/dependencies.py``), so every hard
rule that this module reduces must also be persisted as a real edge. Otherwise the rule
keeps promising a block - a strict Reading Plan still says later material stays out of Roll -
while Roll happily serves the issue.

The reductions are exactly the ones the frozen persistence design defines
(``docs/READING_GRAPH_PERSISTENCE_DESIGN.md`` section 4):

- ``item_read`` issue A -> issue B becomes ``Dependency(A, B)``;
- a checkpoint becomes ``Dependency(checkpoint_issue_id, target)``;
- ``converged`` becomes one incoming edge per issue gate target, never the stored
  self-loop.

``all_members_read`` and ``selected_members_read`` have no production rows and no defined
reduction, so they are deliberately not converted.

Ownership is never encoded in a Dependency note (ADR section 6): one executable edge may be
shared by many plans and by standalone prerequisites. A rule-derived edge is removed again
only once no surviving hard rule reproduces the pair and no Reading Plan still links it.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from sqlalchemy.ext.asyncio import AsyncSession

from app.repositories import (
    continuity_repository,
    dependency_repository,
    reading_plan_repository,
)

if TYPE_CHECKING:
    from app.models.continuity_rule import ContinuityRule

Edge = tuple[int, int]


def _coerce_issue_id(value: object) -> int | None:
    """Return a positive integer issue identifier, or None for anything else."""
    if isinstance(value, bool):
        return None
    if isinstance(value, int):
        return value if value > 0 else None
    if isinstance(value, str) and value.isdigit():
        parsed = int(value)
        return parsed if parsed > 0 else None
    return None


def _edge(source_issue_id: int | None, target_issue_id: int | None) -> list[Edge]:
    """Return one canonical edge, rejecting self-loops and unknown endpoints."""
    if source_issue_id is None or target_issue_id is None:
        return []
    if source_issue_id == target_issue_id:
        return []
    return [(source_issue_id, target_issue_id)]


def canonical_edges_for_semantics(
    *,
    source_type: str,
    source_id: int,
    target_type: str,
    target_id: int,
    satisfaction_type: str,
    checkpoint_issue_id: int | None = None,
    convergence_targets: list[dict[str, object]] | None = None,
) -> list[Edge]:
    """Reduce one rule's hard semantics to canonical issue-to-issue edges.

    Args:
        source_type: Stored source node type.
        source_id: Stored source node identifier.
        target_type: Stored target node type.
        target_id: Stored target node identifier.
        satisfaction_type: Stored satisfaction policy.
        checkpoint_issue_id: Satisfaction Issue for checkpoint semantics.
        convergence_targets: Gate targets for converged semantics.

    Returns:
        Canonical edges in stable order. Empty for non-production compatibility
        semantics and for any rule whose target is not an Issue.
    """
    if target_type != "issue":
        return []
    if satisfaction_type == "item_read" and source_type == "issue":
        return _edge(source_id, target_id)
    if satisfaction_type == "checkpoint":
        return _edge(checkpoint_issue_id, target_id)
    if satisfaction_type != "converged":
        return []
    edges: list[Edge] = []
    for entry in convergence_targets or []:
        if not isinstance(entry, dict) or str(entry.get("type")) != "issue":
            continue
        edges.extend(_edge(_coerce_issue_id(entry.get("id")), target_id))
    return edges


def canonical_edges_for_rule(rule: ContinuityRule) -> list[Edge]:
    """Reduce one persisted ContinuityRule row to canonical issue-to-issue edges.

    Args:
        rule: Persisted rule to reduce.

    Returns:
        Canonical edges implied by the rule's current hard semantics.
    """
    return canonical_edges_for_semantics(
        source_type=rule.source_type,
        source_id=rule.source_id,
        target_type=rule.target_type,
        target_id=rule.target_id,
        satisfaction_type=rule.satisfaction_type,
        checkpoint_issue_id=rule.checkpoint_issue_id,
        convergence_targets=list(rule.convergence_targets or []),
    )


def _dedupe(pairs: list[Edge]) -> list[Edge]:
    """Return pairs in first-seen order without duplicates."""
    seen: set[Edge] = set()
    ordered: list[Edge] = []
    for pair in pairs:
        if pair in seen:
            continue
        seen.add(pair)
        ordered.append(pair)
    return ordered


async def _owned_pairs(db: AsyncSession, user_id: int, pairs: list[Edge]) -> list[Edge]:
    """Keep only pairs whose two endpoints are Issues owned by one user."""
    if not pairs:
        return []
    endpoint_ids = sorted({issue_id for pair in pairs for issue_id in pair})
    owned = await continuity_repository.owned_issue_ids_for_user(db, user_id, endpoint_ids)
    return [
        (source_id, target_id)
        for source_id, target_id in _dedupe(pairs)
        if source_id in owned and target_id in owned
    ]


async def ensure_canonical_dependencies(
    db: AsyncSession,
    *,
    user_id: int,
    pairs: list[Edge],
    note: str | None = None,
) -> list[int]:
    """Persist any missing canonical edge for one user's hard semantics.

    An already materialized edge is reused untouched: the executable edge exists
    once no matter how many rules or plans require it.

    Args:
        db: Database session owned by the calling service's transaction.
        user_id: Owner of both endpoints.
        pairs: Candidate issue-to-issue edges.
        note: Optional reader-facing explanation applied only to newly created edges.

    Returns:
        Dependency IDs for every ensured edge, in candidate order.
    """
    wanted = await _owned_pairs(db, user_id, _dedupe(pairs))
    if not wanted:
        return []
    ensured: list[int] = []
    for source_issue_id, target_issue_id in wanted:
        existing = await dependency_repository.get_dependency_by_ids(
            db, source_issue_id, target_issue_id
        )
        if existing is not None:
            ensured.append(existing.id)
            continue
        dependency = await dependency_repository.create_dependency(
            db,
            source_issue_id,
            target_issue_id,
            note=note[:255] if note else None,
        )
        await db.flush()
        ensured.append(dependency.id)
    return ensured


async def _rule_implied_edges(db: AsyncSession, user_id: int) -> set[Edge]:
    """Return every canonical edge one user's surviving hard rules still require."""
    rules = await continuity_repository.rules_for_user(db, user_id)
    implied: set[Edge] = set()
    for rule in rules:
        implied.update(canonical_edges_for_rule(rule))
    return implied


async def retire_canonical_dependencies(
    db: AsyncSession,
    *,
    user_id: int,
    pairs: list[Edge],
) -> list[int]:
    """Remove rule-derived edges that nothing else justifies anymore.

    An edge survives while any surviving hard rule reproduces the same pair or any
    Reading Plan still links it, so shared and plan-owned edges are never dropped
    from under another owner.

    Args:
        db: Database session owned by the calling service's transaction.
        user_id: Owner of the rule that no longer requires these edges.
        pairs: Edges the removed rule used to require.

    Returns:
        Dependency IDs actually deleted.
    """
    candidates = _dedupe(pairs)
    if not candidates:
        return []
    implied = await _rule_implied_edges(db, user_id)
    removed: list[int] = []
    for source_issue_id, target_issue_id in candidates:
        if (source_issue_id, target_issue_id) in implied:
            continue
        dependency = await dependency_repository.get_dependency_by_ids(
            db, source_issue_id, target_issue_id
        )
        if dependency is None:
            continue
        dependency_id = dependency.id
        referencing = await reading_plan_repository.plans_referencing_dependency(
            db, dependency_id=dependency_id
        )
        if referencing:
            continue
        await dependency_repository.delete_dependency(db, dependency_id)
        removed.append(dependency_id)
    return removed


async def replace_plan_dependency_links(
    db: AsyncSession,
    *,
    plan_id: int,
    dependency_ids: list[int],
) -> list[Edge]:
    """Point one plan's normalized provenance links at exactly these canonical edges.

    Args:
        db: Database session owned by the calling service's transaction.
        plan_id: Plan whose links are replaced.
        dependency_ids: Canonical edges the plan's current semantics require.

    Returns:
        Pairs whose plan link was removed, so the caller can retire them.
    """
    current = await reading_plan_repository.list_plan_dependency_edges(db, plan_id=plan_id)
    current_pairs = {
        (edge.source_issue_id, edge.target_issue_id): edge.id for edge in current
    }
    wanted = sorted(set(dependency_ids))
    wanted_set = set(wanted)
    dropped: list[Edge] = []
    for pair, dependency_id in current_pairs.items():
        if dependency_id in wanted_set:
            continue
        await reading_plan_repository.unlink_plan_dependency(
            db, plan_id=plan_id, dependency_id=dependency_id
        )
        dropped.append(pair)
    for dependency_id in wanted:
        if dependency_id in current_pairs.values():
            continue
        await reading_plan_repository.link_plan_dependency(
            db, plan_id=plan_id, dependency_id=dependency_id
        )
    return dropped


async def sync_plan_canonical_dependencies(
    db: AsyncSession,
    *,
    user_id: int,
    plan_id: int,
    pairs: list[Edge],
) -> list[int]:
    """Compile one plan's hard semantics into canonical edges and plan links.

    This is the strict Reading Plan cutover requirement: an explicit hard requirement
    is persisted through the canonical Dependency runtime that Roll reads, and the
    plan references the resulting edges without taking single ownership of them.

    Args:
        db: Database session owned by the calling service's transaction.
        user_id: Owner of the plan and of every edge endpoint.
        plan_id: Plan being written.
        pairs: Canonical edges implied by the plan's current compiled semantics.

    Returns:
        Dependency IDs the plan now references.
    """
    ensured = await ensure_canonical_dependencies(db, user_id=user_id, pairs=pairs)
    dropped = await replace_plan_dependency_links(
        db, plan_id=plan_id, dependency_ids=ensured
    )
    if dropped:
        await retire_canonical_dependencies(db, user_id=user_id, pairs=dropped)
    return ensured