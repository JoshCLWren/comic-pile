"""Response schemas for the Taste Bank discovery card (issue #1750).

The eligibility engine's canonical types live in
``app.schemas.taste`` (issue #1746); this module adds only the API payloads
the discovery card consumes.
"""

from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field


class TasteDiscovery(BaseModel):
    """One prompt-eligible inferred taste pattern shown on Roll."""

    model_config = ConfigDict(from_attributes=True)

    id: int
    signal_type: str
    external_key: str = Field(min_length=1)
    display_name: str
    prompt: str
    evidence_count: int = Field(ge=0)
    distinct_thread_count: int = Field(ge=0)


class TasteDiscoveryListResponse(BaseModel):
    """Ranked prompt-eligible discoveries for the authenticated user."""

    discoveries: list[TasteDiscovery]
    generated_at: datetime
