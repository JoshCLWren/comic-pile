"""Session model for database."""

from datetime import datetime
from typing import TYPE_CHECKING

from sqlalchemy import DateTime, ForeignKey, Integer, String
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base

if TYPE_CHECKING:
    from app.models.event import Event
    from app.models.thread import Thread


class Session(Base):
    """Session model."""

    __tablename__ = "sessions"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    thread_id: Mapped[int] = mapped_column(ForeignKey("threads.id"), nullable=False)
    started_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default="CURRENT_TIMESTAMP"
    )
    ended_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    die_size: Mapped[int] = mapped_column(Integer, nullable=False)
    ladder_path: Mapped[str] = mapped_column(String(200), nullable=False)

    thread: Mapped["Thread"] = relationship("Thread", back_populates="sessions")
    events: Mapped[list["Event"]] = relationship(
        "Event", back_populates="session", cascade="all, delete-orphan"
    )
