"""Strict Reading Plan hard-constraint selection (#2553 Phase B).

A strict plan promises that Roll will honor its *selected* hard restrictions.
It does not promise that every imported or suggested-order adjacency is a
blocker. Natural Thread sequence remains ``Issue.position`` /
``Thread.next_unread_issue_id``; same-thread adjacent pairs are never
compiled into Dependencies.

The durable inferred restriction for ``strict_sequential`` is a *thread-entry
gate*: the natural first issue of a Thread (minimum ``Issue.position`` on that
Thread, whether or not earlier issues appear in the plan) waits on the nearest
preceding required plan issue from a different Thread.

That representation is title-agnostic:

- Starman #55 before a JSA series start is a thread-entry (or standalone) gate.
- X-Men / Cable / X-Force mid-run suggested-order hops are not inferred;
  genuine crossover Dependencies remain the blockers.
- Wild Hunt #3 is never a thread-entry while #1 exists on the Thread, so an
  in-progress Wild Hunt stays Roll-eligible after earlier unread plan material.
- Absolute Universe later titles whose #1 is in the plan are gated, closing
  the "later material is Roll-eligible" leak without blanketing every hop.

Informational plans compile no inferred gates. Explicit checkpoints,
convergence gates, and caller-supplied selected pairs remain separate.

Existing plan-owned ``item_read`` rows are a separate concern from this
selector. An ordinary no-change save must retain those rows until a hop is
classified and removed on purpose:

- **Intended reading order** — keep. Mignolaverse/Julix cross-thread
  mid-run hops (Abe Sapien minis, Hellboy in Love → Shadow Theater) are
  interleaved reading-order gates, not series-start inference.
- **Redundant** — implied by ``Issue.position`` / ``next_unread_issue_id``.
  Same-thread leftover adjacencies stay on no-change save because a stale
  frontier (Hellboy in Love next-unread pointing at #5 while #1-4 are
  unread) would newly roll a later issue if the hop were dropped.
- **Erroneous** — none proven in the live Mignolaverse, Absolute, Ultimate,
  or JSA plans; do not silently drop any existing restriction.

New inference on a real membership edit remains thread-entry only. This
module never emits a duplicate Starman #55 → JSA #1 edge; that sequence
is already recorded Starman #55 → All-Star Comics (1999) #1, then Secret
Files #1 → JSA #1.
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
    """Return inferred strict ``item_read`` pairs for one plan node list.

    Same-thread adjacency is omitted. A pair is emitted only when the target
    is the Thread's natural first issue and a required predecessor on a
    different Thread exists earlier in plan order.

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
