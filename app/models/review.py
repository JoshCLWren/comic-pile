"""Review model for database."""

from datetime import UTC, datetime
from typing import TYPE_CHECKING

from sqlalchemy import DateTime, Float, ForeignKey, Index, Integer, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base

if TYPE_CHECKING:
    from app.models.issue import Issue
    from app.models.thread import Thread
    from app.models.user import User


class Review(Base):
    """Review model for storing user-written reviews for threads/issues."""

    __tablename__ = "reviews"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), nullable=False)
    thread_id: Mapped[int] = mapped_column(
        ForeignKey("threads.id", ondelete="CASCADE"), nullable=False
    )
    issue_id: Mapped[int | None] = mapped_column(
        ForeignKey("issues.id", ondelete="SET NULL"), nullable=True
    )
    rating: Mapped[float] = mapped_column(Float, nullable=False)
    review_text: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(UTC)
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(UTC),
        onupdate=lambda: datetime.now(UTC),
    )

    __table_args__ = (
        Index("ix_review_user_thread_issue", "user_id", "thread_id", "issue_id"),
        Index("ix_review_created_at", "created_at"),
        Index("ix_review_thread_id", "thread_id"),
    )

    user: Mapped["User"] = relationship("User", back_populates="reviews", lazy="raise")
    thread: Mapped["Thread"] = relationship("Thread", back_populates="reviews", lazy="raise")
    issue: Mapped["Issue | None"] = relationship("Issue", back_populates="reviews", lazy="raise")
