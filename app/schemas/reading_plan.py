"""Normalized Reading Plan request and response schemas.

These schemas represent the relational Reading Plan persistence per
docs/READING_GRAPH_PERSISTENCE_DESIGN.md. They coexist with the existing
ContinuityPlan schemas for backward compatibility during transition.
"""

from __future__ import annotations

from datetime import datetime
from typing import Annotated, Literal

from pydantic import BaseModel, BeforeValidator, Field, model_validator

PlanOrderingMode = Literal["informational", "strict_sequential"]
PlanNodeType = Literal["issue", "crossover", "thread"]
ReaderRole = Literal[
    "required/core",
    "recommended",
    "optional",
    "context/prelude",
    "aftermath/epilogue",
    "skipped/excluded",
]
SourceRole = Literal["core", "context/prelude", "epilogue", "unknown"]
SourceConfidence = Literal["high", "medium", "low"]


def _reject_boolean_item_id(value: object) -> object:
    """Reject boolean JSON values before Pydantic coerces them to integers."""
    if isinstance(value, bool):
        raise ValueError("source_list_ids must contain positive integers")
    return value


TemplateSourceListId = Annotated[int, BeforeValidator(_reject_boolean_item_id)]


class ReadingPlanLane(BaseModel):
    """One visual lane in a Reading Plan."""

    id: str = Field(min_length=1, max_length=80)
    name: str = Field(min_length=1, max_length=120)
    display_order: int = Field(ge=0)
    migration_evidence_json: dict[str, object] | None = Field(default=None, exclude_if=lambda v: v is None)


class ReadingPlanLaneWrite(BaseModel):
    """Lane write payload (client-authored, no server metadata)."""

    id: str = Field(min_length=1, max_length=80)
    name: str = Field(min_length=1, max_length=120)
    display_order: int = Field(ge=0)


class ReadingPlanIssue(BaseModel):
    """One Issue occurrence in a Reading Plan."""

    occurrence_id: str = Field(min_length=1, max_length=80)
    issue_id: int = Field(gt=0)
    lane_id: str = Field(min_length=1, max_length=80)
    display_position: int = Field(ge=0)
    label: str | None = Field(default=None, max_length=200)
    reader_role: ReaderRole | None = None
    reader_optional: bool | None = None
    is_checkpoint: bool = False
    source_metadata_json: dict[str, object] | None = None


class ReadingPlanIssueWrite(BaseModel):
    """Issue occurrence write payload."""

    occurrence_id: str = Field(min_length=1, max_length=80)
    issue_id: int = Field(gt=0)
    lane_id: str = Field(min_length=1, max_length=80)
    display_position: int = Field(ge=0)
    label: str | None = Field(default=None, max_length=200)
    reader_role: ReaderRole | None = None
    reader_optional: bool | None = None
    is_checkpoint: bool = False
    source_metadata_json: dict[str, object] | None = None


class ReadingPlanDependency(BaseModel):
    """One Reading Plan's reference to a canonical Dependency edge."""

    dependency_id: int = Field(gt=0)
    explanation: str | None = Field(default=None, max_length=500)


class ReadingPlanDependencyWrite(BaseModel):
    """Dependency reference write payload."""

    dependency_id: int = Field(gt=0)
    explanation: str | None = Field(default=None, max_length=500)


class CBLPlacement(BaseModel):
    """One ordered CBL observation with inseparable provenance."""

    source_path: str
    position: int


class ConvergenceGateTarget(BaseModel):
    """A node a convergence gate waits for."""

    node_type: PlanNodeType
    node_id: str = Field(min_length=1, max_length=80)


def _coerce_convergence_gate(value: object) -> object:
    """Coerce None to empty list for convergence_gate."""
    if value is None:
        return []
    return value


class ReadingPlanSource(BaseModel):
    """Immutable source snapshot for a Reading Plan adoption/import."""

    id: int
    plan_id: int
    raw_source_path: str
    repository: str | None = None
    source_path: str | None = None
    revision_sha: str | None = None
    content_hash: str | None = None
    cbl_source_list_id: int | None = None
    custom_cbl_list_id: int | None = None
    adopted_at: datetime | None = None
    recorded_at: datetime
    metadata_json: dict[str, object] | None = None


class ReadingPlanSourceWrite(BaseModel):
    """Source snapshot write payload."""

    raw_source_path: str = Field(min_length=1, max_length=1000)
    repository: str | None = Field(default=None, max_length=255)
    source_path: str | None = Field(default=None, max_length=1000)
    revision_sha: str | None = Field(default=None, max_length=64)
    content_hash: str | None = Field(default=None, max_length=64)
    cbl_source_list_id: int | None = Field(default=None, gt=0)
    custom_cbl_list_id: int | None = Field(default=None, gt=0)
    adopted_at: datetime | None = None
    metadata_json: dict[str, object] | None = None


class ReadingPlanSourcePlacement(BaseModel):
    """One source-position observation explaining an Issue occurrence."""

    id: int
    plan_id: int
    occurrence_id: str
    source_id: int
    source_position: int | None = None


class ReadingPlanSourcePlacementWrite(BaseModel):
    """Source placement write payload."""

    occurrence_id: str = Field(min_length=1, max_length=80)
    source_id: int = Field(gt=0)
    source_position: int | None = None


class ReadingPlanWrite(BaseModel):
    """Create/replace payload for a normalized Reading Plan."""

    name: str = Field(min_length=1, max_length=200)
    description: str | None = None
    ordering_mode: PlanOrderingMode = "informational"
    lanes: list[ReadingPlanLaneWrite] = Field(min_length=0, max_length=100)
    issues: list[ReadingPlanIssueWrite] = Field(default_factory=list, max_length=1000)
    dependencies: list[ReadingPlanDependencyWrite] = Field(default_factory=list, max_length=500)
    sources: list[ReadingPlanSourceWrite] = Field(default_factory=list, max_length=50)
    source_placements: list[ReadingPlanSourcePlacementWrite] = Field(default_factory=list, max_length=2000)
    presentation_json: dict[str, object] | None = None

    @model_validator(mode="after")
    def validate_structure(self) -> ReadingPlanWrite:
        """Reject duplicate identifiers and malformed ordering before persistence."""
        lane_ids = [lane.id for lane in self.lanes]
        if len(set(lane_ids)) != len(lane_ids):
            raise ValueError("lane ids must be unique")
        lane_orders = [lane.display_order for lane in self.lanes]
        if len(set(lane_orders)) != len(lane_orders):
            raise ValueError("lane display_order values must be unique")
        occurrence_ids = [issue.occurrence_id for issue in self.issues]
        if len(set(occurrence_ids)) != len(occurrence_ids):
            raise ValueError("occurrence_ids must be unique")
        known_lanes = set(lane_ids)
        if any(issue.lane_id not in known_lanes for issue in self.issues):
            raise ValueError("every issue must reference an existing lane")
        positions_by_lane: dict[str, list[int]] = {}
        for issue in self.issues:
            positions_by_lane.setdefault(issue.lane_id, []).append(issue.display_position)
        if any(len(values) != len(set(values)) for values in positions_by_lane.values()):
            raise ValueError("issue display_positions must be unique within each lane")
        if self.ordering_mode == "strict_sequential":
            if len(self.lanes) != 1:
                raise ValueError("strict sequential plans must use exactly one lane")
            positions = sorted(issue.display_position for issue in self.issues)
            if positions != list(range(len(positions))):
                raise ValueError("strict sequential positions must be contiguous starting at zero")
        # Validate checkpoint placement
        for issue in self.issues:
            if issue.is_checkpoint:
                lane_issues = [i for i in self.issues if i.lane_id == issue.lane_id]
                lane_issues.sort(key=lambda i: i.display_position)
                idx = next((i for i, it in enumerate(lane_issues) if it.occurrence_id == issue.occurrence_id), None)
                if idx is None or idx >= len(lane_issues) - 1:
                    raise ValueError(
                        f"checkpoint on occurrence '{issue.occurrence_id}' must have a next issue in the same lane"
                    )
        # Validate source placements reference valid occurrences and sources
        return self


class ReadingPlanResponse(BaseModel):
    """Persisted Reading Plan response with normalized relations."""

    id: int
    user_id: int
    name: str
    description: str | None = None
    ordering_mode: PlanOrderingMode
    lanes: list[ReadingPlanLane]
    issues: list[ReadingPlanIssue]
    dependencies: list[ReadingPlanDependency]
    sources: list[ReadingPlanSource]
    source_placements: list[ReadingPlanSourcePlacement]
    presentation_json: dict[str, object] | None = None
    created_at: datetime
    updated_at: datetime


class ReadingPlanListItem(BaseModel):
    """Compact summary returned by the plans list endpoint."""

    id: int
    name: str
    description: str | None = None
    ordering_mode: PlanOrderingMode
    lane_count: int
    step_count: int
    issue_count: int
    dependency_count: int
    source_count: int
    updated_at: datetime