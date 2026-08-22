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


SourceRole = Literal["core", "context/prelude", "epilogue", "unknown"]
SourceConfidence = Literal["high", "medium", "low"]
ReaderRole = Literal[
    "required/core",
    "recommended",
    "optional",
    "context/prelude",
    "aftermath/epilogue",
    "skipped/excluded",
]


class CBLPlacement(BaseModel):
    """One ordered CBL observation with inseparable provenance."""

    source_path: str
    position: int


class ContinuityPlanNode(BaseModel):
    """One ordered reference in a continuity plan."""

    id: str = Field(min_length=1, max_length=80)
    node_type: PlanNodeType
    ref_id: int = Field(gt=0)
    lane_id: str = Field(min_length=1, max_length=80)
    position: int = Field(ge=0)

    # Source-derived metadata (populated at adoption, never modified by user)
    source_role: SourceRole | None = None
    source_confidence: SourceConfidence | None = None
    source_explanation: str | None = None
    source_paths: tuple[str, ...] | None = None
    source_cbl_placements: tuple[CBLPlacement, ...] | None = None
    source_story_arc_ids: tuple[str, ...] | None = None
    source_target_story_arc_id: str | None = None

    # Reader override fields (user can modify independently of source)
    reader_role: ReaderRole | None = None
    reader_optional: bool | None = None


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

    @model_validator(mode="before")
    @classmethod
    def _validate_no_bool_and_positive_pre_conversion(cls, values: object) -> object:
        """Reject boolean items and empty source_list_ids before Pydantic casts.

        Args:
            values: Raw input mapping supplied to the Pydantic model.

        Returns:
            The input mapping, unchanged.
        """
        if not isinstance(values, dict):
            return values
        raw_ids = values.get("source_list_ids")
        if not isinstance(raw_ids, (list, tuple)) or len(raw_ids) == 0:
            raise ValueError("source_list_ids must not be empty")
        for v in raw_ids:
            if isinstance(v, bool):
                raise ValueError("source_list_ids must contain positive integers")
        return values

    source_list_ids: tuple[TemplateSourceListId, ...] = Field(min_length=1)
    target_story_arc_id: str | None = None

    @model_validator(mode="after")
    def validate_positive_ids(self) -> CrossoverTemplatePreviewRequest:
        """Validate that all source_list_ids are positive non-boolean integers."""
        for item_id in self.source_list_ids:
            if isinstance(item_id, bool) or not isinstance(item_id, int) or item_id <= 0:
                raise ValueError("source_list_ids must contain positive integers")
        return self


class CrossoverTemplateAdoptRequest(BaseModel):
    """Adopt an external template into an editable continuity plan."""

    @model_validator(mode="before")
    @classmethod
    def _validate_no_bool_and_positive_pre_conversion(cls, values: object) -> object:
        """Reject boolean items and empty source_list_ids before Pydantic casts.

        Args:
            values: Raw input mapping supplied to the Pydantic model.

        Returns:
            The input mapping, unchanged.
        """
        if not isinstance(values, dict):
            return values
        raw_ids = values.get("source_list_ids")
        if not isinstance(raw_ids, (list, tuple)) or len(raw_ids) == 0:
            raise ValueError("source_list_ids must not be empty")
        for v in raw_ids:
            if isinstance(v, bool):
                raise ValueError("source_list_ids must contain positive integers")
        return values

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
