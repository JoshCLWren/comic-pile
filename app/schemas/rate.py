"""Rating-related Pydantic schemas for request/response validation."""

from pydantic import BaseModel, Field


class RateRequest(BaseModel):
    """Schema for rating request."""

    rating: float = Field(..., ge=0.5, le=5.0)
    finish_session: bool = Field(default=False)
    issue_number: int | None = Field(
        default=None, ge=1, description="Issue number just read (triggers migration if provided)"
    )
