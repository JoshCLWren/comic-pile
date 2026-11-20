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


class MigrateToIssuesSimpleRequest(BaseModel):
    """Schema for simplified migration (infers total_issues from current state)."""

    issue_number: str = Field(
        ...,
        min_length=1,
        max_length=50,
        description="The issue number user just read (e.g., '5', 'Annual 1')",
    )
