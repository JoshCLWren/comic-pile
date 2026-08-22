"""UserPreferences model for per-user preference persistence.

A single row is stored per user. Users without a row resolve to repository
defaults (issue #1398), so existing users do not require a data backfill when
the preference is introduced.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import TYPE_CHECKING

from sqlalchemy import DateTime, ForeignKey, Index, Integer, String
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.constants import DEFAULT_THEME
from app.database import Base
from app.models import User, TasteBankSignal


if TYPE_CHECKING:
    from app.models.user import User
    from app.models.taste_bank_signal import TasteBankSignal


class UserPreferences(Base):
    """Per-user UI preferences (e.g., the selected visual theme).

    The ``user_id`` is unique so each user owns exactly one preferences row.
    """

    __tablename__ = "user_preferences"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[int] = mapped_column(
        Integer,
        ForeignKey("users.id", name="fk_user_preferences_user_id_users", ondelete="CASCADE"),
        nullable=False,
        unique=True,
    )
    theme: Mapped[str] = mapped_column(
        String(50), nullable=False, default=DEFAULT_THEME, server_default=DEFAULT_THEME
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

    user: Mapped[User] = relationship(
        "User", back_populates="preferences", uselist=False, lazy="raise"
    )

    # Taste Bank signals - using explicit join condition to avoid circular references
    taste_bank_signals: Mapped[list[TasteBankSignal]] = relationship(
        "TasteBankSignal",
        back_populates="user",
        cascade="all, delete-orphan",
        lazy="selectin",
        primaryjoin=(TasteBankSignal.user_id == user_id)
    )

    __table_args__ = (Index("ix_user_preferences_user_id", "user_id"),)