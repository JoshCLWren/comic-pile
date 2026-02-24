"""Thread model for database."""

from datetime import UTC, datetime
from typing import TYPE_CHECKING

from sqlalchemy import Boolean, DateTime, Float, ForeignKey, Index, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base

if TYPE_CHECKING:
    from app.models.collection import Collection
    from app.models.dependency import Dependency
    from app.models.event import Event
    from app.models.user import User


class Thread(Base):
    """Thread model."""

    __tablename__ = "threads"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    title: Mapped[str] = mapped_column(String(200), nullable=False)
    format: Mapped[str] = mapped_column(String(50), nullable=False)
    issues_remaining: Mapped[int] = mapped_column(Integer, default=0)
    queue_position: Mapped[int] = mapped_column(Integer, nullable=False)
    status: Mapped[str] = mapped_column(String(20), default="active")
    last_rating: Mapped[float | None] = mapped_column(Float, nullable=True)
    last_activity_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    review_url: Mapped[str | None] = mapped_column(Text, nullable=True)
    last_review_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)
    is_test: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    is_blocked: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(UTC)
    )
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), nullable=False)
    collection_id: Mapped[int | None] = mapped_column(
        ForeignKey("collections.id", ondelete="SET NULL"), nullable=True
    )

    __table_args__ = (
        Index("ix_thread_position", "queue_position"),
        Index("ix_thread_status", "status"),
        Index("ix_thread_last_activity", "last_activity_at"),
        Index("ix_thread_user_status_position", "user_id", "status", "queue_position"),
        Index(
            "ix_thread_user_status_blocked_position",
            "user_id",
            "status",
            "is_blocked",
            "queue_position",
        ),
    )

    user: Mapped["User"] = relationship("User", back_populates="threads", lazy="raise")
    collection: Mapped["Collection | None"] = relationship(
        "Collection", back_populates="threads", lazy="raise", passive_deletes=True
    )
    events: Mapped[list["Event"]] = relationship(
        "Event", back_populates="thread", cascade="all, delete-orphan", lazy="raise"
    )
    dependencies_out: Mapped[list["Dependency"]] = relationship(
        "Dependency",
        foreign_keys="Dependency.source_thread_id",
        back_populates="source_thread",
        cascade="all, delete-orphan",
        lazy="raise",
    )
    dependencies_in: Mapped[list["Dependency"]] = relationship(
        "Dependency",
        foreign_keys="Dependency.target_thread_id",
        back_populates="target_thread",
        cascade="all, delete-orphan",
        lazy="raise",
    )
