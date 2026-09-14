"""Request and response contracts for user-authored CBL lists."""

from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, Field, field_validator, model_validator

from app.schemas.continuity_plan import ContinuityPlanResponse


class CustomCBLWrite(BaseModel):
    """Create or replace one custom CBL and its ordered issue membership."""

    name: str = Field(min_length=1, max_length=200)
    description: str | None = Field(default=None, max_length=2000)
    issue_ids: list[int] = Field(default_factory=list, max_length=1000)

    @field_validator("issue_ids", mode="before")
    @classmethod
    def reject_boolean_issue_ids(cls, value: object) -> object:
        """Reject JSON booleans before Pydantic can coerce them to integers."""
        if isinstance(value, (list, tuple)) and any(isinstance(item, bool) for item in value):
            raise ValueError("issue_ids must contain positive integers")
        return value

    @model_validator(mode="after")
    def validate_write(self) -> CustomCBLWrite:
        """Reject blank names, duplicates, and non-positive issue references."""
        if not self.name.strip():
            raise ValueError("name must not be blank")
        if any(issue_id <= 0 for issue_id in self.issue_ids):
            raise ValueError("issue_ids must contain positive integers")
        if len(set(self.issue_ids)) != len(self.issue_ids):
            raise ValueError("issue_ids must not contain duplicates")
        return self


class CustomCBLEntryResponse(BaseModel):
    """One resolved custom CBL entry."""

    id: int
    position: int
    issue_id: int
    thread_id: int
    series_name: str
    issue_number: str
    status: str


class CustomCBLListItem(BaseModel):
    """Compact list-row representation for the custom CBL picker."""

    id: int
    name: str
    description: str | None
    issue_count: int
    updated_at: datetime


class CustomCBLResponse(CustomCBLListItem):
    """Full custom CBL including its ordered canonical issue references."""

    user_id: int
    created_at: datetime
    entries: list[CustomCBLEntryResponse]


class CustomCBLIssueSearchResult(BaseModel):
    """Owned canonical issue candidate available for custom CBL authoring."""

    issue_id: int
    thread_id: int
    series_name: str
    issue_number: str
    status: str


class CustomCBLApplyRequest(BaseModel):
    """Options for explicitly applying a custom CBL to an existing Reading Plan."""

    lane_id: str | None = Field(default=None, min_length=1, max_length=80)


class CustomCBLApplyResponse(ContinuityPlanResponse):
    """Updated Reading Plan after custom CBL material is merged into it."""

    added_issue_ids: list[int]
    skipped_existing_issue_ids: list[int]
