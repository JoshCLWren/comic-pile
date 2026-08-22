"""Taste Bank signal model for per-user preference persistence.

A single row is stored per user per signal type. Users without a row resolve to repository
defaults (issue #1398), so existing users do not require a data backfill when
the preference is introduced.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import TYPE_CHECKING

from sqlalchemy import Boolean, DateTime, ForeignKey, Index, Integer, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base
from app.models.user import User


if TYPE_CHECKING:
    from app.models.user import User


class TasteBankSignal(Base):
    """Per-user Taste Bank signal persistence."""

    __tablename__ = "taste_bank_signals"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[int] = mapped_column(
        Integer,
        ForeignKey("users.id", name="fk_taste_bank_signals_user_id_users", ondelete="CASCADE"),
        nullable=False,
        unique=True,
    )
    signal_type: Mapped[str] = mapped_column(String(50), nullable=False)
    verdict: Mapped[str] = mapped_column(String(20), nullable=False)
    evidence: Mapped[str | None] = mapped_column(String(1000), nullable=True)
    recorded_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(UTC), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(UTC), onupdate=lambda: datetime.now(UTC), nullable=False
    )

    user: Mapped[User] = relationship("User", back_populates="taste_bank_signals", uselist=False, lazy="raise")

    __table_args__ = (
        Index("ix_taste_bank_signals_user_id", "user_id"),
        UniqueConstraint("user_id", "signal_type", name="uq_taste_bank_signal"),
    )