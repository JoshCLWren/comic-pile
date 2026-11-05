"""Roll-related Pydantic schemas for request/response validation."""

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from app.schemas.continuity_blocking import ContinuityBlocker
from comic_pile.recommendation_selection import Bandwidth, Intent


class RollRequest(BaseModel):
    """Schema for roll request.

    Optional reading-mode context may be supplied for telemetry and for the
    selection control path. Both fields are neutral-by-default: absent values
    resolve to ``balanced`` and never change legacy unweighted selection.
    """

    model_config = ConfigDict(extra="forbid")

    bandwidth: Bandwidth | None = None
    intent: Intent | None = None


class RollResponse(BaseModel):
    """Schema for roll response."""

    thread_id: int
    title: str
    format: str
    issues_remaining: int
    queue_position: int
    die_size: int
    result: int
    offset: int
    snoozed_count: int
    issue_id: int | None = None
    issue_number: str | None = None
    next_issue_id: int | None = None
    next_issue_number: str | None = None
    total_issues: int | None = None
    reading_progress: str | None = None
    explanation: str | None = None


class SetCurrentIssueRequest(BaseModel):
    """Schema for atomically correcting the current issue in an active thread."""

    model_config = ConfigDict(extra="forbid")

    issue_number: str = Field(..., min_length=1, description="Target issue number to set as current")


class SetCurrentIssueResponse(BaseModel):
    """Response after atomically correcting the current issue."""

    thread_id: int
    title: str
    format: str
    issues_remaining: int
    queue_position: int
    issue_id: int | None = None
    issue_number: str | None = None
    next_issue_id: int | None = None
    next_issue_number: str | None = None
    total_issues: int | None = None
    reading_progress: str | None = None


class OverrideRequest(BaseModel):
    """Schema for manual thread override."""

    thread_id: int


class RollRecoveryPrerequisite(BaseModel):
    """One currently readable prerequisite recommended for a blocked active roll."""

    node_type: Literal["issue", "crossover"]
    node_id: int
    label: str
    is_readable: bool = True


class RollRecoveryChainNode(BaseModel):
    """One labeled issue or crossover step in a prerequisite chain."""

    node_type: Literal["issue", "crossover"]
    node_id: int
    label: str
    is_readable: bool


class RollRecoveryDiagnostic(BaseModel):
    """One bounded-traversal diagnostic suitable for reader-facing explanation."""

    code: Literal["cycle_detected", "depth_limit_exceeded", "node_limit_exceeded"]
    node_type: Literal["issue", "crossover"]
    node_id: int
    limit: int | None = None


class RollRecoveryInfo(BaseModel):
    """Structured recovery context for a pending roll that became blocked."""

    original_thread_id: int
    original_thread_title: str
    direct_blockers: list[ContinuityBlocker] = Field(default_factory=list)
    readable_prerequisites: list[RollRecoveryPrerequisite] = Field(default_factory=list)
    chains: list[list[RollRecoveryChainNode]] = Field(default_factory=list)
    diagnostics: list[RollRecoveryDiagnostic] = Field(default_factory=list)
