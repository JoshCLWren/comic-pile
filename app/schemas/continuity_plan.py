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


class ContinuityPlanWrite(BaseModel):
    """Create/replace payload for a persisted continuity plan."""

    name: str = Field(min_length=1, max_length=200)
    ordering_mode: PlanOrderingMode = "informational"
    lanes: list[ContinuityPlanLane] = Field(min_length=1, max_length=100)
    nodes: list[ContinuityPlanNode] = Field(default_factory=list, max_length=1000)

    @model_validator(mode="after")
    def validate_structure(self) -> ContinuityPlanWrite:
        """Reject duplicate identifiers and malformed lane ordering."""
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
        if self.ordering_mode == "strict_sequential" and any(
            node.node_type == "thread" for node in self.nodes
        ):
            raise ValueError("strict sequential plans may contain only issue/crossover nodes")
        return self


class ContinuityPlanResponse(ContinuityPlanWrite):
    """Persisted continuity plan response."""

    id: int
    user_id: int
    created_at: datetime
    updated_at: datetime
