"""Issue model for tracking individual comic issues."""

from datetime import UTC, datetime
from typing import TYPE_CHECKING

from sqlalchemy import DateTime, ForeignKey, Index, Integer, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base

if TYPE_CHECKING:
    from app.models.dependency import Dependency
    from app.models.thread import Thread
    from app.models.review import Review


class Issue(Base):
    """Individual issue within a thread."""

    __tablename__ = "issues"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    thread_id: Mapped[int] = mapped_column(
        ForeignKey("threads.id", ondelete="CASCADE"), nullable=False
    )
    issue_number: Mapped[str] = mapped_column(String(50), nullable=False)
    position: Mapped[int] = mapped_column(Integer, nullable=False)
    status: Mapped[str] = mapped_column(String(20), default="unread", nullable=False)
    read_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(UTC)
    )

    # Indexes for performance
    __table_args__ = (
        UniqueConstraint("thread_id", "issue_number", name="uq_issue_thread_number"),
        Index("ix_issue_thread_id", "thread_id"),
        Index("ix_issue_thread_is_read", "thread_id", "status"),
        Index("ix_issue_thread_position", "thread_id", "position"),
    )

    thread: Mapped["Thread"] = relationship(
        "Thread", back_populates="issues", lazy="select", foreign_keys=[thread_id]
    )
    dependencies_out: Mapped[list["Dependency"]] = relationship(
        "Dependency",
        foreign_keys="Dependency.source_issue_id",
        back_populates="source_issue",
        lazy="raise",
        passive_deletes=True,
    )
    dependencies_in: Mapped[list["Dependency"]] = relationship(
        "Dependency",
        foreign_keys="Dependency.target_issue_id",
        back_populates="target_issue",
        lazy="raise",
        passive_deletes=True,
    )
    reviews: Mapped[list["Review"]] = relationship(
        "Review", back_populates="issue", lazy="raise", passive_deletes=True
    )
