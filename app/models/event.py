"""Event model for database."""

from datetime import datetime
from typing import TYPE_CHECKING

from sqlalchemy import DateTime, Float, ForeignKey, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base

if TYPE_CHECKING:
    from app.models.session import Session
    from app.models.thread import Thread


class Event(Base):
    """Event model."""

    __tablename__ = "events"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    type: Mapped[str] = mapped_column(String(50), nullable=False)
    timestamp: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default="CURRENT_TIMESTAMP"
    )
    die: Mapped[int | None] = mapped_column(Integer, nullable=True)
    result: Mapped[int | None] = mapped_column(Integer, nullable=True)
    selected_thread_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    selection_method: Mapped[str | None] = mapped_column(String(50), nullable=True)
    rating: Mapped[float | None] = mapped_column(Float, nullable=True)
    issues_read: Mapped[int | None] = mapped_column(Integer, nullable=True)
    queue_move: Mapped[str | None] = mapped_column(String(20), nullable=True)
    die_after: Mapped[int | None] = mapped_column(Integer, nullable=True)
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)
    session_id: Mapped[int] = mapped_column(ForeignKey("sessions.id"), nullable=True)
    thread_id: Mapped[int | None] = mapped_column(ForeignKey("threads.id"), nullable=True)

    session: Mapped["Session"] = relationship("Session", back_populates="events")
    thread: Mapped["Thread"] = relationship("Thread", back_populates="events")
