"""Rating-related Pydantic schemas for request/response validation."""

from pydantic import BaseModel, Field


class RateRequest(BaseModel):
    """Schema for rating request."""

    rating: float = Field(..., ge=0.5, le=5.0)
    finish_session: bool = Field(default=False)
    issue_number: str | None = Field(
        default=None,
        min_length=1,
        max_length=50,
        description="Issue number just read, e.g. '5' or 'Annual 1' (triggers migration if provided)",
    )
