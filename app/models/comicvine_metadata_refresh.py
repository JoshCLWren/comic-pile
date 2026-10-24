"""Durable ComicVine issue metadata repair work records.

Issue #4148: a Roll issue can be correctly mapped to a ComicVine issue while its
stored metadata came from a sparse volume-roster row. Those rows contain the
cover image but omit the singular issue relationship fields (``person_credits``,
``story_arc_credits``, ...), so the reader sees no creators. Interactive reads
must not wait on ComicVine, and Vercel may discard a detached ``asyncio`` task
after the response. This table is the durable, idempotent request ledger that a
worker can resume across requests and serverless instances.
"""

from __future__ import annotations

from datetime import UTC, datetime

from sqlalchemy import CheckConstraint, DateTime, ForeignKey, Index, Integer, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base

COMICVINE_METADATA_REFRESH_STATES = (
    "pending",
    "running",
    "completed",
    "no_credits",
    "deferred",
    "failed",
)
"""Allowed durable repair states.

``pending`` and ``running`` are active. ``completed`` means a singular issue
response was persisted with creator credits. ``no_credits`` means a singular
response was persisted and legitimately contains no creator credits. ``deferred``
means a bounded retry is scheduled. ``failed`` means the current retry cycle is
exhausted; a later read may open a fresh cycle after the cooldown.
"""


class ComicVineMetadataRefreshRequest(Base):
    """One durable metadata repair request keyed by external identity."""

    __tablename__ = "comicvine_metadata_refresh_requests"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    external_identity_id: Mapped[int] = mapped_column(
        ForeignKey("external_identities.id", ondelete="CASCADE"),
        nullable=False,
    )
    state: Mapped[str] = mapped_column(String(20), nullable=False, default="pending")
    attempts: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    next_attempt_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        default=lambda: datetime.now(UTC),
    )
    lease_expires_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )
    last_error: Mapped[str | None] = mapped_column(String(200), nullable=True)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        default=lambda: datetime.now(UTC),
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        default=lambda: datetime.now(UTC),
        onupdate=lambda: datetime.now(UTC),
    )

    __table_args__ = (
        CheckConstraint(
            "state IN ('pending', 'running', 'completed', 'no_credits', 'deferred', 'failed')",
            name="ck_comicvine_metadata_refresh_state",
        ),
        UniqueConstraint(
            "external_identity_id",
            name="uq_comicvine_metadata_refresh_identity",
        ),
        Index(
            "ix_comicvine_metadata_refresh_due",
            "state",
            "next_attempt_at",
        ),
    )
