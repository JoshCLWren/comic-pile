"""Schemas for reading orders."""

from pydantic import BaseModel


class ReadingOrderItemResponse(BaseModel):
    """Response schema for a single item within a reading order."""

    thread_id: int
    thread_title: str
    position: int
    issue_number: str | None = None
    is_read: bool = False


class ReadingOrderResponse(BaseModel):
    """Response schema for a reading order with items."""

    id: int
    name: str
    description: str | None = None
    total_items: int
    completed_items: int
    items: list[ReadingOrderItemResponse] = []


class ThreadReadingOrdersResponse(BaseModel):
    """Response schema for reading orders containing a specific thread."""

    reading_orders: list[ReadingOrderResponse]
