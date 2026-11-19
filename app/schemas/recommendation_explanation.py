"""Pydantic schemas for recommendation explanation API responses."""

from __future__ import annotations

from pydantic import BaseModel


class ExplainableFactorResponse(BaseModel):
    """One human-readable explanation element returned by the API.

    Attributes:
        code: Stable machine-readable code identifying the factor family.
        label: Short user-facing description.
        detail: Optional extended context or sub-note.
    """

    code: str
    label: str
    detail: str | None = None


class RecommendationExplanationResponse(BaseModel):
    """Aggregate recommendation explanation for a single roll event.

    Attributes:
        event_id: The roll event whose recommendation context was explained.
        factors: Ordered list of human-readable explanation elements derived
            from the persisted decision-time context. Up to ``MAX_EXPLANATIONS``
            factors are returned, ordered deterministically by factor family.
    """

    event_id: int
    factors: list[ExplainableFactorResponse]