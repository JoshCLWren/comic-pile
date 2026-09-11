"""Factual continuity blocker schemas used by Roll and traversal internals."""

from typing import Literal

from pydantic import BaseModel, Field

from app.schemas.continuity_rule import ContinuityNodeType, ContinuitySatisfactionType

ContinuityTargetNodeType = Literal["issue", "thread", "crossover"]
ContinuityBlockerType = Literal[
    "item_unread",
    "members_unread",
    "selected_members_unread",
    "crossover_order",
    "crossover_order_series",
]


class UnreadIssueDetail(BaseModel):
    """Structured label for one unread issue causing a continuity block."""

    issue_id: int
    label: str


class ContinuityBlocker(BaseModel):
    """One unsatisfied continuity constraint with factual blocker evidence."""

    rule_id: int | None = None
    source_type: ContinuityNodeType
    source_id: int
    source_label: str
    satisfaction_type: ContinuitySatisfactionType
    blocker_type: ContinuityBlockerType
    satisfied: Literal[False] = False
    causing_issue_ids: list[int] = Field(default_factory=list)
    causing_member_issue_ids: list[int] = Field(default_factory=list)
    unread_issue_details: list[UnreadIssueDetail] = Field(default_factory=list)
    note: str | None = None
    crossover_id: int | None = None
    sequence_position: int | None = None
