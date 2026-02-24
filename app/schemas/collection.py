"""Collection-related Pydantic schemas for request/response validation."""

from datetime import datetime

from pydantic import BaseModel, Field


class CollectionCreate(BaseModel):
    """Schema for creating a collection."""

    name: str = Field(..., min_length=1, max_length=100)
    is_default: bool = False
    position: int = Field(default=0, ge=0)


class CollectionUpdate(BaseModel):
    """Schema for updating a collection."""

    name: str | None = Field(None, min_length=1, max_length=100)
    is_default: bool | None = None
    position: int | None = Field(None, ge=0)


class CollectionResponse(BaseModel):
    """Schema for collection response."""

    id: int
    name: str
    user_id: int
    is_default: bool
    position: int
    created_at: datetime


class CollectionListResponse(BaseModel):
    """Schema for paginated collection list."""

    collections: list[CollectionResponse]
    next_page_token: str | None = None
