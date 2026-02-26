"""Migration-related Pydantic schemas."""

from pydantic import BaseModel, Field


class MigrateToIssuesRequest(BaseModel):
    """Schema for migrating thread to issue tracking."""

    last_issue_read: int = Field(
        ..., ge=0, description="The issue number user just finished reading (e.g., 15)"
    )
    total_issues: int = Field(
        ..., ge=1, description="Total number of issues in the series (e.g., 25)"
    )
