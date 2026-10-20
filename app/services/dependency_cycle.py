"""Issue-level dependency cycle detection for connected-thread presentation.

Circularity is decided from the effective reading precedence graph, not from
the stored dependency rows alone. Within a series the reader reaches issues in
``position`` order, so an earlier unread issue is an implicit prerequisite of
the next unread issue. Two series can point at each other in both directions
without any impossible order existing: an interleaved chain such as
``USM#22 -> TYI#1 -> USM#23`` stays acyclic once the required
``USM#22 -> USM#23`` order is included. A backward chain such as
``A#2 -> B#1 -> A#1`` is different: with ``A#1`` before ``A#2`` the implicit
order closes a genuine loop, so no issue in it can be read first.

Only live constraints belong to that graph. A prerequisite whose source issue
is already read is satisfied, and an inert historical ``cbl-order:``
materialization row can never block, so neither can close a loop that does not
exist. The caller supplies the live prerequisite pairs; this module adds the
within-series order and finds the loops.
"""

from collections.abc import Iterable
from itertools import pairwise


def build_reading_order_graph(
    dependency_edges: Iterable[tuple[int, int]],
    issues: Iterable[tuple[int, int, int, str]],
) -> tuple[list[tuple[int, int]], dict[int, int]]:
    """Combine stored prerequisites with the required within-series order.

    Only unread issues participate. A stored prerequisite whose source issue is
    already read is satisfied and no longer constrains the reader, and a read
    issue can no longer be blocked, so both endpoints of a live constraint are
    unread. Earlier unread issues in a series then precede later ones through
    consecutive ``position`` pairs, transitively covering every earlier/later
    relation that remains.

    Args:
        dependency_edges: Live ``(source_issue_id, target_issue_id)`` pairs.
            ``source`` must be read before ``target``. The caller supplies
            only rows that can still constrain the reader.
        issues: ``(issue_id, thread_id, position, status)`` for the issues
            those edges connect. ``position`` is the canonical within-series
            reading order and is unique per thread; a duplicated position is
            broken by issue id so the resulting order stays deterministic.

    Returns:
        Tuple of live precedence edges and the thread that owns each issue.
    """
    issue_thread_ids: dict[int, int] = {}
    unread_by_thread: dict[int, list[tuple[int, int]]] = {}
    for issue_id, thread_id, position, status in issues:
        issue_thread_ids[issue_id] = thread_id
        if status != "read":
            unread_by_thread.setdefault(thread_id, []).append((position, issue_id))

    unread_issue_ids = {
        issue_id
        for thread_issues in unread_by_thread.values()
        for _position, issue_id in thread_issues
    }

    edges: list[tuple[int, int]] = [
        (source_issue_id, target_issue_id)
        for source_issue_id, target_issue_id in dependency_edges
        if source_issue_id in unread_issue_ids and target_issue_id in unread_issue_ids
    ]

    for thread_issues in unread_by_thread.values():
        thread_issues.sort()
        for (_earlier_position, earlier_issue_id), (_later_position, later_issue_id) in pairwise(
            thread_issues
        ):
            edges.append((earlier_issue_id, later_issue_id))

    return edges, issue_thread_ids


def find_cyclic_component_members(
    edges: Iterable[tuple[int, int]],
) -> list[frozenset[int]]:
    """Return the issue ids of every strongly connected component holding a cycle.

    The traversal is an iterative Tarjan implementation: dependency graphs are
    reader-sized but can be deep, and recursion would risk a stack overflow on
    a long prerequisite chain.

    Args:
        edges: Directed ``(source_issue_id, target_issue_id)`` dependency edges.
            A self edge marks its own issue as cyclic.

    Returns:
        One member set per component that contains a directed cycle. Components
        without a cycle, including single issues with no self edge, are omitted.
    """
    adjacency: dict[int, list[int]] = {}
    for source_issue_id, target_issue_id in edges:
        adjacency.setdefault(source_issue_id, []).append(target_issue_id)
        adjacency.setdefault(target_issue_id, [])

    indices: dict[int, int] = {}
    lowlinks: dict[int, int] = {}
    on_stack: set[int] = set()
    stack: list[int] = []
    components: list[frozenset[int]] = []
    next_index = 0

    for root in sorted(adjacency):
        if root in indices:
            continue
        # Each frame is (node, index of the next neighbor to visit).
        work: list[tuple[int, int]] = [(root, 0)]
        while work:
            node, neighbor_index = work[-1]
            if node not in indices:
                indices[node] = next_index
                lowlinks[node] = next_index
                next_index += 1
                stack.append(node)
                on_stack.add(node)
            neighbors = adjacency[node]
            descended = False
            while neighbor_index < len(neighbors):
                neighbor = neighbors[neighbor_index]
                neighbor_index += 1
                if neighbor not in indices:
                    work[-1] = (node, neighbor_index)
                    work.append((neighbor, 0))
                    descended = True
                    break
                if neighbor in on_stack:
                    lowlinks[node] = min(lowlinks[node], indices[neighbor])
            if descended:
                continue
            work[-1] = (node, neighbor_index)
            work.pop()
            if work:
                parent = work[-1][0]
                lowlinks[parent] = min(lowlinks[parent], lowlinks[node])
            if lowlinks[node] == indices[node]:
                members: list[int] = []
                while True:
                    member = stack.pop()
                    on_stack.discard(member)
                    members.append(member)
                    if member == node:
                        break
                if len(members) > 1 or node in adjacency[node]:
                    components.append(frozenset(members))
    return components


def find_thread_cycle_issue_ids(
    edges: Iterable[tuple[int, int]],
    issue_thread_ids: dict[int, int],
    thread_id: int,
) -> set[int]:
    """Return every issue that shares an issue-level cycle with one thread.

    A cycle belongs to a thread when the cycle contains at least one of that
    thread's issues. Every issue of such a cycle is reported, so the caller
    can mark the other series on the cycle.

    Args:
        edges: Directed ``(source_issue_id, target_issue_id)`` dependency edges.
        issue_thread_ids: Thread each issue belongs to.
        thread_id: Thread whose cycles are being selected.

    Returns:
        Issue ids that lie on a cycle running through the given thread.
    """
    cyclic_issue_ids: set[int] = set()
    for component in find_cyclic_component_members(edges):
        if any(issue_thread_ids.get(issue_id) == thread_id for issue_id in component):
            cyclic_issue_ids.update(component)
    return cyclic_issue_ids
