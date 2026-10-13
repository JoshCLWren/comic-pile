"""Pure contract checks for durable custom CBL checkpoint target semantics."""

import pytest
from pydantic import ValidationError

from app.schemas.continuity_plan import ContinuityPlanNode
from app.schemas.custom_cbl import CustomCBLWrite
from app.services.continuity_plan_writer import (
    _checkpoint_edges_from_nodes,
    preserve_checkpoint_targets,
)


@pytest.mark.parametrize("targets", [{1: [1]}, {1: [2, 2]}, {1: [4]}, {4: [2]}, {1: [True]}])
def test_invalid_checkpoint_targets_are_rejected(targets: dict[int, list[int]]) -> None:
    """Reject self, duplicate, non-member, and boolean targets before any mutation."""
    with pytest.raises(ValidationError):
        CustomCBLWrite(name="Order", issue_ids=[1, 2, 3], checkpoint_targets=targets)


def test_explicit_fanout_ignores_adjacency_and_removed_target() -> None:
    """Missing targets cannot cause a checkpoint to fall back to the next list node."""
    source = ContinuityPlanNode(
        id="source",
        node_type="issue",
        ref_id=1,
        lane_id="a",
        position=0,
        is_checkpoint=True,
        checkpoint_target_ref_ids=[3, 4],
    )
    neighbor = ContinuityPlanNode(
        id="neighbor", node_type="issue", ref_id=2, lane_id="a", position=1
    )
    target = ContinuityPlanNode(id="target", node_type="issue", ref_id=3, lane_id="b", position=0)
    edges = _checkpoint_edges_from_nodes([source, neighbor, target])
    assert edges == [("issue", 1, "issue", 3, "checkpoint", 1)]


def test_missing_all_explicit_targets_never_uses_neighbor() -> None:
    """Even when no targets survive, the source does not gate a different issue."""
    source = ContinuityPlanNode(
        id="source",
        node_type="issue",
        ref_id=1,
        lane_id="a",
        position=0,
        is_checkpoint=True,
        checkpoint_target_ref_ids=[3],
    )
    neighbor = ContinuityPlanNode(
        id="neighbor", node_type="issue", ref_id=2, lane_id="a", position=1
    )
    assert _checkpoint_edges_from_nodes([source, neighbor]) == []


def test_old_planner_payload_preserves_targets_but_explicit_edits_do_not() -> None:
    """An old tab cannot replace stored targets with incidental adjacency."""
    base = {
        "id": "source",
        "node_type": "issue",
        "ref_id": 1,
        "lane_id": "a",
        "position": 0,
        "is_checkpoint": True,
    }
    current = ContinuityPlanNode.model_validate({**base, "checkpoint_target_ref_ids": [3, 4]})
    omitted = ContinuityPlanNode.model_validate(base)
    assert preserve_checkpoint_targets([current], [omitted])[0].checkpoint_target_ref_ids == [3, 4]
    explicit = ContinuityPlanNode.model_validate({**base, "checkpoint_target_ref_ids": [5]})
    assert preserve_checkpoint_targets([current], [explicit])[0].checkpoint_target_ref_ids == [5]
    disabled = ContinuityPlanNode.model_validate({**base, "is_checkpoint": False})
    assert preserve_checkpoint_targets([current], [disabled])[0].checkpoint_target_ref_ids == []
