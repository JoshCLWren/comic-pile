"""Durable reader-owned collection exclusions.

Target identifiers are deliberately not foreign keys to Threads or Issues:
a reader's decision survives deletion of the item it excluded.
"""

from __future__ import annotations

from datetime import UTC, datetime

from sqlalchemy import CheckConstraint, DateTime, ForeignKey, Index, Integer, String, text
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base


class CollectionExclusion(Base):
    """One explicit owner-approved exclusion, independent of list membership."""

    __tablename__ = "collection_exclusions"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[int] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )
    provider: Mapped[str | None] = mapped_column(String(50), nullable=True)
    external_volume_id: Mapped[str | None] = mapped_column(String(100), nullable=True)
    thread_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    issue_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(UTC), nullable=False
    )

    __table_args__ = (
        CheckConstraint(
            "num_nonnulls(external_volume_id, thread_id, issue_id) = 1 "
            "AND (provider IS NULL) = (external_volume_id IS NULL)",
            name="ck_collection_exclusion_exactly_one_target",
        ),
        CheckConstraint(
            "(thread_id IS NULL OR thread_id > 0) AND (issue_id IS NULL OR issue_id > 0)",
            name="ck_collection_exclusion_positive_ids",
        ),
        Index(
            "uq_collection_exclusion_owner_volume",
            "user_id", "provider", "external_volume_id",
            unique=True,
            postgresql_where=text("external_volume_id IS NOT NULL"),
        ),
        Index(
            "uq_collection_exclusion_owner_thread",
            "user_id", "thread_id",
            unique=True,
            postgresql_where=text("thread_id IS NOT NULL"),
        ),
        Index(
            "uq_collection_exclusion_owner_issue",
            "user_id", "issue_id",
            unique=True,
            postgresql_where=text("issue_id IS NOT NULL"),
        ),
        Index("ix_collection_exclusions_user_id", "user_id"),
    )
