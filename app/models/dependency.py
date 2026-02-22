"""Dependency model for hard-blocking thread roll eligibility."""

from datetime import UTC, datetime
from typing import TYPE_CHECKING

from sqlalchemy import DateTime, ForeignKey, Integer, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base

if TYPE_CHECKING:
    from app.models.thread import Thread


class Dependency(Base):
    """A directed dependency edge: source thread must be completed before target thread."""

    __tablename__ = "dependencies"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    source_thread_id: Mapped[int] = mapped_column(
        ForeignKey("threads.id", ondelete="CASCADE"), nullable=False
    )
    target_thread_id: Mapped[int] = mapped_column(
        ForeignKey("threads.id", ondelete="CASCADE"), nullable=False
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(UTC), nullable=False
    )

    __table_args__ = (
        UniqueConstraint("source_thread_id", "target_thread_id", name="uq_dependency_edge"),
    )

    source_thread: Mapped["Thread"] = relationship(
        "Thread", foreign_keys=[source_thread_id], back_populates="dependencies_out", lazy="raise"
    )
    target_thread: Mapped["Thread"] = relationship(
        "Thread", foreign_keys=[target_thread_id], back_populates="dependencies_in", lazy="raise"
    )
