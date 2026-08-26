"""Recommendation context model for auditability."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import TYPE_CHECKING

from sqlalchemy import Boolean, DateTime, Float, ForeignKey, Index, Integer, JSON, String
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base

if TYPE_CHECKING:
    from app.models.event import Event


class RecommendationContext(Base):
    """Snapshot of the intent-side factor breakdown used at decision time.

    Records the active intent/source/confidence plus compact per-candidate
    reason codes/factors such as ``recent_high_rating``,
    ``same_thread_momentum``, ``confirmed_creator``, ``novel_candidate``,
    ``taste_adjacent``.  Also records the final combined weight after caps.
    Full Taste Bank records or raw ComicVine metadata are NOT serialized.
    Random intent records an explicit contextual bypass; balanced records
    neutrality explicitly.
    """

    __tablename__ = "recommendation_contexts"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    event_id: Mapped[int] = mapped_column(
        ForeignKey("events.id", ondelete="CASCADE"), nullable=False, unique=True
    )
    schema_version: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(UTC)
    )

    # Active intent at decision time
    intent: Mapped[str] = mapped_column(String(30), nullable=False)
    # How the intent was determined (manual, inferred, quiz, default)
    intent_source: Mapped[str] = mapped_column(String(30), nullable=False)
    # Confidence in the intent (0.0 to 1.0)
    intent_confidence: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)

    # Bandwidth at decision time (light, balanced, deep)
    bandwidth: Mapped[str | None] = mapped_column(String(30), nullable=True)
    # How bandwidth was determined
    bandwidth_source: Mapped[str | None] = mapped_column(String(30), nullable=True)
    # Confidence in bandwidth (0.0 to 1.0)
    bandwidth_confidence: Mapped[float | None] = mapped_column(Float, nullable=True)

    # Per-candidate factor breakdown for the selected thread
    # Stored as JSON: list of {candidate_id, factors: [str], weight: float}
    candidate_factors: Mapped[list[dict] | None] = mapped_column(JSON, nullable=True)
    # The final combined weight after caps for the selected candidate
    final_weight: Mapped[float | None] = mapped_column(Float, nullable=True)

    # Explicit flags for special cases
    random_bypass: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    balanced_neutrality: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)

    __table_args__ = (
        Index("ix_recommendation_contexts_event_id", "event_id"),
        Index("ix_recommendation_contexts_created_at", "created_at"),
        Index("ix_recommendation_contexts_intent", "intent"),
    )

    event: Mapped[Event] = relationship("Event", back_populates="recommendation_context_record", lazy="raise")