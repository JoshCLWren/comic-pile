"""Bug report request/response schemas."""

from pydantic import BaseModel, Field


class BugReportCreate(BaseModel):
    """Request schema for creating a bug report."""

    title: str = Field(..., min_length=1, max_length=200)
    description: str = Field(..., min_length=1, max_length=2000)
    diagnostics: dict | None = None


class BugReportResponse(BaseModel):
    """Response after successfully creating a bug report issue."""

    issue_url: str
