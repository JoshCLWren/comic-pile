"""Taste Bank API schemas — Phase 7 discovery response models."""

from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel


class TasteSignalResponse(BaseModel):
    """Persisted taste signal for one user and normalized external feature."""

    id: int
    user_id: int
    signal_type: str
    external_key: str
    display_name: str
    affinity_estimate: float | None = None
    evidence_count: int
    distinct_thread_count: int
    confidence: float | None = None
    user_verdict: str | None = None
    verdict_at: datetime | None = None
    first_observed_at: datetime | None = None
    last_observed_at: datetime | None = None
    last_prompted_at: datetime | None = None
    prompt_suppressed_until: datetime | None = None
    created_at: datetime
    updated_at: datetime


class TasteDiscoveryResponse(BaseModel):
    """A prompt-eligible discovery with a concise evidence summary."""

    signal: TasteSignalResponse
    evidence_summary: str


class TasteVerdictRequest(BaseModel):
    """User verdict for a discovered signal."""

    verdict: str
