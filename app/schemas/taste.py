"""Schemas for taste-signal prompt eligibility (issue #1746).

Provides data structures for the prompt-eligibility engine that determines
when inferred taste patterns are strong enough to ask about. The eligibility
rules are centralized and deterministic, operating on plain signal data
without direct database coupling.
"""

from __future__ import annotations

from datetime import datetime
from enum import StrEnum

from pydantic import BaseModel, ConfigDict, Field


class SignalType(StrEnum):
    """Category of taste signal derived from reading history."""

    CREATOR = "creator"
    CHARACTER = "character"
    TEAM = "team"
    PUBLISHER = "publisher"
    ERA = "era"


class Verdict(StrEnum):
    """User verdict on a previously prompted or inferred signal."""

    CONFIRMED = "confirmed"
    REJECTED = "rejected"
    SOMETIMES = "sometimes"


class TasteSignal(BaseModel):
    """A single inferred or confirmed taste signal.

    This is the input data structure for the prompt-eligibility engine.
    In production these would be persisted in a Taste Bank table; the
    eligibility engine itself is decoupled from storage.

    Attributes:
        user_id: Owning user.
        signal_type: Category of taste signal.
        stable_key: Normalized external/role key (e.g. ``creator:writer:dk``).
        display_name: Human-readable label shown in prompts.
        affinity: Estimated effect size (positive = user rates above baseline).
        confidence: Statistical confidence in the affinity estimate [0, 1].
        evidence_count: Distinct issues/threads contributing evidence.
        evidence_diversity: Distinct threads or runs contributing evidence.
        verdict: Explicit user verdict, or ``None`` if only inferred.
        last_prompted_at: Timestamp of most recent prompt for this signal,
            or ``None`` if never prompted.
        last_rejected_at: Timestamp of most recent rejection, or ``None``.
        is_creator_role: Whether this signal is creator-role-specific
            (writer vs artist distinction).
    """

    model_config = ConfigDict(frozen=True)

    user_id: int
    signal_type: SignalType
    stable_key: str
    display_name: str
    affinity: float
    confidence: float = Field(ge=0.0, le=1.0)
    evidence_count: int = Field(ge=0)
    evidence_diversity: int = Field(ge=0)
    verdict: Verdict | None = None
    last_prompted_at: datetime | None = None
    last_rejected_at: datetime | None = None
    is_creator_role: bool = False


class PromptEligibilityConfig(BaseModel):
    """Thresholds and suppression rules for prompt eligibility.

    All thresholds are deterministic constants; the engine never uses
    heuristics, randomness, or learned parameters.

    Attributes:
        min_evidence_count: Minimum distinct observations before a signal
            can become a prompt candidate.
        min_confidence: Minimum confidence score required.
        min_affinity: Minimum absolute affinity effect size required.
        min_diversity: Minimum distinct threads/runs contributing evidence.
        cooldown_days: Days since last prompt before a signal may be
            re-prompted.
        rejection_suppress_days: Days to suppress a rejected signal before
            it may be reconsidered. Use ``float('inf')`` to suppress
            permanently (the default).
        max_candidates: Maximum number of eligible prompts to return.
    """

    model_config = ConfigDict(frozen=True)

    min_evidence_count: int = Field(default=3, ge=1)
    min_confidence: float = Field(default=0.6, ge=0.0, le=1.0)
    min_affinity: float = Field(default=0.3, ge=0.0)
    min_diversity: int = Field(default=2, ge=1)
    cooldown_days: int = Field(default=14, ge=0)
    rejection_suppress_days: float = Field(default=float("inf"), ge=0)
    max_candidates: int = Field(default=5, ge=1)


class PromptCandidate(BaseModel):
    """A taste signal that passed all eligibility gates.

    Attributes:
        signal: The original taste signal data.
        score: Composite ranking score (higher is more eligible).
        rank: 1-based position in the ranked output list.
    """

    model_config = ConfigDict(frozen=True)

    signal: TasteSignal
    score: float
    rank: int


class PromptEligibilityResult(BaseModel):
    """Result of the prompt-eligibility evaluation.

    Attributes:
        candidates: Ranked list of eligible prompt candidates, strongest first.
        suppressed: Signals that were suppressed due to cooldown or rejection.
        ineligible: Signals that failed threshold gates.
    """

    model_config = ConfigDict(frozen=True)

    candidates: list[PromptCandidate]
    suppressed: list[TasteSignal]
    ineligible: list[TasteSignal]
