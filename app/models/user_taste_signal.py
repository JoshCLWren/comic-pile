"""User Taste Bank signal model for confirmed reading preferences."""

from __future__ import annotations

from datetime import UTC, datetime

from sqlalchemy import (
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base
from comic_pile.recommendation_intent import ALL_VERDICTS


class UserTasteSignal(Base):
    """One persistent Taste Bank signal for a user.

    Phase 7 discovery writes candidate patterns here with explicit verdicts.
    Phase 8 Familiar/Explore weighting reads only these records; explicit
    verdicts are the authority and unconfirmed signals never boost candidates.

    Verdicts:
        - ``confirmed``: user affirmed the pattern (strongest effect).
        - ``sometimes``: user qualified the pattern as occasional (weaker).
        - ``inferred``: discovered but not yet confirmed (no positive effect).
        - ``rejected``: user declined the pattern (never boosts).
    """

    __tablename__ = "user_taste_signals"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[int] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )
    category: Mapped[str] = mapped_column(String(20), nullable=False)
    normalized_key: Mapped[str] = mapped_column(String(200), nullable=False)
    verdict: Mapped[str] = mapped_column(String(20), nullable=False)
    evidence_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
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
            f"verdict IN ({', '.join(repr(v) for v in sorted(ALL_VERDICTS))})",
            name="ck_user_taste_signal_verdict",
        ),
        UniqueConstraint(
            "user_id",
            "category",
            "normalized_key",
            name="uq_user_taste_signal_identity",
        ),
        Index("ix_user_taste_signal_user_id", "user_id"),
    )
