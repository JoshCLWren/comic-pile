"""Stable reader-authored prerequisites and read-only historical provenance."""

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


class PrerequisiteCreate(BaseModel):
    """Create one stable pair; provenance is server-controlled."""

    model_config = ConfigDict(extra="forbid")
    source_issue_id: int = Field(gt=0)
    target_issue_id: int = Field(gt=0)
    note: str | None = Field(default=None, max_length=255)


class PrerequisiteNoteUpdate(BaseModel):
    """Edit reader prose without changing endpoints or classification."""

    model_config = ConfigDict(extra="forbid")
    note: str | None = Field(default=None, max_length=255)


class PrerequisiteResponse(BaseModel):
    """Expose historical uncertainty without claiming approval."""

    model_config = ConfigDict(from_attributes=True)
    id: int
    source_issue_id: int
    target_issue_id: int
    created_at: datetime
    note: str | None
    origin: Literal["reader", "converted"] | None
    classification: Literal["A", "B", "C", "D"] | None
    provenance: str | None
