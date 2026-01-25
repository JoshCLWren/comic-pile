"""Snapshot-related Pydantic schemas for request/response validation."""

from datetime import datetime

from pydantic import BaseModel


class SnapshotResponse(BaseModel):
    """Schema for snapshot response."""

    id: int
    session_id: int
    created_at: datetime
    description: str | None


class SnapshotsListResponse(BaseModel):
    """Schema for snapshots list response."""

    session_id: int
    snapshots: list[SnapshotResponse]
