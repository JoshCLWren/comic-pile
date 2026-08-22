"""Persistent Taste Bank signals derived from confirmed ComicVine metadata."""

from __future__ import annotations

from datetime import UTC, datetime

from sqlalchemy import CheckConstraint, DateTime, Float, ForeignKey, Index, Integer, JSON, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base


class TasteSignal(Base):
    """Derived taste preference signal for one user and feature value."""

    __tablename__ = "taste_signals"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    feature_type: Mapped[str] = mapped_column(String(20), nullable=False)
    feature_key: Mapped[str] = mapped_column(String(200), nullable=False)
    display_name: Mapped[str] = mapped_column(String(200), nullable=False)
    role: Mapped[str | None] = mapped_column(String(50), nullable=True)
    evidence_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    distinct_issue_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    distinct_thread_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    confidence: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    affinity: Mapped[float | None] = mapped_column(Float, nullable=True)
    verdict: Mapped[str] = mapped_column(String(20), nullable=False, default="inferred")
    evidence_json: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
    first_seen_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=lambda: datetime.now(UTC))
    last_seen_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=lambda: datetime.now(UTC))
    last_prompted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=lambda: datetime.now(UTC))
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(UTC),
        onupdate=lambda: datetime.now(UTC),
    )

    __table_args__ = (
        UniqueConstraint("user_id", "feature_type", "feature_key", name="uq_taste_signal_user_feature"),
        CheckConstraint(
            "feature_type IN ('creator', 'character', 'team', 'publisher', 'era')",
            name="ck_taste_signal_feature_type",
        ),
        CheckConstraint(
            "verdict IN ('inferred', 'confirmed', 'sometimes', 'rejected')",
            name="ck_taste_signal_verdict",
        ),
        Index("ix_taste_signal_user_id", "user_id"),
        Index("ix_taste_signal_user_verdict", "user_id", "verdict"),
        Index("ix_taste_signal_user_type_key", "user_id", "feature_type", "feature_key"),
    )
