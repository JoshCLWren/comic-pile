"""Schemas for user-owned named dependency groups."""

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
        """Require exactly one membership target."""
        if (self.thread_id is None) == (self.issue_id is None):
            raise ValueError("Exactly one of thread_id or issue_id is required")
        return self


class DependencyGroupMemberResponse(BaseModel):
    """One persisted group membership."""

    model_config = ConfigDict(from_attributes=True)

    id: int
    thread_id: int | None
    issue_id: int | None


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
