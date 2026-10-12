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
different Thread.

Annuals, specials, one-shots, and Giant-Size issues belong to their parent
series. A short side Thread (four issues or fewer) whose plan run starts at
that Thread's natural first issue is not free-floating: it is anchored to
the required issue immediately before it in plan order, and the next plan
issue from that same parent Thread after the side run waits until the side
Thread is read. Mid-run list hops between ongoing series — Uncanny #360
after Generation X, Promethea #13 after Tom Strong — are not crossover
points and compile no blocker.

That representation is title-agnostic:

- Starman #55 before a JSA series start is a crossover / thread-entry gate.
- X-Men 1999, Magneto War, Giant-Size Fantastic Four, and other short
  side Threads compile the parent-before and parent-resume pair.
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
# One-shots, annuals, specials, Giant-Size, and short miniseries. Ongoing
# series (JSA, Uncanny, Promethea) have more issues and are not side Threads.
_SIDE_THREAD_MAX_ISSUES = 4


@dataclass(frozen=True, slots=True)
class IssueThreadIndex:
    """Thread identity and series-start flag for one plan Issue."""

    thread_id: int
    position: int
    is_thread_natural_start: bool
    thread_issue_count: int = 99

    @property
    def is_side_thread(self) -> bool:
        """Return whether this issue's Thread is a short parent-anchored side title."""
        return self.thread_issue_count <= _SIDE_THREAD_MAX_ISSUES


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


def _ordered_required_nodes(
    nodes: Sequence[ContinuityPlanNode],
    index: Mapping[int, IssueThreadIndex],
) -> list[ContinuityPlanNode]:
    """Return required issue nodes sorted by plan display position."""
    return sorted(
        (
            node
            for node in nodes
            if is_required_issue_node(node) and node.ref_id in index
        ),
        key=lambda node: (node.position, node.id),
    )


def _append_pair(
    pairs: list[tuple[int, int]],
    seen: set[tuple[int, int]],
    source_id: int,
    target_id: int,
) -> None:
    """Append one unique ``item_read`` pair."""
    if source_id == target_id:
        return
    pair = (source_id, target_id)
    if pair in seen:
        return
    seen.add(pair)
    pairs.append(pair)


def _thread_entry_pairs(
    ordered: Sequence[ContinuityPlanNode],
    index: Mapping[int, IssueThreadIndex],
) -> list[tuple[int, int]]:
    """Return gates from a different-thread predecessor onto a series start."""
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
        if predecessor_id is None:
            continue
        _append_pair(pairs, seen, predecessor_id, target.ref_id)
    return pairs


def _parent_anchored_side_thread_pairs(
    ordered: Sequence[ContinuityPlanNode],
    index: Mapping[int, IssueThreadIndex],
) -> list[tuple[int, int]]:
    """Return resume gates: parent next-issue waits on a short side Thread.

    A consecutive run that starts at a short Thread's natural first issue is
    an annual/special/one-shot/Giant-Size insertion. After that run, the next
    required issue from the same Thread as the immediate predecessor is
    blocked until the side run is read.

    Args:
        ordered: Required plan issue nodes in display order.
        index: Runtime Thread metadata for every referenced Issue.

    Returns:
        ``(side_last_issue_id, parent_resume_issue_id)`` pairs.
    """
    pairs: list[tuple[int, int]] = []
    seen: set[tuple[int, int]] = set()
    offset = 0
    while offset < len(ordered):
        start = ordered[offset]
        start_meta = index[start.ref_id]
        end = offset + 1
        while (
            end < len(ordered)
            and index[ordered[end].ref_id].thread_id == start_meta.thread_id
        ):
            end += 1
        is_side_run = start_meta.is_side_thread and start_meta.is_thread_natural_start
        if is_side_run and offset > 0:
            predecessor = ordered[offset - 1]
            parent_thread_id = index[predecessor.ref_id].thread_id
            if parent_thread_id != start_meta.thread_id:
                for later in ordered[end:]:
                    if index[later.ref_id].thread_id == parent_thread_id:
                        _append_pair(
                            pairs,
                            seen,
                            ordered[end - 1].ref_id,
                            later.ref_id,
                        )
                        break
        offset = end
    return pairs


def strict_plan_item_read_pairs(
    nodes: Sequence[ContinuityPlanNode],
    index: Mapping[int, IssueThreadIndex],
) -> list[tuple[int, int]]:
    """Return inferred crossover ``item_read`` pairs for one plan node list.

    Same-thread adjacency is omitted. A pair is emitted when:

    * the target is a Thread natural first issue waiting on a required
      predecessor from a different Thread (series start / crossover entry);
    * or a short side Thread (annual, special, one-shot, Giant-Size) is
      inserted in plan order, in which case the next parent-Thread issue
      after that run also waits on the side Thread.

    Mid-run list adjacency between continuing series is not a crossover point.

    Args:
        nodes: Plan nodes in any order; display ``position`` is the sort key.
        index: Runtime Thread metadata for every referenced Issue.

    Returns:
        Ordered ``(source_issue_id, target_issue_id)`` pairs with no
        duplicates. Missing index entries are skipped rather than guessed.
    """
    ordered = _ordered_required_nodes(nodes, index)
    pairs = _thread_entry_pairs(ordered, index)
    seen = set(pairs)
    for source_id, target_id in _parent_anchored_side_thread_pairs(ordered, index):
        _append_pair(pairs, seen, source_id, target_id)
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
    ``thread_issue_count`` is the full Thread size so short side titles can
    be parent-anchored without reading titles.

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
    stats = {
        thread_id: (min_position, int(issue_count))
        for thread_id, min_position, issue_count in (
            await db.execute(
                select(
                    Issue.thread_id,
                    func.min(Issue.position),
                    func.count(),
                ).where(
                    Issue.thread_id.in_(thread_ids)
                ).group_by(Issue.thread_id)
            )
        ).all()
    }
    return {
        issue_id: IssueThreadIndex(
            thread_id=thread_id,
            position=position,
            is_thread_natural_start=position == stats[thread_id][0],
            thread_issue_count=stats[thread_id][1],
        )
        for issue_id, thread_id, position in referenced
    }
