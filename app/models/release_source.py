"""Explicit reader follow-intent for release sources feeding a Reading Plan.

Implements the durable subscription model from issue #3116: a first-class
record that a specific confirmed ComicVine volume (provider series identity)
should continue feeding newly released issues into a specific existing
Thread **for a specific Reading Plan**.

This model carries *follow intent*, not provider identity evidence and not
issue ownership/acquisition. Identity evidence lives on
``ThreadExternalSeriesMapping``; issue acquisition lives on ``Issue``. This
table only records the reader's durable intent to subscribe.

Invariants enforced here:

- ``uq_reading_plan_release_source`` makes one plan/thread/provider-volume
  subscription unique and retry-safe;
- ``enabled`` is opt-in; a disabled source stops future discovery only and
  never deletes adopted Issues, plan membership, read state, or dependencies;
- the same provider volume may feed more than one Reading Plan without
  duplicating canonical Issues (the join table is plan-scoped; canonical
  Issues are shared by reference through ``reading_plan_issues``).
"""

from __future__ import annotations

from datetime import UTC, datetime

from sqlalchemy import (
    Boolean,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base


class ReadingPlanReleaseSource(Base):
    """One durable subscription from a plan/thread pair to a provider volume.

    The referenced ``external_identity_id`` must be a *series* entity type
    and must already be linked to the target ``thread_id`` through a
    confirmed ``ThreadExternalSeriesMapping``. Ambiguous/candidate mappings
    can never become an automatic release source; the service layer enforces
    that gate before ``enabled`` is accepted.
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
    enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    last_synced_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(UTC), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(UTC),
        onupdate=lambda: datetime.now(UTC),
        nullable=False,
    )

    __table_args__ = (
        UniqueConstraint(
            "plan_id",
            "thread_id",
            "external_identity_id",
            name="uq_reading_plan_release_source",
        ),
        Index("ix_reading_plan_release_sources_plan_id", "plan_id"),
        Index("ix_reading_plan_release_sources_thread_id", "thread_id"),
        Index("ix_reading_plan_release_sources_external_id", "external_identity_id"),
        Index(
            "ix_reading_plan_release_sources_enabled_lookup",
            "plan_id",
            "enabled",
        ),
    )