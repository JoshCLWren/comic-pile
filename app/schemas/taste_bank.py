"""Taste Bank Pydantic schemas."""

from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, Field


class TasteSignalResponse(BaseModel):
    """Persisted taste signal summary."""

    id: int
    feature_type: str
    feature_key: str
    display_name: str
    role: str | None = None
    evidence_count: int
    distinct_issue_count: int
    distinct_thread_count: int
    confidence: float
    affinity: float | None = None
    verdict: str
    last_prompted_at: datetime | None = None
    first_seen_at: datetime | None = None
    last_seen_at: datetime | None = None

    model_config = {"from_attributes": True}


class TasteVerdictRequest(BaseModel):
    """Explicit user verdict for a discovered signal."""

    verdict: str = Field(..., description="confirmed | sometimes | rejected")


class TasteDiscoveryResponse(BaseModel):
    """One prompt-eligible discovery card."""

    signal: TasteSignalResponse
    evidence_summary: str
