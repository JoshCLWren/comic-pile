"""Taste Bank models for user taste signal tracking and inference.

Taste Bank records both inferred and user-confirmed preferences derived from
the user's own reading history. Raw ratings and events remain the source
evidence; Taste Bank rows are derived/summary state that must be rebuildable.
"""

from __future__ import annotations

from datetime import UTC, datetime

from sqlalchemy import (
    CheckConstraint,
    DateTime,
    Float,
    ForeignKey,
    Index,
    Integer,
    String,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base


class TasteSignal(Base):
    """One inferred or user-confirmed taste signal for a user.

    Signals capture a user's apparent affinity toward a specific normalized
    feature (creator, character, team, publisher, or publication era).
    Inferred state is distinct from explicit user verdict; explicit verdicts
    are never overwritten by recalculation.

    Attributes:
        user_id: Owner of this signal.
        signal_type: Category of the taste feature.
        stable_key: Normalized stable identifier (external ID or normalized name).
        display_name: Human-readable display for the feature.
        inferred_affinity: Estimated preference strength: positive = aligned,
            negative = opposed, 0.0 = neutral. Range roughly [-1.0, 1.0].
        evidence_count: Total observations supporting this signal.
        distinct_threads_count: Number of distinct threads contributing evidence.
        distinct_runs_count: Number of distinct sessions contributing evidence.
        confidence: How reliable this signal is. 0.0 = too sparse to trust,
            1.0 = very confident. Inferred signals cap at 0.95.
        user_verdict: Explicit user verdict when set: "confirmed" for a
            positively affirmed preference, "sometimes" for mixed reactions,
            "rejected" for an actively disliked preference, or None when
            the signal is purely inferred with no explicit verdict.
        first_observed_at: When evidence for this signal was first seen.
        last_observed_at: When evidence for this signal was most recently seen.
        last_prompted_at: When this signal was last surfaced to the user, or None.
        prompt_suppressed: Whether prompts for this signal are suppressed.
    """

    __tablename__ = "taste_signals"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[int] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )
    signal_type: Mapped[str] = mapped_column(String(20), nullable=False)
    stable_key: Mapped[str] = mapped_column(String(200), nullable=False)
    display_name: Mapped[str] = mapped_column(String(300), nullable=False)
    inferred_affinity: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    evidence_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    distinct_threads_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    distinct_runs_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    confidence: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    user_verdict: Mapped[str | None] = mapped_column(
        String(20), nullable=True, default=None
    )
    first_observed_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    last_observed_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    last_prompted_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    prompt_suppressed: Mapped[bool] = mapped_column(
        Integer, nullable=False, default=0
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(UTC)
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(UTC),
        onupdate=lambda: datetime.now(UTC),
    )

    __table_args__ = (
        CheckConstraint(
            "signal_type IN ('creator', 'character', 'team', 'publisher', 'era')",
            name="ck_taste_signal_type",
        ),
        CheckConstraint(
            "user_verdict IS NULL OR user_verdict IN "
            "('confirmed', 'sometimes', 'rejected')",
            name="ck_taste_signal_verdict",
        ),
        CheckConstraint(
            "confidence >= 0 AND confidence <= 1",
            name="ck_taste_signal_confidence",
        ),
        CheckConstraint(
            "evidence_count >= 0",
            name="ck_taste_signal_evidence_count",
        ),
        CheckConstraint(
            "distinct_threads_count >= 0",
            name="ck_taste_signal_distinct_threads",
        ),
        CheckConstraint(
            "distinct_runs_count >= 0",
            name="ck_taste_signal_distinct_runs",
        ),
        UniqueConstraint(
            "user_id",
            "signal_type",
            "stable_key",
            name="uq_taste_signal_user_type_key",
        ),
        Index("ix_taste_signal_user_id", "user_id"),
        Index("ix_taste_signal_user_confidence", "user_id", "confidence"),
    )


class TasteEvidence(Base):
    """One raw observation contributing to a TasteBank signal.

    Each row records a feature observation from a specific issue rating event,
    supporting rebuildability of derived TasteBank state from source history.

    Attributes:
        taste_signal_id: Parent signal this observation supports.
        user_id: Owner (denormalized for isolation queries).
        signal_type: Feature type denormalized from parent signal.
        stable_key: Stable feature key denormalized from parent signal.
        event_id: Rating event that produced this observation.
        thread_id: Thread where the observed issue lives.
        issue_id: Issue that was rated.
        observed_rating: Rating value from the event.
        observed_at: When the event occurred.
    """

    __tablename__ = "taste_evidence"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    taste_signal_id: Mapped[int] = mapped_column(
        ForeignKey("taste_signals.id", ondelete="CASCADE"), nullable=False
    )
    user_id: Mapped[int] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )
    signal_type: Mapped[str] = mapped_column(String(20), nullable=False)
    stable_key: Mapped[str] = mapped_column(String(200), nullable=False)
    event_id: Mapped[int] = mapped_column(
        ForeignKey("events.id", ondelete="CASCADE"), nullable=False
    )
    thread_id: Mapped[int] = mapped_column(
        ForeignKey("threads.id", ondelete="CASCADE"), nullable=False
    )
    issue_id: Mapped[int | None] = mapped_column(
        ForeignKey("issues.id", ondelete="SET NULL"), nullable=True
    )
    observed_rating: Mapped[float] = mapped_column(Float, nullable=False)
    observed_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False
    )

    __table_args__ = (
        UniqueConstraint(
            "taste_signal_id",
            "event_id",
            name="uq_taste_evidence_signal_event",
        ),
        Index("ix_taste_evidence_user_id", "user_id"),
        Index("ix_taste_evidence_signal_id", "taste_signal_id"),
        Index("ix_taste_evidence_user_signal", "user_id", "signal_type", "stable_key"),
        Index("ix_taste_evidence_event_id", "event_id"),
    )