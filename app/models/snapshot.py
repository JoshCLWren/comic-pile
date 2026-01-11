"""Snapshot model for undo functionality."""

from datetime import UTC, datetime
from typing import TYPE_CHECKING

from sqlalchemy import JSON, ForeignKey, Index, Integer, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base

if TYPE_CHECKING:
    from app.models.event import Event
    from app.models.session import Session


class Snapshot(Base):
    """Snapshot model for storing thread states for undo functionality."""

    __tablename__ = "snapshots"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    session_id: Mapped[int] = mapped_column(ForeignKey("sessions.id"), nullable=False)
    event_id: Mapped[int] = mapped_column(ForeignKey("events.id"), nullable=True)
    thread_states: Mapped[dict] = mapped_column(JSON, nullable=False)
    session_state: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    created_at: Mapped[datetime] = mapped_column(default=lambda: datetime.now(UTC))
    description: Mapped[str | None] = mapped_column(Text, nullable=True)

    __table_args__ = (
        Index("ix_snapshot_session_id", "session_id"),
        Index("ix_snapshot_event_id", "event_id"),
        Index("ix_snapshot_created_at", "created_at"),
    )

    session: Mapped["Session"] = relationship("Session", back_populates="snapshots")
    event: Mapped["Event"] = relationship("Event", back_populates="snapshots")
