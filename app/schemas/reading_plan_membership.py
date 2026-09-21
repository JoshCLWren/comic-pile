"""Normalized Reading Plan membership request and response schemas."""

from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, Field


class ReadingPlanMemberIssue(BaseModel):
    """One normalized Issue occurrence inside a Reading Plan."""

    occurrence_id: str
    issue_id: int
    lane_id: str
    display_position: int
    label: str | None = None
    reader_role: str | None = None
    reader_optional: bool | None = None
    is_checkpoint: bool = False
    source_metadata: dict[str, object] | None = None


class ReadingPlanDependencyLink(BaseModel):
    """One plan provenance reference to a canonical Dependency edge."""

    dependency_id: int
    source_issue_id: int
    target_issue_id: int
    explanation: str | None = None


class ReadingPlanSourceSnapshot(BaseModel):
    """One preserved import snapshot referenced by a Reading Plan."""

    id: int
    raw_source_path: str
    repository: str | None = None
    source_path: str | None = None
    revision_sha: str | None = None
    content_hash: str | None = None
    adopted_at: datetime | None = None
    recorded_at: datetime


class ReadingPlanSourcePlacementView(BaseModel):
    """One preserved source-position observation for a plan occurrence."""

    id: int
    occurrence_id: str
    plan_source_id: int
    source_position: int | None = None


class ReadingPlanProgress(BaseModel):
    """Plan progress derived from global Issue read state."""

    total_issues: int
    read_issues: int


class ReadingPlanMembershipResponse(BaseModel):
    """Normalized membership, provenance, and progress for one Reading Plan."""

    plan_id: int
    issues: list[ReadingPlanMemberIssue]
    dependencies: list[ReadingPlanDependencyLink]
    sources: list[ReadingPlanSourceSnapshot]
    placements: list[ReadingPlanSourcePlacementView]
    progress: ReadingPlanProgress


class ReadingPlanDependencyLinkRequest(BaseModel):
    """Request to reference one canonical Dependency edge from a plan."""

    explanation: str | None = Field(default=None, max_length=500)
