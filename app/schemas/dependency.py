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
    created_at: datetime


class BlockingExplanation(BaseModel):
    """Schema for blocked thread explanation."""

    is_blocked: bool
    blocking_reasons: list[str]


class ThreadDependenciesResponse(BaseModel):
    """Schema for thread dependency listing."""

    blocking: list[DependencyResponse]
    blocked_by: list[DependencyResponse]
