"""Dependency request/response schemas."""

from datetime import datetime
from typing import Literal

from pydantic import BaseModel


class DependencyCreate(BaseModel):
    """Schema for creating dependencies."""

    source_type: Literal["thread", "issue"]
    source_id: int
    target_type: Literal["thread", "issue"]
    target_id: int


class DependencyResponse(BaseModel):
    """Schema for dependency payload."""

    id: int
    source_thread_id: int | None
    target_thread_id: int | None
    source_issue_id: int | None
    target_issue_id: int | None
    is_issue_level: bool = False
    created_at: datetime
    source_label: str | None = None
    target_label: str | None = None
    source_issue_thread_id: int | None = None
    target_issue_thread_id: int | None = None


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
