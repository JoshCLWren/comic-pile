"""Google-style API error schemas."""

from pydantic import BaseModel, Field


class GoogleError(BaseModel):
    """Google API error payload."""

    code: int
    message: str
    status: str
    # Details is a list of arbitrary dicts, avoid using Any for typing
    details: list[dict] = Field(default_factory=list)


class ErrorResponse(BaseModel):
    """Envelope for Google API errors."""

    error: GoogleError
