"""Bug report request/response schemas."""

from pydantic import BaseModel


class BugReportResponse(BaseModel):
    """Response after successfully creating a bug report issue."""

    issue_url: str
