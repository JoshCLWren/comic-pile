"""Session model for database."""

from datetime import UTC, datetime
from typing import TYPE_CHECKING

from sqlalchemy import DateTime, ForeignKey, Index, Integer, JSON
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base

if TYPE_CHECKING:
    from app.models.event import Event
    from app.models.issue import Issue
    from app.models.snapshot import Snapshot
    from app.models.thread import Thread
    from app.models.user import User


class Session(Base):
    """Session model."""

    __tablename__ = "sessions"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    started_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(UTC)
    )
    ended_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    start_die: Mapped[int] = mapped_column(Integer, default=6)
    manual_die: Mapped[int | None] = mapped_column(Integer, nullable=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), nullable=False)
    pending_thread_id: Mapped[int | None] = mapped_column(
        ForeignKey("threads.id", ondelete="SET NULL"), nullable=True
    )
    pending_issue_id: Mapped[int | None] = mapped_column(
        ForeignKey("issues.id", ondelete="SET NULL"), nullable=True
    )
    pending_thread_updated_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    # Thread IDs temporarily excluded from roll selection during this session
    snoozed_thread_ids: Mapped[list[int] | None] = mapped_column(JSON, nullable=True)

    __table_args__ = (
        Index("ix_session_started_at", "started_at"),
        Index("ix_session_ended_at", "ended_at"),
        Index("ix_session_user_ended_started", "user_id", "ended_at", "started_at"),
    )

    user: Mapped["User"] = relationship("User", back_populates="sessions", lazy="raise")
    pending_thread: Mapped["Thread"] = relationship(
        "Thread", foreign_keys=[pending_thread_id], lazy="raise"
    )
    pending_issue: Mapped["Issue | None"] = relationship(
        "Issue", foreign_keys=[pending_issue_id], lazy="raise"
    )
    events: Mapped[list["Event"]] = relationship(
        "Event", back_populates="session", cascade="all, delete-orphan", lazy="raise"
    )
    snapshots: Mapped[list["Snapshot"]] = relationship(
        "Snapshot", back_populates="session", cascade="all, delete-orphan", lazy="raise"
    )
