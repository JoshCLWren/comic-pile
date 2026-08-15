"""Structured continuity readiness request and response schemas."""

from typing import Literal

from pydantic import BaseModel, Field

from app.schemas.continuity_rule import ContinuityNodeType, ContinuitySatisfactionType

ContinuityReadinessNodeType = Literal["issue", "thread", "crossover"]
ContinuityBlockerType = Literal["item_unread", "members_unread", "selected_members_unread"]


class ContinuityReadinessRequest(BaseModel):
    """Request readiness for one owned issue, thread, or crossover."""

    node_type: ContinuityReadinessNodeType
    node_id: int = Field(gt=0)


class ContinuityBlocker(BaseModel):
    """One unsatisfied continuity rule blocking the requested node."""

    rule_id: int
    source_type: ContinuityNodeType
    source_id: int
    source_label: str
    satisfaction_type: ContinuitySatisfactionType
    blocker_type: ContinuityBlockerType
    satisfied: Literal[False] = False
    causing_issue_ids: list[int] = Field(default_factory=list)
    causing_member_issue_ids: list[int] = Field(default_factory=list)
    note: str | None = None


class ContinuityReadinessResponse(BaseModel):
    """Machine-readable direct readiness result for one requested node."""

    node_type: ContinuityReadinessNodeType
    node_id: int
    is_readable: bool
    evaluated_issue_id: int | None = None
    blockers: list[ContinuityBlocker] = Field(default_factory=list)


ContinuityChainNodeType = Literal["issue", "crossover"]
ContinuityChainDiagnosticCode = Literal[
    "cycle_detected",
    "depth_limit_exceeded",
    "node_limit_exceeded",
]


class ContinuityChainNode(BaseModel):
    """One structured node along a prerequisite chain."""

    node_type: ContinuityChainNodeType
    node_id: int
    label: str
    is_readable: bool


class ContinuityChainDiagnostic(BaseModel):
    """One structured traversal failure that does not require text parsing."""

    code: ContinuityChainDiagnosticCode
    node_type: ContinuityChainNodeType
    node_id: int
    limit: int | None = None


class ContinuityChainResponse(BaseModel):
    """Bounded transitive prerequisite chains for one requested node."""

    node_type: ContinuityReadinessNodeType
    node_id: int
    evaluated_issue_id: int | None = None
    direct_blockers: list[ContinuityBlocker] = Field(default_factory=list)
    chains: list[list[ContinuityChainNode]] = Field(default_factory=list)
    readable_prerequisites: list[ContinuityChainNode] = Field(default_factory=list)
    diagnostics: list[ContinuityChainDiagnostic] = Field(default_factory=list)
