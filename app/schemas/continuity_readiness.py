"""Structured continuity readiness request and response schemas."""

from typing import Literal

from pydantic import BaseModel, Field

from app.schemas.continuity_rule import ContinuityNodeType, ContinuitySatisfactionType

ContinuityReadinessNodeType = Literal["issue", "thread", "crossover"]
ContinuityChainNodeType = Literal["issue", "crossover"]


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
    satisfied: Literal[False] = False
    causing_issue_ids: list[int] = Field(default_factory=list)
    causing_member_issue_ids: list[int] = Field(default_factory=list)
    note: str | None = None


class ContinuityChainNode(BaseModel):
    """One structured node in a transitive continuity chain."""

    node_type: ContinuityChainNodeType
    node_id: int
    label: str
    is_readable: bool


class ContinuityChain(BaseModel):
    """One deterministic path from blocked content to a readable prerequisite."""

    nodes: list[ContinuityChainNode]


class ContinuityDiagnostic(BaseModel):
    """Structured traversal diagnostic that clients can display without parsing text."""

    code: Literal["cycle_detected", "depth_limit_exceeded", "node_limit_exceeded"]
    node_type: ContinuityChainNodeType
    node_id: int
    limit: int | None = None


class ContinuityReadinessResponse(BaseModel):
    """Machine-readable readiness result with direct and transitive guidance."""

    node_type: ContinuityReadinessNodeType
    node_id: int
    is_readable: bool
    evaluated_issue_id: int | None = None
    blockers: list[ContinuityBlocker] = Field(default_factory=list)
    chains: list[ContinuityChain] = Field(default_factory=list)
    readable_prerequisites: list[ContinuityChainNode] = Field(default_factory=list)
    diagnostics: list[ContinuityDiagnostic] = Field(default_factory=list)
