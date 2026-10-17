"""Reader-facing Reading Plan progress, availability, and blocker schemas."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field

from app.schemas.reading_plan_membership import (
    ReadingPlanProgress,
    ReadingPlanSourceSnapshot,
)

ReadingPlanIssueAvailability = Literal["read", "available", "blocked", "later", "excluded", "inactive"]


class ReadingPlanBlocker(BaseModel):
    """One unread Issue required by the current execution authority."""

    issue_id: int
    thread_id: int
    thread_title: str
    issue_number: str
    explanation: str


class ReadingPlanReaderIssue(BaseModel):
    """One plan occurrence with display identity and canonical availability."""

    occurrence_id: str
    issue_id: int
    lane_id: str
    display_position: int
    label: str | None = None
    reader_role: str | None = None
    reader_optional: bool | None = None
    is_checkpoint: bool = False
    issue_number: str
    thread_id: int
    thread_title: str
    status: str
    availability: ReadingPlanIssueAvailability
    blockers: list[ReadingPlanBlocker] = Field(default_factory=list)
    source_paths: list[str] = Field(default_factory=list)


class ReadingPlanReaderLane(BaseModel):
    """One reading lane of ordered plan issues."""

    id: str
    name: str
    order: int
    issues: list[ReadingPlanReaderIssue]


class ReadingPlanReaderResponse(BaseModel):
    """Primary reader view for one Reading Plan."""

    execution_mode: Literal["legacy", "option_e"] = "legacy"
    plan_id: int
    name: str
    ordering_mode: str
    progress: ReadingPlanProgress
    available_now: list[ReadingPlanReaderIssue]
    blocked_next: list[ReadingPlanReaderIssue]
    lanes: list[ReadingPlanReaderLane]
    sources: list[ReadingPlanSourceSnapshot]
