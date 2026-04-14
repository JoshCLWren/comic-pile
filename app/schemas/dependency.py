"""Dependency request/response schemas."""

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field


class DependencyCreate(BaseModel):
    """Schema for creating dependencies."""

    source_type: Literal["thread", "issue"]
    source_id: int
    target_type: Literal["thread", "issue"]
    target_id: int


class DependencyResponse(BaseModel):
    """Schema for dependency payload."""

    id: int
    source_issue_id: int | None = None
    target_issue_id: int | None = None
    is_issue_level: bool = True
    created_at: datetime
    note: str | None = None
    source_label: str | None = None
    target_label: str | None = None
    source_issue_thread_id: int | None = None
    target_issue_thread_id: int | None = None


class DependencyNoteUpdate(BaseModel):
    """Schema for updating a dependency note."""

    note: str | None = Field(None, max_length=255)


class BlockingExplanation(BaseModel):
    """Schema for blocked thread explanation."""

    is_blocked: bool
    blocking_reasons: list[str]


class ThreadDependenciesResponse(BaseModel):
    """Schema for thread dependency listing."""

    blocking: list[DependencyResponse]
    blocked_by: list[DependencyResponse]


class IssueDependencyEdge(BaseModel):
    """Schema for a single issue dependency edge."""

    dependency_id: int
    source_issue_id: int
    source_issue_number: str
    source_thread_id: int
    source_thread_title: str


class IssueDependenciesResponse(BaseModel):
    """Schema for issue-level dependency listing."""

    issue_id: int
    incoming: list[IssueDependencyEdge]
    outgoing: list[IssueDependencyEdge]


class DependencyOrderRequirement(BaseModel):
    """Schema for a single dependency order requirement."""

    issue_id: int
    issue_number: str
    position: int


class DependencyOrderConflict(BaseModel):
    """Schema for a position/dependency order conflict."""

    issue_id: int
    issue_number: str
    position: int
    dependency_requires_before: list[DependencyOrderRequirement]
    conflict: str


class ThreadDependencyOrderCheckResponse(BaseModel):
    """Schema for thread dependency order validation."""

    thread_id: int
    conflicts: list[DependencyOrderConflict]
