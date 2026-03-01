"""Dependency model for hard-blocking thread or issue roll eligibility."""

from datetime import UTC, datetime
from typing import TYPE_CHECKING

from sqlalchemy import CheckConstraint, DateTime, ForeignKey, Integer, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base

if TYPE_CHECKING:
    from app.models.issue import Issue
    from app.models.thread import Thread


class Dependency(Base):
    """A directed dependency edge between threads or issues."""

    __tablename__ = "dependencies"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    source_thread_id: Mapped[int | None] = mapped_column(
        ForeignKey("threads.id", ondelete="CASCADE"), nullable=True
    )
    target_thread_id: Mapped[int | None] = mapped_column(
        ForeignKey("threads.id", ondelete="CASCADE"), nullable=True
    )
    source_issue_id: Mapped[int | None] = mapped_column(
        ForeignKey("issues.id", ondelete="CASCADE"), nullable=True
    )
    target_issue_id: Mapped[int | None] = mapped_column(
        ForeignKey("issues.id", ondelete="CASCADE"), nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(UTC), nullable=False
    )

    __table_args__ = (
        CheckConstraint(
            "(source_thread_id IS NOT NULL AND target_thread_id IS NOT NULL "
            "AND source_issue_id IS NULL AND target_issue_id IS NULL) OR "
            "(source_thread_id IS NULL AND target_thread_id IS NULL "
            "AND source_issue_id IS NOT NULL AND target_issue_id IS NOT NULL)",
            name="ck_dependency_exactly_one_type",
        ),
        UniqueConstraint("source_thread_id", "target_thread_id", name="uq_dependency_thread_edge"),
        UniqueConstraint("source_issue_id", "target_issue_id", name="uq_dependency_issue_edge"),
    )

    source_thread: Mapped["Thread | None"] = relationship(
        "Thread", foreign_keys=[source_thread_id], back_populates="dependencies_out", lazy="raise"
    )
    target_thread: Mapped["Thread | None"] = relationship(
        "Thread", foreign_keys=[target_thread_id], back_populates="dependencies_in", lazy="raise"
    )
    source_issue: Mapped["Issue | None"] = relationship(
        "Issue",
        foreign_keys=[source_issue_id],
        back_populates="dependencies_out",
        lazy="raise",
    )
    target_issue: Mapped["Issue | None"] = relationship(
        "Issue",
        foreign_keys=[target_issue_id],
        back_populates="dependencies_in",
        lazy="raise",
    )
