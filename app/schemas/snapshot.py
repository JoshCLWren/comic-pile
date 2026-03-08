"""Snapshot-related Pydantic schemas for request/response validation."""

from datetime import datetime

from pydantic import BaseModel, field_serializer

from app.schemas.session import _to_utc_iso


class SnapshotResponse(BaseModel):
    """Schema for snapshot response."""

    id: int
    session_id: int
    created_at: datetime
    description: str | None

    @field_serializer("created_at")
    def serialize_created_at(self, value: datetime) -> str:
        """Serialize snapshot created_at to ISO 8601 format with timezone.

        Ensures naive datetimes are treated as UTC for consistent serialization.

        Args:
            value: The datetime value to serialize.

        Returns:
            ISO 8601 formatted string with timezone.
        """
        return _to_utc_iso(value)


class SnapshotsListResponse(BaseModel):
    """Schema for snapshots list response."""

    session_id: int
    snapshots: list[SnapshotResponse]
