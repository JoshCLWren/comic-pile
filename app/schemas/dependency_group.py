"""Schemas for user-owned named dependency groups."""

from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field, model_validator

from app.schemas.continuity_readiness import ContinuityReadinessResponse
from app.schemas.issue import IssueResponse
from app.schemas.thread import ThreadResponse


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
    sequence_order: int | None = Field(
        default=None,
        ge=1,
        description=(
            "Authoritative position of an issue-level member within the "
            "crossover's reading order. Only issue-level memberships participate "
            "in crossover sequencing; thread memberships ignore this field."
        ),
    )

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


class DependencyGroupOrderItem(BaseModel):
    """One crossover membership assigned a reading-sequence position."""

    issue_id: int = Field(gt=0)
    sequence_order: int = Field(gt=0)


class DependencyGroupOrderUpdate(BaseModel):
    """Set the authoritative ordered reading sequence of a crossover."""

    items: list[DependencyGroupOrderItem] = Field(min_length=1, max_length=1000)


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
    """One persisted group membership with human-readable target metadata.

    ``series_title`` carries the owning thread's title for both membership
    kinds. For issue-level memberships, ``issue_number`` identifies the exact
    issue inside that series. A missing value means the target could not be
    resolved and the client must render a readable fallback instead of raw IDs.

    ``sequence_order`` is the authoritative cross-series reading-order slot for the
    membership inside its group. It is never derived from each issue's
    series-local position, so the crossover sequence stays stable even when
    several series reuse the same local position.
    """

    model_config = ConfigDict(from_attributes=True)

    id: int
    thread_id: int | None
    issue_id: int | None
    sequence_order: int
    series_title: str | None = None
    issue_number: str | None = None


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


class DependencyGroupDetailMemberResponse(BaseModel):
    """Enriched member with thread and issue objects for crossover detail view."""

    membership: DependencyGroupMemberResponse
    thread: ThreadResponse | None = None
    issue: IssueResponse | None = None
    other_crossovers: list[str] = []


class DependencyGroupDetailResponse(BaseModel):
    """Full crossover detail with enriched members, readiness, and linked plans."""

    id: int
    name: str
    created_at: datetime
    memberships: list[DependencyGroupDetailMemberResponse]
    readiness: ContinuityReadinessResponse | None = None
    linked_plans: list[DependencyGroupSummary] = []
