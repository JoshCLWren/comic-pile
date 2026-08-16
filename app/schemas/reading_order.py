"""Schemas for reading orders."""

from pydantic import BaseModel, Field


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


class ReadingOrderSummary(BaseModel):
    """Compact reading order metadata for projection and picker surfaces."""

    id: int
    name: str
    description: str | None = None
    total_items: int = 0


class ReadingOrderListResponse(BaseModel):
    """Response schema for listing all reading orders owned by a user."""

    reading_orders: list[ReadingOrderSummary]


class ReadingOrderProjectionEntry(BaseModel):
    """One row in a projected reading order preview."""

    thread_id: int
    thread_title: str | None
    position: int = Field(ge=1)
    source: str = Field(pattern="^(existing|added|updated)$")
    source_node_id: str | None = None


class ReadingOrderProjectionConflict(BaseModel):
    """A single conflict blocking a projection."""

    code: str = Field(pattern="^(duplicate_thread|missing_thread|non_thread_node)$")
    message: str
    node_id: str
    thread_id: int | None = None
    existing_positions: list[int] = []


class ReadingOrderProjectionPreview(BaseModel):
    """Response contract for the preview endpoint."""

    plan_id: int
    plan_name: str
    plan_ordering_mode: str
    reading_order_id: int
    reading_order_name: str
    entries: list[ReadingOrderProjectionEntry]
    conflicts: list[ReadingOrderProjectionConflict]
    total_positions: int = Field(ge=0)
    dropped_node_ids: list[str] = []


class ReadingOrderProjectionRequest(BaseModel):
    """Request contract for both preview and confirm endpoints."""

    reading_order_id: int = Field(gt=0)


class ReadingOrderProjectionResult(BaseModel):
    """Response contract for the confirm endpoint."""

    plan_id: int
    reading_order_id: int
    added_count: int = Field(ge=0)
    updated_count: int = Field(ge=0)
    kept_count: int = Field(ge=0)
    total_positions: int = Field(ge=0)
