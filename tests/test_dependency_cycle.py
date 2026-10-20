"""Tests for issue-level dependency cycle detection."""

from app.services.dependency_cycle import (
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
