"""Durable Taste Bank records for inferred and user-confirmed taste signals.

Taste Bank rows are derived/summary state about one user's relationship to a
normalized external feature (creator, character, team, publisher, or
publication era). Raw ratings and events remain the source evidence; every
inferred statistic on a row must stay rebuildable from that history.

Two facts live side by side and never overwrite each other:

- ``affinity_estimate``/``confidence`` are inferred from reading history;
- ``user_verdict`` is an explicit user statement (`confirmed`, `sometimes`,
  or `rejected`) that survives rebuilds, including for signals whose source
  evidence has disappeared.

Rows are unique per ``(user_id, signal_type, external_key)`` so multiple
users and stable external keys stay isolated even when display names change.
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
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base

SIGNAL_CREATOR = "creator"
SIGNAL_CHARACTER = "character"
SIGNAL_TEAM = "team"
SIGNAL_PUBLISHER = "publisher"
SIGNAL_ERA = "era"

SIGNAL_TYPES: tuple[str, ...] = (
    SIGNAL_CREATOR,
    SIGNAL_CHARACTER,
    SIGNAL_TEAM,
    SIGNAL_PUBLISHER,
    SIGNAL_ERA,
)

VERDICT_CONFIRMED = "confirmed"
VERDICT_SOMETIMES = "sometimes"
VERDICT_REJECTED = "rejected"

USER_VERDICTS: tuple[str, ...] = (VERDICT_CONFIRMED, VERDICT_SOMETIMES, VERDICT_REJECTED)


class TasteSignal(Base):
    """One durable per-user taste-signal summary keyed by stable external key.

    A NULL ``user_verdict`` means the row is inferred only. Inferred columns
    are derived state and may be recomputed at any time; verdict columns are
    explicit user state and are only written by user actions.
    """

    __tablename__ = "taste_signals"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[int] = mapped_column(
        Integer,
        ForeignKey("users.id", name="fk_taste_signal_user_id_users", ondelete="CASCADE"),
        nullable=False,
    )
    signal_type: Mapped[str] = mapped_column(String(20), nullable=False)
    external_key: Mapped[str] = mapped_column(String(255), nullable=False)
    display_name: Mapped[str] = mapped_column(String(200), nullable=False)
    affinity_estimate: Mapped[float | None] = mapped_column(Float, nullable=True)
    evidence_count: Mapped[int] = mapped_column(
        Integer, nullable=False, default=0, server_default="0"
    )
    distinct_thread_count: Mapped[int] = mapped_column(
        Integer, nullable=False, default=0, server_default="0"
    )
    confidence: Mapped[float | None] = mapped_column(Float, nullable=True)
    # NULL means inferred-only; explicit verdicts survive rebuilds.
    user_verdict: Mapped[str | None] = mapped_column(String(20), nullable=True)
    verdict_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    first_observed_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    last_observed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    last_prompted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    prompt_suppressed_until: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(UTC), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(UTC),
        onupdate=lambda: datetime.now(UTC),
        nullable=False,
    )

    __table_args__ = (
        CheckConstraint(
            f"signal_type IN ({', '.join(repr(value) for value in SIGNAL_TYPES)})",
            name="ck_taste_signal_signal_type",
        ),
        CheckConstraint(
            f"user_verdict IS NULL OR user_verdict IN "
            f"({', '.join(repr(value) for value in USER_VERDICTS)})",
            name="ck_taste_signal_user_verdict",
        ),
        CheckConstraint(
            "confidence IS NULL OR (confidence >= 0 AND confidence <= 1)",
            name="ck_taste_signal_confidence_range",
        ),
        CheckConstraint(
            "affinity_estimate IS NULL OR (affinity_estimate >= -1 AND affinity_estimate <= 1)",
            name="ck_taste_signal_affinity_range",
        ),
        CheckConstraint(
            "evidence_count >= 0 AND distinct_thread_count >= 0",
            name="ck_taste_signal_evidence_non_negative",
        ),
        UniqueConstraint("user_id", "signal_type", "external_key", name="uq_taste_signal_user_key"),
        Index("ix_taste_signal_user_verdict", "user_id", "user_verdict"),
    )
