"""Strict Reading Plan hard-constraint selection (#2553 Phase B).

A strict plan promises that Roll will honor its *selected* hard restrictions.
Josh's definition: only key crossover points block; series can run side by
side between them. It does not compile the entire list order into a chain.
Within a series, issue order applies as usual (``Issue.position`` /
``Thread.next_unread_issue_id``). Same-thread adjacent pairs are never
compiled into Dependencies.

The durable inferred restriction for ``strict_sequential`` is a *crossover
point* / thread-entry gate: the natural first issue of a Thread (minimum
``Issue.position`` on that Thread, whether or not earlier issues appear in
the plan) waits on the nearest preceding required plan issue from a
different Thread. Mid-run list hops — Uncanny #360 after Generation X in a
CBL, Promethea #13 after Tom Strong, and other non-start adjacency — are
not crossover points and compile no blocker.

That representation is title-agnostic:

- Starman #55 before a JSA series start is a crossover / thread-entry gate.
- Magneto Rex #1, annuals, and other one-shot or volume starts are crossover
  points because they are Thread natural first issues.
- Wild Hunt #3 is never a thread-entry while #1 exists on the Thread, so an
  in-progress Wild Hunt stays Roll-eligible after earlier unread plan material.
- Absolute Universe later titles whose #1 is in the plan are gated, closing
  the "later material is Roll-eligible" leak without blanketing every hop.

Informational plans compile no inferred gates. Explicit checkpoints,
convergence gates, and caller-supplied selected pairs remain separate.
``inferred_gate_kind`` on a lane is provenance only; it never changes which
pairs this module emits.
"""

from __future__ import annotations

from collections.abc import Collection, Mapping, Sequence
from dataclasses import dataclass

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.issue import Issue
from app.schemas.continuity_plan import ContinuityPlanNode

_SKIPPED_READER_ROLES = frozenset({"skipped/excluded"})


@dataclass(frozen=True, slots=True)
class IssueThreadIndex:
    """Thread identity and series-start flag for one plan Issue."""

    thread_id: int
    position: int
    is_thread_natural_start: bool


def is_required_issue_node(node: ContinuityPlanNode) -> bool:
    """Return whether a plan node can source or receive a strict hard gate.

    Args:
        node: Plan node under consideration.

    Returns:
        True when the node is an issue that the reader has not marked optional
        or skipped. Presentation-only optionality never becomes a blocker.
    """
    if node.node_type != "issue":
        return False
    if node.reader_optional is True:
        return False
    if node.reader_role in _SKIPPED_READER_ROLES:
        return False
    return True


def strict_plan_item_read_pairs(
    nodes: Sequence[ContinuityPlanNode],
    index: Mapping[int, IssueThreadIndex],
) -> list[tuple[int, int]]:
    """Return inferred crossover / thread-entry ``item_read`` pairs.

    Same-thread adjacency is omitted. A pair is emitted only when the target
    is the Thread's natural first issue and a required predecessor on a
    different Thread exists earlier in plan order. Mid-run list adjacency
    between continuing series is not a crossover point.

    Args:
        nodes: Plan nodes in any order; display ``position`` is the sort key.
        index: Runtime Thread metadata for every referenced Issue.

    Returns:
        Ordered ``(source_issue_id, target_issue_id)`` pairs with no
        duplicates. Missing index entries are skipped rather than guessed.
    """
    ordered = sorted(
        (
            node
            for node in nodes
            if is_required_issue_node(node) and node.ref_id in index
        ),
        key=lambda node: (node.position, node.id),
    )
    pairs: list[tuple[int, int]] = []
    seen: set[tuple[int, int]] = set()
    for offset, target in enumerate(ordered):
        target_meta = index[target.ref_id]
        if not target_meta.is_thread_natural_start:
            continue
        predecessor_id: int | None = None
        for source in reversed(ordered[:offset]):
            if index[source.ref_id].thread_id != target_meta.thread_id:
                predecessor_id = source.ref_id
                break
        if predecessor_id is None or predecessor_id == target.ref_id:
            continue
        pair = (predecessor_id, target.ref_id)
        if pair in seen:
            continue
        seen.add(pair)
        pairs.append(pair)
    return pairs


async def load_issue_thread_index(
    db: AsyncSession,
    issue_ids: Collection[int],
) -> dict[int, IssueThreadIndex]:
    """Load Thread identity and natural-start flags for one Issue id set.

    Natural start is the minimum ``Issue.position`` among *all* issues of the
    Thread, not merely those present in the plan. That keeps an in-progress
    series (Wild Hunt #3 while #1-2 exist on the Thread) from being treated
    as a series start just because earlier issues were omitted from the plan.

    Args:
        db: Async database session.
        issue_ids: Issue ids referenced by the plan.

    Returns:
        Mapping of Issue id to Thread index rows. Unknown ids are omitted.
    """
    unique_ids = sorted({issue_id for issue_id in issue_ids if issue_id > 0})
    if not unique_ids:
        return {}
    referenced = (
        await db.execute(
            select(Issue.id, Issue.thread_id, Issue.position).where(
                Issue.id.in_(unique_ids)
            )
        )
    ).all()
    if not referenced:
        return {}
    thread_ids = {thread_id for _issue_id, thread_id, _position in referenced}
    min_positions = dict(
        (
            await db.execute(
                select(Issue.thread_id, func.min(Issue.position)).where(
                    Issue.thread_id.in_(thread_ids)
                ).group_by(Issue.thread_id)
            )
        ).all()
    )
    return {
        issue_id: IssueThreadIndex(
            thread_id=thread_id,
            position=position,
            is_thread_natural_start=position == min_positions[thread_id],
        )
        for issue_id, thread_id, position in referenced
    }
