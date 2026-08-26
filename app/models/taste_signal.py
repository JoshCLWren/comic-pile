"""Inferred taste signals backing the Taste Bank.

Each row represents a single taste feature (creator, character, team, publisher,
or era) that has been inferred from a user's reading history.  Signals are
persisted so that explicit user verdicts survive recomputation and so that
the API can serve inferred affinity and confidence without re-running the
full inference pipeline on every request.
"""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import (
    DateTime,
    Float,
    ForeignKey,
    Index,
    Integer,
    String,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base


class TasteSignal(Base):
    """An inferred taste signal for a user.

    Attributes:
        id: Primary key.
        user_id: Owner, denormalized for isolation queries.
        signal_type: Category of the taste feature (e.g. "creator", "character",
            "team", "publisher", "era").
        external_key: Stable normalized key for the feature (e.g. "alan moore",
            "stan lee").
        display_name: Human-readable name for UI display.
        affinity_estimate: Inferred preference strength; positive = aligned,
            negative = opposed, 0 = neutral.
        evidence_count: Total observations supporting this signal.
        distinct_thread_count: Number of distinct threads contributing evidence.
        confidence: How reliable this signal is; 0.0 = too sparse, 1.0 = very
            confident.
        user_verdict: Explicit user verdict when set; overrides inferred
            classification.
        first_observed_at: When this signal was first inferred.
        last_observed_at: When this signal was last observed.
    """

    __tablename__ = "taste_signals"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[int] = mapped_column(
        Integer,
        ForeignKey("users.id", name="fk_taste_signal_user_id_users", ondelete="CASCADE"),
        nullable=False,
    )
    signal_type: Mapped[str] = mapped_column(String(50), nullable=False)
    external_key: Mapped[str] = mapped_column(String(255), nullable=False)
    display_name: Mapped[str] = mapped_column(String(200), nullable=False)
    affinity_estimate: Mapped[float] = mapped_column(Float, nullable=False)
    evidence_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    distinct_thread_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    confidence: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    user_verdict: Mapped[str | None] = mapped_column(
        String(20),
        nullable=True,
    )
    first_observed_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=datetime.now
    )
    last_observed_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=datetime.now
    )

    __table_args__ = (
        UniqueConstraint(
            "user_id",
            "signal_type",
            "external_key",
            name="uq_taste_signal_user_type_key",
        ),
        Index("ix_taste_signal_user_id", "user_id"),
        Index("ix_taste_signal_type_key", "signal_type", "external_key"),
    )