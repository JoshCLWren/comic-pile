"""Tests for issue-level dependency cycle detection."""

from app.services.dependency_cycle import (
    build_reading_order_graph,
    find_cyclic_component_members,
    find_thread_cycle_issue_ids,
)


def test_interleaved_chain_has_no_cyclic_component() -> None:
    """Two series linked in both directions stay acyclic at the issue level.

    Regression coverage for issue #3596: ``A#1 -> B#1 -> A#2`` points at the
    same two series in both directions while no issue-level loop exists.
    """
    components = find_cyclic_component_members([(1, 2), (2, 3)])

    assert components == []


def test_two_issue_cycle_is_reported() -> None:
    """A direct reversal is a genuine issue-level loop."""
    components = find_cyclic_component_members([(1, 2), (2, 1)])

    assert components == [frozenset({1, 2})]


def test_three_issue_cycle_is_reported() -> None:
    """A longer loop is reported as one component."""
    components = find_cyclic_component_members([(1, 2), (2, 3), (3, 1)])

    assert components == [frozenset({1, 2, 3})]


def test_self_edge_is_a_cycle() -> None:
    """An issue that depends on itself is its own cycle."""
    components = find_cyclic_component_members([(7, 7)])

    assert components == [frozenset({7})]


def test_acyclic_chain_reports_nothing() -> None:
    """A plain chain contains no cycle."""
    components = find_cyclic_component_members([(1, 2), (2, 3), (3, 4)])

    assert components == []


def test_independent_cycle_is_not_merged() -> None:
    """Separate loops stay separate components."""
    components = find_cyclic_component_members([(1, 2), (2, 1), (3, 4), (4, 3)])

    assert sorted(components, key=sorted) == [frozenset({1, 2}), frozenset({3, 4})]


def test_thread_cycle_issue_ids_anchors_on_the_viewed_thread() -> None:
    """Only issues on a cycle running through the viewed thread are reported."""
    edges = [(1, 2), (2, 3), (3, 1), (4, 5), (5, 4)]
    issue_thread_ids = {1: 10, 2: 20, 3: 30, 4: 40, 5: 50}

    cycle_issue_ids = find_thread_cycle_issue_ids(edges, issue_thread_ids, 10)

    assert cycle_issue_ids == {1, 2, 3}


def test_thread_cycle_issue_ids_ignores_foreign_cycles() -> None:
    """A loop between other series does not mark the viewed thread."""
    edges = [(4, 5), (5, 4)]
    issue_thread_ids = {4: 40, 5: 50}

    cycle_issue_ids = find_thread_cycle_issue_ids(edges, issue_thread_ids, 10)

    assert cycle_issue_ids == set()


def test_thread_cycle_issue_ids_handles_an_empty_graph() -> None:
    """A reader without dependencies has no cycles."""
    assert find_thread_cycle_issue_ids([], {}, 10) == set()


def test_backward_series_chain_is_a_cycle() -> None:
    """Required series order makes a backward chain a genuine loop.

    ``A#2 -> B#1 -> A#1`` looks like a chain in the stored rows, but ``A#1``
    must be read before ``A#2``, so the implicit edge closes a loop and no
    issue in it can be read first.
    """
    edges = [(2, 3), (3, 1)]
    issues = [(1, 10, 1, "unread"), (2, 10, 2, "unread"), (3, 20, 1, "unread")]

    graph_edges, issue_thread_ids = build_reading_order_graph(edges, issues)

    assert (1, 2) in graph_edges
    assert find_thread_cycle_issue_ids(graph_edges, issue_thread_ids, 10) == {1, 2, 3}
    assert find_thread_cycle_issue_ids(graph_edges, issue_thread_ids, 20) == {1, 2, 3}


def test_forward_interleaved_chain_stays_acyclic_with_series_order() -> None:
    """Adding the required order must not turn a valid interleaving circular."""
    edges = [(1, 3), (3, 2)]
    issues = [(1, 10, 1, "unread"), (2, 10, 2, "unread"), (3, 20, 1, "unread")]

    graph_edges, issue_thread_ids = build_reading_order_graph(edges, issues)

    assert (1, 2) in graph_edges
    assert find_thread_cycle_issue_ids(graph_edges, issue_thread_ids, 10) == set()


def test_satisfied_dependency_does_not_complete_a_cycle() -> None:
    """A prerequisite whose source issue is read no longer constrains order."""
    edges = [(2, 3), (3, 1)]
    issues = [
        (1, 10, 1, "read"),
        (2, 10, 2, "unread"),
        (3, 20, 1, "unread"),
    ]

    graph_edges, issue_thread_ids = build_reading_order_graph(edges, issues)

    assert graph_edges == [(2, 3)]
    assert find_thread_cycle_issue_ids(graph_edges, issue_thread_ids, 10) == set()


def test_series_order_skips_read_issues() -> None:
    """Only unread issues contribute the implicit earlier/later edges."""
    issues = [
        (1, 10, 1, "read"),
        (2, 10, 2, "unread"),
        (3, 10, 3, "read"),
        (4, 10, 4, "unread"),
    ]

    graph_edges, _issue_thread_ids = build_reading_order_graph([], issues)

    assert graph_edges == [(2, 4)]

