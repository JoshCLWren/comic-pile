"""Google-style API error schemas."""

from typing import Any

from pydantic import BaseModel, Field


class GoogleError(BaseModel):
    """Google API error payload."""

    code: int
    message: str
    status: str
    details: list[Any] = Field(default_factory=list)


class ErrorResponse(BaseModel):
    """Envelope for Google API errors."""

    error: GoogleError
