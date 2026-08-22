"""Reading-mode schemas: canonical session bandwidth/intent state."""

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

Bandwidth = Literal["light", "balanced", "deep"]
Intent = Literal["balanced", "momentum", "familiar", "explore", "random"]
ModeSource = Literal["inferred", "manual", "snooze"]

BANDWIDTH_LABELS: dict[str, str] = {
    "light": "Light",
    "balanced": "Balanced",
    "deep": "Deep",
}

INTENT_LABELS: dict[str, str] = {
    "balanced": "Balanced",
    "momentum": "Momentum",
    "familiar": "Familiar",
    "explore": "Explore",
    "random": "Random",
}


class SessionModeState(BaseModel):
    """Canonical active reading-mode state for a session."""

    bandwidth: Bandwidth
    bandwidth_source: ModeSource
    bandwidth_confidence: float | None = None
    intent: Intent
    intent_source: ModeSource
    intent_confidence: float | None = None
    mode_version: int


class SessionModeUpdateRequest(BaseModel):
    """Request for explicitly changing the active session mode.

    Both dimensions are optional; omitted dimensions are preserved unchanged.
    At least one dimension must be provided.
    """

    model_config = ConfigDict(extra="forbid")

    bandwidth: Bandwidth | None = None
    intent: Intent | None = None

    @model_validator(mode="after")
    def require_at_least_one_dimension(self) -> SessionModeUpdateRequest:
        """Reject updates that would change nothing."""
        if self.bandwidth is None and self.intent is None:
            raise ValueError("At least one of bandwidth or intent is required")
        return self


class CorrectionOption(BaseModel):
    """One canonical choice offered by the Snooze correction sheet.

    ``bandwidth``/``intent`` carry the canonical values to submit; when neither
    is present, ``confirm_bandwidth`` marks a deliberate confirmation of the
    current bandwidth so the choice still updates canonical session state.
    """

    id: str
    label: str
    bandwidth: Bandwidth | None = None
    intent: Intent | None = None
    confirm_bandwidth: bool = False


class CorrectionGuidance(BaseModel):
    """Structured backend guidance asking the reader to clarify their mode.

    Emitted only when the repeated-mismatch policy concludes the current mode
    may be wrong; the frontend must never invent this state locally.
    """

    suggest_correction: bool
    reason: str | None = None
    options: list[CorrectionOption] = Field(default_factory=list)
