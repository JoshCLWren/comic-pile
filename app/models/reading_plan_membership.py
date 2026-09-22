"""Normalized Reading Plan persistence around canonical Issues and Dependencies.

Implements the relational shape from ``docs/READING_GRAPH_PERSISTENCE_DESIGN.md``
section 2 (Chunk 1 of ``docs/READING_GRAPH_IMPLEMENTATION_PLAN.md``):

- ``reading_plan_issues`` is the explicit ReadingPlan-to-Issue join. One Issue
  may belong to many plans, including repeated occurrences with separate
  lane/label context. ``nodes_json`` on ``ContinuityPlan`` remains temporarily
  for compatibility/presentation but is no longer the sole canonical
  membership representation.
- ``reading_plan_dependencies`` links many plans to one canonical executable
  ``Dependency`` edge without single-owner semantics. Plan deletion cascades
  only to plan-local rows, never to shared Issues or Dependencies.
- ``reading_plan_sources`` / ``reading_plan_source_placements`` preserve
  immutable import provenance (raw path, repository, revision, content hash,
  source position) separately from reader presentation. They are never runtime
  authority for Roll.
"""

from __future__ import annotations

from datetime import UTC, datetime

from sqlalchemy import (
    JSON,
    Boolean,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base


class ReadingPlanIssue(Base):
    """One Issue occurrence inside a Reading Plan."""

    __tablename__ = "reading_plan_issues"

    plan_id: Mapped[int] = mapped_column(
        ForeignKey("continuity_plans.id", ondelete="CASCADE"), primary_key=True
    )
    occurrence_id: Mapped[str] = mapped_column(String(80), primary_key=True)
    issue_id: Mapped[int] = mapped_column(
        ForeignKey("issues.id", ondelete="CASCADE"), nullable=False
    )
    lane_id: Mapped[str] = mapped_column(String(80), nullable=False)
    display_position: Mapped[int] = mapped_column(Integer, nullable=False)
    label: Mapped[str | None] = mapped_column(String(200), nullable=True)
    reader_role: Mapped[str | None] = mapped_column(String(32), nullable=True)
    reader_optional: Mapped[bool | None] = mapped_column(Boolean, nullable=True)
    is_checkpoint: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    source_metadata_json: Mapped[dict[str, object] | None] = mapped_column(
        JSON, nullable=True
    )

    __table_args__ = (
        UniqueConstraint(
            "plan_id",
            "lane_id",
            "display_position",
            name="uq_reading_plan_issue_lane_position",
        ),
        Index("ix_reading_plan_issues_plan_issue", "plan_id", "issue_id"),
        Index("ix_reading_plan_issues_issue_id", "issue_id"),
    )


class ReadingPlanDependency(Base):
    """One plan's provenance reference to a canonical Dependency edge.

    The executable edge exists once in ``dependencies``; zero, one, or many
    plans may reference it. Removing a plan only unlinks that plan.
    """

    __tablename__ = "reading_plan_dependencies"

    plan_id: Mapped[int] = mapped_column(
        ForeignKey("continuity_plans.id", ondelete="CASCADE"), primary_key=True
    )
    dependency_id: Mapped[int] = mapped_column(
        ForeignKey("dependencies.id", ondelete="CASCADE"), primary_key=True
    )
    explanation: Mapped[str | None] = mapped_column(String(500), nullable=True)

    __table_args__ = (
        Index("ix_reading_plan_dependencies_dependency_id", "dependency_id"),
    )


class ReadingPlanSource(Base):
    """One immutable import snapshot referenced by a Reading Plan."""

    __tablename__ = "reading_plan_sources"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    plan_id: Mapped[int] = mapped_column(
        ForeignKey("continuity_plans.id", ondelete="CASCADE"), nullable=False
    )
    raw_source_path: Mapped[str] = mapped_column(String(1000), nullable=False)
    repository: Mapped[str | None] = mapped_column(String(255), nullable=True)
    source_path: Mapped[str | None] = mapped_column(String(1000), nullable=True)
    revision_sha: Mapped[str | None] = mapped_column(String(64), nullable=True)
    content_hash: Mapped[str | None] = mapped_column(String(64), nullable=True)
    cbl_source_list_id: Mapped[int | None] = mapped_column(
        ForeignKey("cbl_source_lists.id", ondelete="SET NULL"), nullable=True
    )
    custom_cbl_list_id: Mapped[int | None] = mapped_column(
        ForeignKey("custom_cbl_lists.id", ondelete="SET NULL"), nullable=True
    )
    adopted_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    recorded_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(UTC), nullable=False
    )
    metadata_json: Mapped[dict[str, object] | None] = mapped_column(
        JSON, nullable=True
    )

    __table_args__ = (
        UniqueConstraint(
            "plan_id",
            "raw_source_path",
            "repository",
            "source_path",
            "revision_sha",
            "content_hash",
            name="uq_reading_plan_source_snapshot",
            postgresql_nulls_not_distinct=True,
        ),
        Index("ix_reading_plan_sources_plan_id", "plan_id"),
    )


class ReadingPlanSourcePlacement(Base):
    """One known source-position observation for a plan Issue occurrence."""

    __tablename__ = "reading_plan_source_placements"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    plan_id: Mapped[int] = mapped_column(
        ForeignKey("continuity_plans.id", ondelete="CASCADE"), nullable=False
    )
    occurrence_id: Mapped[str] = mapped_column(String(80), nullable=False)
    plan_source_id: Mapped[int] = mapped_column(
        ForeignKey("reading_plan_sources.id", ondelete="CASCADE"), nullable=False
    )
    source_position: Mapped[int | None] = mapped_column(Integer, nullable=True)

    __table_args__ = (
        UniqueConstraint(
            "plan_id",
            "occurrence_id",
            "plan_source_id",
            "source_position",
            name="uq_reading_plan_source_placement",
            postgresql_nulls_not_distinct=True,
        ),
        Index("ix_reading_plan_source_placements_plan_id", "plan_id"),
        Index("ix_reading_plan_source_placements_source_id", "plan_source_id"),
    )
