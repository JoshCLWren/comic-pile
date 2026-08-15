"""Continuity-plan request and response schemas."""

from __future__ import annotations

from datetime import datetime
from typing import Annotated, Literal

from pydantic import BaseModel, BeforeValidator, Field, model_validator

PlanOrderingMode = Literal["informational", "strict_sequential"]
PlanNodeType = Literal["issue", "crossover", "thread"]


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


TemplateRole = Literal["core", "context/prelude", "epilogue", "unknown"]
TemplateConfidence = Literal["high", "medium", "low"]


class CrossoverTemplateItemPreview(BaseModel):
    """Suggested crossover member with full provenance and advisory metadata."""

    issue_id: int
    suggested_position: int
    role: TemplateRole
    confidence: TemplateConfidence
    explanation: str
    source_paths: tuple[str, ...]
    target_story_arc_id: str | None


class CrossoverTemplateConflictPreview(BaseModel):
    """A pair whose reading-order evidence disagrees across source lists."""

    first_issue_id: int
    second_issue_id: int
    source_paths: tuple[str, ...]


class CrossoverTemplateParallelCandidatePreview(CrossoverTemplateConflictPreview):
    """Advisory pair that may represent parallel branches."""


class CrossoverTemplateSerialSpinePreview(BaseModel):
    """Same-thread issue order preserved as advisory series structure."""

    thread_id: int
    issue_ids: tuple[int, ...]
    source_paths: tuple[str, ...]
    explanation: str


class CrossoverTemplateIntersectionPreview(BaseModel):
    """Consistent cross-thread ordering observation, never a hard dependency."""

    first_issue_id: int
    second_issue_id: int
    source_paths: tuple[str, ...]
    explanation: str


class CrossoverTemplateUnresolvedMatchPreview(BaseModel):
    """A source entry that could not be matched to a ComicPile issue."""

    source_path: str
    position: int
    series_name: str
    issue_number: str
    reason: str


class DerivedCrossoverTemplatePreview(BaseModel):
    """Non-blocking preview of a derived external crossover template."""

    items: list[CrossoverTemplateItemPreview]
    conflicts: list[CrossoverTemplateConflictPreview] = Field(default_factory=list)
    parallel_candidates: list[CrossoverTemplateParallelCandidatePreview] = (
        Field(default_factory=list)
    )
    serial_spines: list[CrossoverTemplateSerialSpinePreview] = Field(default_factory=list)
    intersections: list[CrossoverTemplateIntersectionPreview] = Field(default_factory=list)
    unresolved: list[CrossoverTemplateUnresolvedMatchPreview] = Field(default_factory=list)


class CrossoverTemplatePreviewRequest(BaseModel):
    """Request to preview a derived crossover template from persisted CBL evidence."""

    source_list_ids: tuple[TemplateSourceListId, ...] = Field(min_length=1)
    target_story_arc_id: str | None = None

    @model_validator(mode="after")
    def validate_positive_ids(self) -> CrossoverTemplatePreviewRequest:
        """Validate that all source_list_ids are positive non-boolean integers."""
        for item_id in self.source_list_ids:
            # Explicitly reject boolean values because bool is a subclass of int
            if isinstance(item_id, bool) or not isinstance(item_id, int) or item_id <= 0:
                raise ValueError("source_list_ids must contain positive integers")
        return self


class CrossoverTemplateAdoptRequest(BaseModel):
    """Adopt an external template into an editable continuity plan."""

    source_list_ids: tuple[TemplateSourceListId, ...] = Field(min_length=1)
    target_story_arc_id: str | None = None
    plan_name: str = Field(min_length=1, max_length=200)
    ordering_mode: PlanOrderingMode = "informational"
    lane_id: str = Field(min_length=1, max_length=80, default="imported")
    lane_name: str = Field(min_length=1, max_length=120, default="Imported")
    issue_node_id_prefix: str = Field(min_length=1, max_length=40, default="tpl-")

    @model_validator(mode="after")
    def validate_positive_ids(self) -> CrossoverTemplateAdoptRequest:
        """Validate that all source_list_ids are positive non-boolean integers."""
        if any(
            isinstance(item_id, bool) or not isinstance(item_id, int) or item_id <= 0
            for item_id in self.source_list_ids
        ):
            raise ValueError("source_list_ids must contain positive integers")
        return self
