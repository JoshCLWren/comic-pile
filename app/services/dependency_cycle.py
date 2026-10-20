"""Issue-level dependency cycle detection for connected-thread presentation.

Two series can point at each other in both directions without any issue-level
loop existing. An interleaved chain such as ``USM#22 -> TYI#1 -> USM#23``
links the same two series in both directions while the issue graph stays
acyclic, so the reading order stays possible. Only a real cycle in the
issue -> issue dependency graph makes a reading order impossible, so
circularity is decided from the strongly connected components of that graph.
"""

from collections.abc import Iterable


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
