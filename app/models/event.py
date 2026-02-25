"""Event model for database."""

from datetime import UTC, datetime
from typing import TYPE_CHECKING

from sqlalchemy import DateTime, Float, ForeignKey, Index, Integer, String
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base

if TYPE_CHECKING:
    from app.models.issue import Issue
    from app.models.session import Session
    from app.models.snapshot import Snapshot
    from app.models.thread import Thread


class Event(Base):
    """Tracks discrete actions that occur during reading sessions.

    Events record user interactions with the reading queue system. Each event
    captures a specific action along with relevant metadata like dice values,
    ratings, and thread references.

    Event Types:
        - "roll": A random thread selection. Uses `selected_thread_id` to record
          which thread was picked, `die` for the die size, `result` for the roll
          value, and `selection_method` (e.g., "random").
        - "rate": User rated a reading session. Uses `thread_id` to link to the
          rated thread, `rating` for the score, `issues_read` for progress,
          `die` for current die, and `die_after` for the new die size.
        - "rolled_but_skipped": User rolled but skipped reading. Uses `thread_id`
          to record which pending thread was abandoned.
        - "snooze": User snoozed a thread. Uses `thread_id` to record which
          thread was snoozed, `die` for the die before snooze, and `die_after`
          for the die after stepping up.
        - "unsnooze": User unsnoozed a thread. Uses `thread_id` to record which
          thread was removed from the snoozed list.

    Thread ID Fields:
        This model has two thread reference fields with different purposes:

        - `selected_thread_id`: Stores the ID of a thread selected during a roll.
          Has NO foreign key constraint, allowing historical records to persist
          even if the thread is later deleted. Used only by "roll" events.

        - `thread_id`: A proper foreign key to the threads table. Used by "rate"
          and "rolled_but_skipped" events where we need referential integrity
          and the relationship to the Thread model.
    """

    __tablename__ = "events"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    type: Mapped[str] = mapped_column(String(50), nullable=False)
    timestamp: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(UTC)
    )
    die: Mapped[int | None] = mapped_column(Integer, nullable=True)
    result: Mapped[int | None] = mapped_column(Integer, nullable=True)
    # Thread ID captured at roll time (no FK - allows historical tracking if thread deleted)
    # Used by: "roll" events to record which thread was randomly selected
    selected_thread_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    selection_method: Mapped[str | None] = mapped_column(String(50), nullable=True)
    rating: Mapped[float | None] = mapped_column(Float, nullable=True)
    issues_read: Mapped[int | None] = mapped_column(Integer, nullable=True)
    queue_move: Mapped[str | None] = mapped_column(String(20), nullable=True)
    die_after: Mapped[int | None] = mapped_column(Integer, nullable=True)
    session_id: Mapped[int] = mapped_column(ForeignKey("sessions.id"), nullable=True)
    # Foreign key to threads table for events that act on a thread
    # Used by: "rate" events (thread that was read) and "rolled_but_skipped" events
    thread_id: Mapped[int | None] = mapped_column(ForeignKey("threads.id"), nullable=True)
    issue_id: Mapped[int | None] = mapped_column(
        ForeignKey("issues.id", ondelete="SET NULL"), nullable=True
    )
    issue_number: Mapped[str | None] = mapped_column(String(50), nullable=True)

    __table_args__ = (
        Index("ix_event_session_id", "session_id"),
        Index("ix_event_timestamp", "timestamp"),
        Index("ix_event_session_type_timestamp", "session_id", "type", "timestamp"),
        Index("ix_event_session_type_die_after", "session_id", "type", "die_after"),
    )

    session: Mapped["Session"] = relationship("Session", back_populates="events", lazy="raise")
    thread: Mapped["Thread"] = relationship("Thread", back_populates="events", lazy="raise")
    issue: Mapped["Issue | None"] = relationship("Issue", foreign_keys=[issue_id], lazy="raise")
    snapshots: Mapped[list["Snapshot"]] = relationship(
        "Snapshot", back_populates="event", cascade="all, delete-orphan", lazy="raise"
    )
