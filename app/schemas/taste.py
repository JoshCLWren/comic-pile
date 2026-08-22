"""Taste Bank discovery schemas (issue #1750)."""

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

TasteVerdict = Literal["confirmed", "sometimes", "rejected"]


class TasteDiscovery(BaseModel):
    """One prompt-eligible inferred taste pattern shown on Roll."""

    model_config = ConfigDict(from_attributes=True)

    id: int
    feature_type: str
    creator_role: str | None
    label: str
    prompt: str
    evidence_count: int = Field(ge=0)
    distinct_threads: int = Field(ge=0)


class TasteDiscoveryListResponse(BaseModel):
    """Ranked prompt-eligible discoveries for the authenticated user."""

    discoveries: list[TasteDiscovery]
    generated_at: datetime


class TasteVerdictRequest(BaseModel):
    """Explicit reader verdict for a discovered pattern."""

    verdict: TasteVerdict


class TasteSignalResponse(BaseModel):
    """Canonical state of one taste signal after a response."""

    model_config = ConfigDict(from_attributes=True)

    id: int
    feature_type: str
    creator_role: str | None
    label: str
    verdict: TasteVerdict | None
    verdict_at: datetime | None
    dismissed_at: datetime | None
    prompted_at: datetime | None
    prompt_count: int
