"""Continuity-plan request and response schemas."""

from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field, model_validator

PlanOrderingMode = Literal["informational", "strict_sequential"]
PlanNodeType = Literal["issue", "crossover", "thread"]


class ContinuityPlanLane(BaseModel):
    """One visual lane in a continuity plan."""

    id: str = Field(min_length=1, max_length=80)
    name: str = Field(min_length=1, max_length=120)
    order: int = Field(ge=0)


class ContinuityPlanNode(BaseModel):
    """One ordered reference in a continuity plan."""

    id: str = Field(min_length=1, max_length=80)
    node_type: PlanNodeType
    ref_id: int = Field(gt=0)
    lane_id: str = Field(min_length=1, max_length=80)
    position: int = Field(ge=0)


class ContinuityPlanCheckpoint(BaseModel):
    """A lane-stop checkpoint that blocks later lane members until its issue is read.

    The checkpoint is anchored to ``after_node_id``: the node that ends the readable
    portion of the lane. ``wait_for_issue_id`` is the issue that must be read before
    later nodes in the same lane become readable.
    """

    id: str = Field(min_length=1, max_length=80)
    lane_id: str = Field(min_length=1, max_length=80)
    after_node_id: str = Field(min_length=1, max_length=80)
    wait_for_issue_id: int | None = Field(default=None, gt=0)


class ContinuityPlanGate(BaseModel):
    """A convergence gate that unblocks one target node once every prerequisite is read."""

    id: str = Field(min_length=1, max_length=80)
    target_node_id: str = Field(min_length=1, max_length=80)
    requires_node_ids: list[str] = Field(min_length=1, max_length=100)


class ContinuityPlanWrite(BaseModel):
    """Create/replace payload for a persisted continuity plan."""

    name: str = Field(min_length=1, max_length=200)
    ordering_mode: PlanOrderingMode = "informational"
    lanes: list[ContinuityPlanLane] = Field(min_length=1, max_length=100)
    nodes: list[ContinuityPlanNode] = Field(default_factory=list, max_length=1000)
    checkpoints: list[ContinuityPlanCheckpoint] = Field(
        default_factory=list, max_length=1000
    )
    gates: list[ContinuityPlanGate] = Field(default_factory=list, max_length=1000)

    @model_validator(mode="after")
    def validate_structure(self) -> ContinuityPlanWrite:
        """Reject duplicate identifiers and malformed ordering before persistence."""
        lane_ids = [lane.id for lane in self.lanes]
        if len(set(lane_ids)) != len(lane_ids):
            raise ValueError("lane ids must be unique")
        lane_orders = [lane.order for lane in self.lanes]
        if len(set(lane_orders)) != len(lane_orders):
            raise ValueError("lane order values must be unique")
        node_ids = [node.id for node in self.nodes]
        if len(set(node_ids)) != len(node_ids):
            raise ValueError("node ids must be unique")
        known_lanes = set(lane_ids)
        if any(node.lane_id not in known_lanes for node in self.nodes):
            raise ValueError("every node must reference an existing lane")
        positions_by_lane: dict[str, list[int]] = {}
        for node in self.nodes:
            positions_by_lane.setdefault(node.lane_id, []).append(node.position)
        if any(len(values) != len(set(values)) for values in positions_by_lane.values()):
            raise ValueError("node positions must be unique within each lane")
        if self.ordering_mode == "strict_sequential":
            if len(self.lanes) != 1:
                raise ValueError("strict sequential plans must use exactly one lane")
            if any(node.node_type == "thread" for node in self.nodes):
                raise ValueError("strict sequential plans may contain only issue/crossover nodes")
            positions = sorted(node.position for node in self.nodes)
            if positions != list(range(len(positions))):
                raise ValueError("strict sequential positions must be contiguous starting at zero")
        self._validate_checkpoints(node_ids)
        self._validate_gates(node_ids)
        return self

    def _validate_checkpoints(self, node_ids: list[str]) -> None:
        """Validate lane-stop checkpoints against known nodes and lanes."""
        known_node_ids = set(node_ids)
        known_lanes = {lane.id for lane in self.lanes}
        seen: set[str] = set()
        for checkpoint in self.checkpoints:
            if checkpoint.id in seen:
                raise ValueError("checkpoint ids must be unique")
            seen.add(checkpoint.id)
            if checkpoint.lane_id not in known_lanes:
                raise ValueError(
                    f"checkpoint {checkpoint.id} references unknown lane {checkpoint.lane_id}"
                )
            if checkpoint.after_node_id not in known_node_ids:
                raise ValueError(
                    f"checkpoint {checkpoint.id} references unknown node {checkpoint.after_node_id}"
                )
            owner_node = next(
                node for node in self.nodes if node.id == checkpoint.after_node_id
            )
            if owner_node.lane_id != checkpoint.lane_id:
                raise ValueError(
                    f"checkpoint {checkpoint.id} must anchor a node in its own lane"
                )
            if owner_node.node_type not in {"issue", "crossover"}:
                raise ValueError(
                    f"checkpoint {checkpoint.id} must anchor an issue or crossover node"
                )
            if checkpoint.wait_for_issue_id is not None and owner_node.node_type != "issue":
                raise ValueError(
                    f"checkpoint {checkpoint.id} wait_for_issue_id requires an issue anchor"
                )
            later_exists = any(
                node.lane_id == checkpoint.lane_id
                and node.position > owner_node.position
                for node in self.nodes
            )
            if not later_exists:
                raise ValueError(
                    f"checkpoint {checkpoint.id} must precede at least one later lane member"
                )

    def _validate_gates(self, node_ids: list[str]) -> None:
        """Validate convergence gates against known nodes and reject self-cycles."""
        known_node_ids = set(node_ids)
        seen: set[str] = set()
        for gate in self.gates:
            if gate.id in seen:
                raise ValueError("gate ids must be unique")
            seen.add(gate.id)
            if gate.target_node_id not in known_node_ids:
                raise ValueError(
                    f"gate {gate.id} references unknown target {gate.target_node_id}"
                )
            if gate.target_node_id in gate.requires_node_ids:
                raise ValueError(
                    f"gate {gate.id} cannot require its own target node"
                )
            for required in gate.requires_node_ids:
                if required not in known_node_ids:
                    raise ValueError(
                        f"gate {gate.id} references unknown requirement {required}"
                    )
            if len(set(gate.requires_node_ids)) != len(gate.requires_node_ids):
                raise ValueError(
                    f"gate {gate.id} requires_node_ids must be unique"
                )


class ContinuityPlanResponse(ContinuityPlanWrite):
    """Persisted continuity plan response."""

    id: int
    user_id: int
    created_at: datetime
    updated_at: datetime
