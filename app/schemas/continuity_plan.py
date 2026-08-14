"""Continuity-plan request and response schemas."""

from __future__ import annotations

from datetime import datetime
from typing import Annotated, Literal

from pydantic import BaseModel, BeforeValidator, Field, model_validator

from app.schemas.continuity_readiness import ContinuityBlocker

PlanOrderingMode = Literal["informational", "strict_sequential"]
PlanNodeType = Literal["issue", "crossover", "thread"]
PlanReadinessDiagnosticCode = Literal[
    "dangling_plan_reference",
    "plan_cycle_detected",
    "cycle_detected",
    "depth_limit_exceeded",
    "node_limit_exceeded",
]


def _reject_boolean_item_id(value: object) -> object:
    """Reject boolean JSON values before Pydantic coerces them to integers."""
    if isinstance(value, bool):
        raise ValueError("source_list_ids must contain positive integers")
    return value


TemplateSourceListId = Annotated[int, BeforeValidator(_reject_boolean_item_id)]


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
        return self


class ContinuityPlanResponse(ContinuityPlanWrite):
    """Persisted continuity plan response."""

    id: int
    user_id: int
    created_at: datetime
    updated_at: datetime


class ContinuityPlanChainNode(BaseModel):
    """One labeled issue or crossover step in a plan prerequisite chain."""

    node_type: Literal["issue", "crossover"]
    node_id: int
    label: str
    is_readable: bool


class ContinuityPlanReadinessDiagnostic(BaseModel):
    """One structured plan-readiness failure that does not require text parsing."""

    code: PlanReadinessDiagnosticCode
    node_type: PlanNodeType
    node_id: int
    limit: int | None = None


class ContinuityPlanNodeReadiness(BaseModel):
    """Live readiness of one visible node in a saved continuity plan."""

    node_id: str
    node_type: PlanNodeType
    ref_id: int
    lane_id: str
    position: int
    label: str
    is_readable: bool
    is_complete: bool
    evaluated_issue_id: int | None = None
    blockers: list[ContinuityBlocker] = Field(default_factory=list)
    diagnostics: list[ContinuityPlanReadinessDiagnostic] = Field(default_factory=list)
    chains: list[list[ContinuityPlanChainNode]] = Field(default_factory=list)
    readable_prerequisites: list[ContinuityPlanChainNode] = Field(default_factory=list)


class ContinuityPlanReadinessSummary(BaseModel):
    """Deterministic state buckets for one saved plan."""

    total: int = 0
    readable: int = 0
    blocked: int = 0
    complete: int = 0
    unavailable: int = 0


class ContinuityPlanReadinessResponse(BaseModel):
    """Aggregate live readiness for every visible node of one owned plan."""

    plan_id: int
    plan_name: str
    ordering_mode: PlanOrderingMode
    lanes: list[ContinuityPlanLane] = Field(default_factory=list)
    nodes: list[ContinuityPlanNodeReadiness] = Field(default_factory=list)
    plan_diagnostics: list[ContinuityPlanReadinessDiagnostic] = Field(
        default_factory=list
    )
    summary: ContinuityPlanReadinessSummary = Field(default_factory=ContinuityPlanReadinessSummary)
    generated_at: datetime
