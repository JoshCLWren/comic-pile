"""Structured continuity readiness request and response schemas."""

from typing import Literal

from pydantic import BaseModel, Field

from app.schemas.continuity_rule import ContinuityNodeType, ContinuitySatisfactionType

ContinuityReadinessNodeType = Literal["issue", "thread", "crossover"]


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


class ContinuityReadinessResponse(BaseModel):
    """Machine-readable direct readiness result for one requested node."""

    node_type: ContinuityReadinessNodeType
    node_id: int
    is_readable: bool
    evaluated_issue_id: int | None = None
    blockers: list[ContinuityBlocker] = Field(default_factory=list)
