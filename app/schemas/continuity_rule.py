"""Continuity-rule request and response schemas."""

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field, model_validator

ContinuityNodeType = Literal["issue", "crossover"]
ContinuitySatisfactionType = Literal[
    "item_read",
    "all_members_read",
    "checkpoint",
    "selected_members_read",
]


class ContinuityRuleCreate(BaseModel):
    """Schema for creating a generalized continuity rule."""

    source_type: ContinuityNodeType
    source_id: int = Field(gt=0)
    target_type: ContinuityNodeType
    target_id: int = Field(gt=0)
    satisfaction_type: ContinuitySatisfactionType
    checkpoint_issue_id: int | None = Field(default=None, gt=0)
    selected_member_issue_ids: list[int] = Field(default_factory=list, max_length=250)
    note: str | None = Field(default=None, max_length=500)

    @model_validator(mode="after")
    def validate_shape(self) -> "ContinuityRuleCreate":
        """Reject ambiguous satisfaction-policy combinations.

        Returns:
            The validated request.

        Raises:
            ValueError: If node or satisfaction fields form an invalid rule.
        """
        if self.source_type == self.target_type and self.source_id == self.target_id:
            raise ValueError("A continuity rule cannot target its own source node")
        if self.satisfaction_type == "checkpoint":
            if self.checkpoint_issue_id is None:
                raise ValueError("checkpoint_issue_id is required for checkpoint rules")
        elif self.checkpoint_issue_id is not None:
            raise ValueError("checkpoint_issue_id is only valid for checkpoint rules")
        if self.satisfaction_type == "selected_members_read":
            if not self.selected_member_issue_ids:
                raise ValueError("selected-member rules require at least one issue")
        elif self.selected_member_issue_ids:
            raise ValueError("selected_member_issue_ids are only valid for selected-member rules")
        self.selected_member_issue_ids = list(dict.fromkeys(self.selected_member_issue_ids))
        return self


class ContinuityRuleResponse(BaseModel):
    """Schema for a persisted generalized continuity rule."""

    id: int
    user_id: int
    source_type: ContinuityNodeType
    source_id: int
    target_type: ContinuityNodeType
    target_id: int
    satisfaction_type: ContinuitySatisfactionType
    checkpoint_issue_id: int | None
    selected_member_issue_ids: list[int]
    note: str | None
    created_at: datetime
    updated_at: datetime
