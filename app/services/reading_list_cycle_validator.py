"""Pure global cycle validation for Option E execution constraints."""

from collections.abc import Mapping
from dataclasses import dataclass
from heapq import heapify, heappop, heappush

from app.services.reading_list_evaluator import ReadingSnapshot


@dataclass(frozen=True, slots=True)
class ConstraintEdge:
    """One directed requirement and the reader-visible reason for it."""

    source_issue_id: int
    target_issue_id: int
    origin: str


class ReadingCycleError(ValueError):
    """A cycle in the combined execution graph, with a concrete path."""

    def __init__(self, edges: tuple[ConstraintEdge, ...]) -> None:
        """Store the cycle edges and format their origins for readers."""
        self.edges = edges
        path = " -> ".join(
            f"Issue {edge.source_issue_id} --[{edge.origin}]--> Issue {edge.target_issue_id}"
            for edge in edges
        )
        super().__init__(f"Reading constraint cycle: {path}")


def validate_reading_constraints(
    snapshot: ReadingSnapshot,
    *,
    list_names: Mapping[int, str] | None = None,
    thread_names: Mapping[int, str] | None = None,
) -> tuple[int, ...]:
    """Validate stored constraints, including read and excluded Issues.

    Global exclusions change eligibility, but do not erase stored ordering
    constraints during write validation. Local skipped placements are omitted.
    Returns a stable topological order when the combined graph is acyclic.

    Args:
        snapshot: Complete user-scoped execution inputs. Its constructor rejects
            missing references and excluded prerequisite sources.
        list_names: Optional overrides for titles carried by list snapshots.
        thread_names: Optional overrides for titles carried by Thread snapshots.

    Returns:
        Issue IDs in deterministic topological order.

    Raises:
        ReadingCycleError: When the combined graph contains a cycle.
    """
    list_names = list_names or {}
    thread_names = thread_names or {}
    named_threads = {
        thread.thread_id: (thread_names.get(thread.thread_id) or thread.name).strip()
        or f"#{thread.thread_id}"
        for thread in snapshot.threads
    }
    named_lists = {
        reading_list.list_id: (list_names.get(reading_list.list_id) or reading_list.name).strip()
        or f"#{reading_list.list_id}"
        for reading_list in snapshot.lists
    }
    edges: set[ConstraintEdge] = set()
    by_thread: dict[int, list[tuple[int, int]]] = {}
    for issue in snapshot.issues:
        # Validate stored order even for excluded Issues. Exclusions suppress
        # eligibility, but must not make an invalid edit appear acyclic.
        by_thread.setdefault(issue.thread_id, []).append((issue.position, issue.issue_id))
    for thread_id, ordered in by_thread.items():
        ids = [issue_id for _, issue_id in sorted(ordered)]
        name = named_threads[thread_id]
        edges.update(
            ConstraintEdge(a, b, f"Thread {name} series order")
            for a, b in zip(ids, ids[1:], strict=False)
        )
    for reading_list in snapshot.lists:
        entries = [
            entry
            for entry in reading_list.entries
            if not entry.skipped
        ]
        name = named_lists[reading_list.list_id]
        ids = [entry.issue_id for entry in entries]
        if reading_list.mode == "strict":
            edges.update(
                ConstraintEdge(a, b, f"list {name} strict order")
                for a, b in zip(ids, ids[1:], strict=False)
            )
        # A chain implies that every earlier strict entry precedes each later
        # one. Store its transitive reduction to keep long lists linear.
        previous_hold: int | None = None
        since_hold: list[int] = []
        for index, entry in enumerate(entries):
            if previous_hold is not None:
                edges.add(ConstraintEdge(previous_hold, entry.issue_id, f"list {name} hold"))
            if entry.gate == "after_previous" and index:
                edges.add(
                    ConstraintEdge(ids[index - 1], entry.issue_id, f"list {name} after_previous")
                )
            if entry.gate == "hold":
                # The prior hold already depends on everything above it. Only
                # entries since that milestone need direct edges to this one.
                edges.update(
                    ConstraintEdge(source, entry.issue_id, f"list {name} hold")
                    for source in since_hold
                )
                previous_hold = entry.issue_id
                since_hold.clear()
            else:
                since_hold.append(entry.issue_id)
    edges.update(
        ConstraintEdge(
            p.source_issue_id, p.target_issue_id, f"prerequisite {p.prerequisite_id} ({p.origin})"
        )
        for p in snapshot.prerequisites
    )
    adjacency: dict[int, list[ConstraintEdge]] = {issue.issue_id: [] for issue in snapshot.issues}
    indegree = dict.fromkeys(adjacency, 0)
    for edge in sorted(edges, key=lambda e: (e.source_issue_id, e.target_issue_id, e.origin)):
        adjacency[edge.source_issue_id].append(edge)
        indegree[edge.target_issue_id] += 1
    ready = [issue_id for issue_id, degree in indegree.items() if degree == 0]
    heapify(ready)
    ordered_ids: list[int] = []
    while ready:
        issue_id = heappop(ready)
        ordered_ids.append(issue_id)
        for edge in adjacency[issue_id]:
            indegree[edge.target_issue_id] -= 1
            if indegree[edge.target_issue_id] == 0:
                heappush(ready, edge.target_issue_id)
    if len(ordered_ids) == len(adjacency):
        return tuple(ordered_ids)

    # Walk only the residual graph. An explicit stack keeps long lists safe.
    residual = {issue_id for issue_id, degree in indegree.items() if degree > 0}
    visited: set[int] = set()
    for start in sorted(residual):
        if start in visited:
            continue
        active: dict[int, int] = {start: 0}
        path: list[ConstraintEdge] = []
        stack = [
            (start, iter(edge for edge in adjacency[start] if edge.target_issue_id in residual))
        ]
        while stack:
            node, iterator = stack[-1]
            edge = next(iterator, None)
            if edge is None:
                visited.add(node)
                del active[node]
                stack.pop()
                if path:
                    path.pop()
                continue
            target = edge.target_issue_id
            if target in active:
                raise ReadingCycleError(tuple(path[active[target] :] + [edge]))
            if target not in visited:
                active[target] = len(path) + 1
                path.append(edge)
                stack.append(
                    (
                        target,
                        iter(
                            next_edge
                            for next_edge in adjacency[target]
                            if next_edge.target_issue_id in residual
                        ),
                    )
                )
    raise RuntimeError("Residual graph has no cycle")
