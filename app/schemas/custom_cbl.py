"""Request and response contracts for user-authored CBL lists."""

from __future__ import annotations

from datetime import datetime
from typing import Annotated, Literal

from pydantic import BaseModel, Field, field_validator, model_validator

from app.schemas.continuity_plan import ContinuityPlanResponse


class ReadingListEntryIntent(BaseModel):
    """Explicit positional intent for one stable member Issue."""

    gate: Literal["none", "hold", "after_previous"] = "none"
    skipped: bool = False


class ReadingListPredecessorChange(BaseModel):
    """Named before/after requirements that the reader must acknowledge."""

    issue_id: int
    issue_name: str
    before_issue_ids: list[int]
    before_issue_names: list[str]
    after_issue_ids: list[int]
    after_issue_names: list[str]


class CustomCBLWrite(BaseModel):
    """Create or replace one custom CBL and its ordered issue membership."""

    mode: Literal["strict", "loose"] | None = None
    entry_intents: dict[int, ReadingListEntryIntent] | None = None
    confirmed_predecessor_changes: list[ReadingListPredecessorChange] | None = None
    name: str = Field(min_length=1, max_length=200)
    description: str | None = Field(default=None, max_length=2000)
    issue_ids: list[int] = Field(default_factory=list, max_length=1000)
    checkpoint_issue_ids: list[int] | None = Field(default=None, max_length=1000)
    # Omission preserves stored targets for older clients; {} explicitly clears them.
    checkpoint_targets: dict[int, list[Annotated[int, Field(strict=True, gt=0)]]] | None = None

    @field_validator("issue_ids", "checkpoint_issue_ids", mode="before")
    @classmethod
    def reject_boolean_issue_ids(cls, value: object) -> object:
        """Reject JSON booleans before Pydantic can coerce them to integers."""
        if isinstance(value, (list, tuple)) and any(isinstance(item, bool) for item in value):
            raise ValueError("issue ids must contain positive integers")
        return value

    @model_validator(mode="after")
    def validate_write(self) -> CustomCBLWrite:
        """Reject blank names, duplicates, and checkpoint ids outside membership."""
        if not self.name.strip():
            raise ValueError("name must not be blank")
        if any(issue_id <= 0 for issue_id in self.issue_ids):
            raise ValueError("issue_ids must contain positive integers")
        if len(set(self.issue_ids)) != len(self.issue_ids):
            raise ValueError("issue_ids must not contain duplicates")
        if any(issue_id not in self.issue_ids for issue_id in (self.entry_intents or {})):
            raise ValueError("entry_intents must reference members of issue_ids")
        checkpoint_ids = self.checkpoint_issue_ids or []
        if any(issue_id <= 0 for issue_id in checkpoint_ids):
            raise ValueError("checkpoint_issue_ids must contain positive integers")
        if len(set(checkpoint_ids)) != len(checkpoint_ids):
            raise ValueError("checkpoint_issue_ids must not contain duplicates")
        owned = set(self.issue_ids)
        if any(issue_id not in owned for issue_id in checkpoint_ids):
            raise ValueError("checkpoint_issue_ids must be a subset of issue_ids")
        for source, targets in (self.checkpoint_targets or {}).items():
            if source not in owned or any(target not in owned for target in targets):
                raise ValueError("checkpoint endpoints must be members of issue_ids")
            if source in targets or len(targets) != len(set(targets)):
                raise ValueError(
                    "checkpoint targets must be distinct and cannot include the source"
                )
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
    is_checkpoint: bool = False
    gate: Literal["none", "hold", "after_previous"] = "none"
    skipped: bool = False
    checkpoint_target_issue_ids: list[int] = Field(default_factory=list)


class CustomCBLListItem(BaseModel):
    """Compact list-row representation for the custom CBL picker."""

    id: int
    name: str
    description: str | None
    mode: Literal["strict", "loose"] = "loose"
    issue_count: int
    updated_at: datetime


class CustomCBLResponse(CustomCBLListItem):
    """Full custom CBL including its ordered canonical issue references."""

    user_id: int
    created_at: datetime
    entries: list[CustomCBLEntryResponse]
    predecessor_changes: list[ReadingListPredecessorChange] = Field(default_factory=list)


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
    expected_updated_at: datetime | None = Field(
        default=None,
        description=(
            "Optimistic-concurrency token from GET ``updated_at``. When present, "
            "a mismatch returns 409 ``plan_version_conflict``, matching PUT."
        ),
    )


class CustomCBLApplyResponse(ContinuityPlanResponse):
    """Updated Reading Plan after custom CBL material is merged into it."""

    added_issue_ids: list[int]
    skipped_existing_issue_ids: list[int]
