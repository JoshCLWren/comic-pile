"""Read-only live eligibility for the complete authored Reading List."""

from typing import Literal

from pydantic import BaseModel, Field

from app.schemas.custom_cbl import CustomCBLEntryResponse
from app.schemas.dependency import BlockingExplanation


class ReadingListReaderEntry(CustomCBLEntryResponse):
    """One current list member with the execution authority's decision."""

    availability: Literal["read", "available", "blocked", "later", "excluded", "inactive", "legacy"]
    explanation: BlockingExplanation | None = None


class ReadingListReaderResponse(BaseModel):
    """Full current list order; never reconstructed from plan membership."""

    list_id: int
    name: str
    mode: Literal["strict", "loose"]
    execution_mode: Literal["legacy", "option_e"]
    entries: list[ReadingListReaderEntry] = Field(default_factory=list)
