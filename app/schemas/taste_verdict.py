"""Request and response schemas for explicit Taste Bank verdicts (issue #1749).

The verdict API turns an inferred Taste Bank discovery into an explicit user
decision. Inferred statistics (affinity, confidence, evidence counts) are kept
strictly separate from the explicit verdict: verdict writes never modify them.
"""

from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

TasteSignalType = Literal["creator", "character", "team", "publisher", "era"]
TasteVerdict = Literal["confirmed", "sometimes", "rejected"]


class TasteVerdictRequest(BaseModel):
    """Explicit user verdict on a previously discovered taste signal.

    Attributes:
        verdict: The stable user decision to record for the signal.
    """

    verdict: TasteVerdict


class TasteSignalResponse(BaseModel):
    """Canonical representation of one persisted Taste Bank signal.

    Attributes:
        user_id: Owning user; responses are always scoped to the caller.
        signal_type: Category of the signal (creator, character, team,
            publisher, or era).
        external_key: Stable normalized key of the external feature.
        display_name: Human-readable label for prompts.
        affinity_estimate: Inferred affinity effect size, or ``None`` when
            no inference exists yet. Never modified by verdict writes.
        confidence: Inferred statistical confidence in [0, 1], or ``None``.
            Never modified by verdict writes.
        evidence_count: Distinct issues contributing inference evidence.
            Never modified by verdict writes.
        distinct_thread_count: Distinct threads contributing evidence.
            Never modified by verdict writes.
        user_verdict: Explicit user verdict, or ``None`` when inferred only.
        verdict_at: When the current explicit verdict was recorded.
        first_observed_at: First time this signal was observed for the user.
        last_observed_at: Most recent observation for the user.
        last_prompted_at: Most recent discovery prompt for this signal.
    """

    model_config = ConfigDict(from_attributes=True)

    user_id: int
    signal_type: str
    external_key: str = Field(min_length=1, max_length=255)
    display_name: str = Field(min_length=1, max_length=200)
    affinity_estimate: float | None = None
    confidence: float | None = None
    evidence_count: int = Field(ge=0)
    distinct_thread_count: int = Field(ge=0)
    user_verdict: TasteVerdict | None = None
    verdict_at: datetime | None = None
    first_observed_at: datetime | None = None
    last_observed_at: datetime | None = None
    last_prompted_at: datetime | None = None


class TasteSignalListResponse(BaseModel):
    """All Taste Bank signals owned by the authenticated user.

    Attributes:
        signals: Canonical signals ordered by signal type then external key.
    """

    signals: list[TasteSignalResponse]
