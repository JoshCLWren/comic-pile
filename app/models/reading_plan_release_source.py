"""Persisted release sources: explicit user intent that a ComicVine volume feeds new issues into a thread for a reading plan."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import TYPE_CHECKING

from sqlalchemy import Boolean, DateTime, ForeignKey, Index, Integer, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base

if TYPE_CHECKING:
    from app.models.continuity_plan import ContinuityPlan
    from app.models.external_identity import ExternalIdentity
    from app.models.thread import Thread


class ReadingPlanReleaseSource(Base):
    """A subscription linking a reading plan + thread to a confirmed ComicVine volume.

    Identity evidence (which ComicVine volume matches a thread) lives in
    ThreadExternalSeriesMapping. This model records the reader's explicit
    intent that the volume should continue feeding newly released issues
    into the thread for the given plan. It must not overload the mapping
    table.
    """

    __tablename__ = "reading_plan_release_sources"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    plan_id: Mapped[int] = mapped_column(
        ForeignKey("continuity_plans.id", ondelete="CASCADE"), nullable=False
    )
    thread_id: Mapped[int] = mapped_column(
        ForeignKey("threads.id", ondelete="CASCADE"), nullable=False
    )
    external_identity_id: Mapped[int] = mapped_column(
        ForeignKey("external_identities.id", ondelete="CASCADE"), nullable=False
    )
    enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    last_synced_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(UTC), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(UTC),
        onupdate=lambda: datetime.now(UTC),
        nullable=False,
    )

    reading_plan: Mapped[ContinuityPlan] = relationship(
        "ContinuityPlan", back_populates="release_sources", lazy="raise"
    )
    thread: Mapped[Thread] = relationship("Thread", lazy="raise")
    external_identity: Mapped[ExternalIdentity] = relationship(
        "ExternalIdentity", lazy="raise"
    )

    __table_args__ = (
        UniqueConstraint(
            "plan_id",
            "thread_id",
            "external_identity_id",
            name="uq_release_source_once_per_plan_thread_volume",
        ),
        Index("ix_release_sources_plan_id", "plan_id"),
        Index("ix_release_sources_thread_id", "thread_id"),
        Index("ix_release_sources_enabled", "enabled"),
    )
