"""Deterministic collapse rule for repeated canonical Issue nodes.

Reading Plan membership is set membership: within one plan a canonical Issue
appears at most once. ``normalize_plan_nodes`` is the single rule that enforces
it on the canonical write path, so it is covered here as a pure function with no
database dependency.
"""

from app.schemas.continuity_plan import (
    CBLPlacement,
    ContinuityPlanNode,
    ConvergenceGateTarget,
)
from app.services.reading_plan_normalization import normalize_plan_nodes


def _issue(
    node_id: str,
    ref_id: int,
    position: int,
    *,
    lane_id: str = "main",
    **overrides: object,
) -> ContinuityPlanNode:
    """Build one issue plan node."""
    return ContinuityPlanNode(
        id=node_id,
        node_type="issue",
        ref_id=ref_id,
        lane_id=lane_id,
        position=position,
        **overrides,
    )


def test_distinct_issues_are_returned_unchanged() -> None:
    """A plan without repeats passes through untouched."""
    nodes = [_issue("a", 1, 0), _issue("b", 2, 1)]
    assert normalize_plan_nodes(nodes) == nodes


def test_lowest_position_occurrence_survives() -> None:
    """Reading order decides the survivor before occurrence ID breaks ties."""
    nodes = [_issue("late", 1, 5), _issue("early", 1, 2), _issue("other", 2, 9)]
    normalized = normalize_plan_nodes(nodes)
    assert [node.id for node in normalized] == ["early", "other"]
    assert [node.position for node in normalized] == [2, 9]


def test_occurrence_id_breaks_a_position_tie() -> None:
    """Two occurrences at the same position resolve by occurrence ID."""
    normalized = normalize_plan_nodes([_issue("beta", 1, 0), _issue("alpha", 1, 0)])
    assert [node.id for node in normalized] == ["alpha"]


def test_provenance_from_every_occurrence_is_preserved() -> None:
    """Collapsing membership never discards import evidence."""
    nodes = [
        _issue(
            "first",
            1,
            0,
            source_paths=("cbl:one",),
            source_cbl_placements=(CBLPlacement(source_path="cbl:one", position=1),),
            source_role="core",
        ),
        _issue(
            "second",
            1,
            1,
            source_paths=("cbl:one", "cbl:two"),
            source_cbl_placements=(
                CBLPlacement(source_path="cbl:one", position=1),
                CBLPlacement(source_path="cbl:two", position=4),
            ),
            source_explanation="recap placement",
        ),
    ]
    [survivor] = normalize_plan_nodes(nodes)
    assert survivor.source_paths == ("cbl:one", "cbl:two")
    assert [placement.source_path for placement in survivor.source_cbl_placements or ()] == [
        "cbl:one",
        "cbl:two",
    ]
    assert survivor.source_role == "core"
    assert survivor.source_explanation == "recap placement"


def test_reader_overrides_of_the_survivor_win() -> None:
    """Label and reader overrides are reader-visible and are never merged away."""
    nodes = [
        _issue("first", 1, 0, label="First", reader_role="required/core"),
        _issue("second", 1, 1, label="Second", reader_role="optional"),
    ]
    [survivor] = normalize_plan_nodes(nodes)
    assert survivor.label == "First"
    assert survivor.reader_role == "required/core"


def test_plan_level_gates_are_unioned() -> None:
    """A checkpoint or convergence gate on any occurrence survives the collapse."""
    nodes = [
        _issue("first", 1, 0),
        _issue(
            "second",
            1,
            1,
            is_checkpoint=True,
            convergence_gate=[
                ConvergenceGateTarget(node_type="issue", node_id="waited")
            ],
        ),
    ]
    [survivor] = normalize_plan_nodes(nodes)
    assert survivor.is_checkpoint is True
    assert [target.node_id for target in survivor.convergence_gate] == ["waited"]


def test_convergence_gate_is_repointed_at_the_survivor() -> None:
    """A gate waiting on a removed occurrence waits on its survivor instead."""
    nodes = [
        _issue("first", 1, 0),
        _issue("second", 1, 1),
        _issue(
            "later",
            2,
            2,
            convergence_gate=[
                ConvergenceGateTarget(node_type="issue", node_id="second")
            ],
        ),
    ]
    normalized = normalize_plan_nodes(nodes)
    assert [node.id for node in normalized] == ["first", "later"]
    assert [target.node_id for target in normalized[1].convergence_gate] == ["first"]


def test_convergence_gate_onto_its_own_occurrence_is_dropped() -> None:
    """An Issue waiting for its own collapsed occurrence is not a real wait."""
    nodes = [
        _issue(
            "first",
            1,
            0,
            convergence_gate=[
                ConvergenceGateTarget(node_type="issue", node_id="second")
            ],
        ),
        _issue("second", 1, 1),
    ]
    [survivor] = normalize_plan_nodes(nodes)
    assert survivor.convergence_gate == []


def test_non_issue_nodes_are_never_collapsed() -> None:
    """Crossover and thread nodes keep every occurrence."""
    crossover = ContinuityPlanNode(
        id="crossover-1", node_type="crossover", ref_id=7, lane_id="main", position=1
    )
    thread = ContinuityPlanNode(
        id="thread-1", node_type="thread", ref_id=8, lane_id="main", position=2
    )
    normalized = normalize_plan_nodes([_issue("a", 1, 0), crossover, thread])
    assert [node.id for node in normalized] == ["a", "crossover-1", "thread-1"]


def test_compact_positions_renumbers_each_lane_after_a_collapse() -> None:
    """Strict sequential plans stay contiguous enough to round-trip the API."""
    nodes = [
        _issue("a", 1, 0),
        _issue("dup", 1, 1),
        _issue("b", 2, 2),
        _issue("c", 3, 4, lane_id="side"),
        _issue("d", 4, 7, lane_id="side"),
    ]
    normalized = normalize_plan_nodes(nodes, compact_positions=True)
    assert [(node.id, node.lane_id, node.position) for node in normalized] == [
        ("a", "main", 0),
        ("b", "main", 1),
        ("c", "side", 0),
        ("d", "side", 1),
    ]


def test_compact_positions_is_a_no_op_without_duplicates() -> None:
    """Contiguous plans keep the exact positions they were written with."""
    nodes = [_issue("a", 1, 0), _issue("b", 2, 1)]
    normalized = normalize_plan_nodes(nodes, compact_positions=True)
    assert [node.position for node in normalized] == [0, 1]


def test_collapse_is_idempotent() -> None:
    """Re-normalizing an already normalized node set changes nothing."""
    nodes = [_issue("first", 1, 0), _issue("second", 1, 3), _issue("other", 2, 5)]
    once = normalize_plan_nodes(nodes, compact_positions=True)
    twice = normalize_plan_nodes(once, compact_positions=True)
    assert once == twice


def test_compact_positions_follows_declared_order_not_list_order() -> None:
    """A collapse never reverses the reading order the plan declared.

    The API accepts plan nodes in any list order, so compaction has to rank the
    declared positions rather than the submission order. Otherwise collapsing a
    repeat in a strict sequential plan submitted out of order would silently
    flip its reading order.
    """
    nodes = [
        _issue("b", 2, 2),
        _issue("dup", 1, 3),
        _issue("a", 3, 0),
        _issue("first", 1, 1),
    ]
    normalized = normalize_plan_nodes(nodes, compact_positions=True)
    assert {node.id for node in normalized} == {"a", "first", "b"}
    assert {node.id: node.position for node in normalized} == {
        "a": 0,
        "first": 1,
        "b": 2,
    }
