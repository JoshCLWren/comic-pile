"""Pydantic schemas for the keep-alive endpoint."""

from pydantic import BaseModel, Field


class KeepaliveResponse(BaseModel):
    """Response from the Neon warm-pool keep-alive probe."""

    status: str = Field(..., min_length=1)
