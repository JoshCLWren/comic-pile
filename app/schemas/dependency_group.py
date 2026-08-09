"""Schemas for user-owned named dependency groups."""

from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field, model_validator


class DependencyGroupCreate(BaseModel):
    """Create a named dependency group."""

    name: str = Field(min_length=1, max_length=120)


class DependencyGroupUpdate(BaseModel):
    """Rename a named dependency group."""

    name: str = Field(min_length=1, max_length=120)


class DependencyGroupMemberCreate(BaseModel):
    """Add exactly one thread or issue to a group."""

    thread_id: int | None = Field(default=None, gt=0)
    issue_id: int | None = Field(default=None, gt=0)

    @model_validator(mode="after")
    def validate_one_target(self) -> DependencyGroupMemberCreate:
        """Require exactly one membership target.

        Args:
            self: The membership request model being validated.

        Returns:
            The validated membership request model.
        """
        if (self.thread_id is None) == (self.issue_id is None):
            raise ValueError("Exactly one of thread_id or issue_id is required")
        return self


class DependencyGroupIssueRangeCreate(BaseModel):
    """Add a bounded inclusive issue-position range from one owned thread."""

    thread_id: int = Field(gt=0)
    start_position: int = Field(gt=0)
    end_position: int = Field(gt=0)

    @model_validator(mode="after")
    def validate_position_order(self) -> DependencyGroupIssueRangeCreate:
        """Require a forward inclusive range.

        Returns:
            The validated range request.
        """
        if self.end_position < self.start_position:
            raise ValueError("end_position must be greater than or equal to start_position")
        return self


class DependencyGroupMemberResponse(BaseModel):
    """One persisted group membership."""

    model_config = ConfigDict(from_attributes=True)

    id: int
    thread_id: int | None
    issue_id: int | None


class DependencyGroupIssueRangeResponse(BaseModel):
    """Summary of an idempotent issue-range membership operation."""

    thread_id: int
    start_position: int
    end_position: int
    added_issue_ids: list[int]
    already_present_issue_ids: list[int]


class DependencyGroupResponse(BaseModel):
    """A named dependency group with its members."""

    model_config = ConfigDict(from_attributes=True)

    id: int
    name: str
    created_at: datetime
    memberships: list[DependencyGroupMemberResponse]


class DependencyGroupSummary(BaseModel):
    """Compact group metadata for the Roll view."""

    id: int
    name: str
