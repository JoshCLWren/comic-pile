"""User model for database."""

from datetime import UTC, datetime
from typing import TYPE_CHECKING

from sqlalchemy import Boolean, DateTime, Integer, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base

if TYPE_CHECKING:
    from app.models.revoked_token import RevokedToken
    from app.models.session import Session
    from app.models.thread import Thread


class User(Base):
    """User model."""

    __tablename__ = "users"
    __table_args__ = (UniqueConstraint("email", name="uq_users_email"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    username: Mapped[str] = mapped_column(String(50), unique=True, nullable=False)
    email: Mapped[str | None] = mapped_column(String(255), nullable=True)
    password_hash: Mapped[str | None] = mapped_column(String(255), nullable=True)
    is_admin: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(UTC)
    )

    sessions: Mapped[list["Session"]] = relationship(
        "Session", back_populates="user", cascade="all, delete-orphan", lazy="raise"
    )
    threads: Mapped[list["Thread"]] = relationship(
        "Thread", back_populates="user", cascade="all, delete-orphan", lazy="raise"
    )
    revoked_tokens: Mapped[list["RevokedToken"]] = relationship(
        "RevokedToken", back_populates="user", cascade="all, delete-orphan", lazy="raise"
    )
