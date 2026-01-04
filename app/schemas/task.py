"""Pydantic schemas for task API."""

from datetime import datetime

from pydantic import BaseModel, Field


class TaskResponse(BaseModel):
    """Schema for task response."""

    id: int
    task_id: str
    title: str
    description: str | None
    priority: str
    status: str
    dependencies: str | None
    assigned_agent: str | None
    worktree: str | None
    status_notes: str | None
    estimated_effort: str
    completed: bool
    blocked_reason: str | None
    blocked_by: str | None
    last_heartbeat: datetime | None
    instructions: str | None
    created_at: datetime
    updated_at: datetime


class ClaimTaskRequest(BaseModel):
    """Schema for claiming a task."""

    agent_name: str = Field(..., min_length=1)
    worktree: str = Field(..., min_length=1)


class UpdateNotesRequest(BaseModel):
    """Schema for updating status notes."""

    notes: str = Field(..., min_length=1)


class SetStatusRequest(BaseModel):
    """Schema for setting task status."""

    status: str = Field(..., min_length=1)
    blocked_reason: str | None = None
    blocked_by: str | None = None


class UnclaimRequest(BaseModel):
    """Schema for unclaiming a task."""

    agent_name: str = Field(..., min_length=1)


class HeartbeatRequest(BaseModel):
    """Schema for task heartbeat."""

    agent_name: str = Field(..., min_length=1)


class TaskCoordinatorResponse(BaseModel):
    """Schema for coordinator dashboard response."""

    pending: list[TaskResponse]
    in_progress: list[TaskResponse]
    blocked: list[TaskResponse]
    in_review: list[TaskResponse]
    done: list[TaskResponse]


class CreateTaskRequest(BaseModel):
    """Schema for creating a new task."""

    task_id: str = Field(..., min_length=1)
    title: str = Field(..., min_length=1)
    description: str | None = None
    instructions: str | None = None
    priority: str = Field(default="MEDIUM")
    dependencies: str | None = None
    estimated_effort: str | None = None


class SetWorktreeRequest(BaseModel):
    """Schema for setting task worktree (admin only)."""

    worktree: str = Field(..., min_length=1)
