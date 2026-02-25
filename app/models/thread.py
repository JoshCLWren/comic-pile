"""Thread model for database."""

from datetime import UTC, datetime
from typing import TYPE_CHECKING

from sqlalchemy import Boolean, DateTime, Float, ForeignKey, Index, Integer, JSON, String, Text
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base
from app.models.issue import Issue

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
    # New issue tracking fields (NULL means old system, not migrated yet)
    total_issues: Mapped[int | None] = mapped_column(Integer, nullable=True)
    next_unread_issue_id: Mapped[int | None] = mapped_column(
        ForeignKey("issues.id", ondelete="SET NULL"), nullable=True
    )
    reading_progress: Mapped[str | None] = mapped_column(String(20), nullable=True)
    # Dependency tracking fields (for Phase 3)
    blocked_by_thread_ids: Mapped[list[int] | None] = mapped_column(JSON, nullable=True)
    blocked_by_issue_ids: Mapped[list[int] | None] = mapped_column(JSON, nullable=True)
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
        Index("ix_thread_collection_id", "collection_id"),
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
    issues: Mapped[list["Issue"]] = relationship(
        "Issue",
        back_populates="thread",
        cascade="all, delete-orphan",
        lazy="raise",
        order_by="Issue.issue_number",
        foreign_keys="[Issue.thread_id]",
    )
    next_unread_issue: Mapped["Issue | None"] = relationship(
        "Issue", foreign_keys=[next_unread_issue_id], lazy="raise"
    )

    def uses_issue_tracking(self) -> bool:
        """Check if thread has been migrated to issue tracking.

        Threads with total_issues = NULL use old issues_remaining counter.
        Threads with total_issues != NULL use Issue records.

        Returns:
            True if thread uses Issue tracking, False if using old counter system
        """
        return self.total_issues is not None

    async def get_issues_remaining(self, db: AsyncSession) -> int:
        """Get the count of remaining unread issues.

        For migrated threads, counts unread Issue records.
        For unmigrated threads, returns issues_remaining counter.

        Args:
            db: Database session for querying Issue count

        Returns:
            Number of unread issues
        """
        if self.uses_issue_tracking():
            from sqlalchemy import func, select

            result = await db.execute(
                select(func.count())
                .select_from(Issue)
                .where(Issue.thread_id == self.id)
                .where(Issue.status == "unread")
            )
            return result.scalar() or 0
        return self.issues_remaining

    async def migrate_to_issues(
        self,
        last_issue_read: int,
        total_issues: int,
        db: AsyncSession,
    ) -> "Thread":
        """Migrate a thread from counter-based to issue-based tracking.

        Creates issue records #1 through total_issues.
        Marks #1 through last_issue_read as read.
        Updates thread with issue tracking fields.

        Args:
            last_issue_read: The issue number user just finished reading (e.g., 15)
            total_issues: Total issues in the series (e.g., 25)
            db: Database session

        Returns:
            Updated thread with issue tracking enabled

        Raises:
            ValueError: If last_issue_read < 0 or > total_issues
        """
        from sqlalchemy import select

        if last_issue_read < 0:
            raise ValueError("last_issue_read must be >= 0")
        if last_issue_read > total_issues:
            raise ValueError("last_issue_read cannot exceed total_issues")

        for i in range(1, total_issues + 1):
            status = "read" if i <= last_issue_read else "unread"
            read_at = datetime.now(UTC) if status == "read" else None

            issue = Issue(
                thread_id=self.id,
                issue_number=str(i),
                status=status,
                read_at=read_at,
            )
            db.add(issue)

        self.total_issues = total_issues

        if last_issue_read < total_issues:
            self.reading_progress = "in_progress"

            result = await db.execute(
                select(Issue).where(
                    Issue.thread_id == self.id,
                    Issue.issue_number == str(last_issue_read + 1),
                )
            )
            next_issue = result.scalar_one()
            self.next_unread_issue_id = next_issue.id
        else:
            self.reading_progress = "completed"
            self.next_unread_issue_id = None
            self.status = "completed"

        self.issues_remaining = total_issues - last_issue_read

        await db.flush()

        return self
