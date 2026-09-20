"""Normalized Reading Plan persistence models.

These tables implement the relational Reading Plan persistence design per
docs/READING_GRAPH_PERSISTENCE_DESIGN.md. They replace JSON-only membership
with ordinary foreign-key relationships while preserving presentation and
provenance metadata.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import TYPE_CHECKING

from sqlalchemy import DateTime, ForeignKey, ForeignKeyConstraint, Index, Integer, JSON, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base

if TYPE_CHECKING:
    from app.models.cbl_reference import CBLSourceList
    from app.models.continuity_plan import ContinuityPlan
    from app.models.custom_cbl import CustomCBLList
    from app.models.dependency import Dependency
    from app.models.issue import Issue


class ReadingPlanLane(Base):
    """One visual lane in a Reading Plan."""

    __tablename__ = "reading_plan_lanes"

    plan_id: Mapped[int] = mapped_column(
        ForeignKey("continuity_plans.id", ondelete="CASCADE"), nullable=False, primary_key=True
    )
    lane_id: Mapped[str] = mapped_column(String(80), nullable=False, primary_key=True)
    name: Mapped[str] = mapped_column(String(120), nullable=False)
    display_order: Mapped[int] = mapped_column(Integer, nullable=False)
    migration_evidence_json: Mapped[dict[str, object] | None] = mapped_column(JSON, nullable=True)

    __table_args__ = (
        UniqueConstraint("plan_id", "display_order", name="uq_reading_plan_lane_display_order"),
        Index("ix_reading_plan_lanes_plan_id", "plan_id"),
    )

    plan: Mapped[ContinuityPlan] = relationship(
        "ContinuityPlan", back_populates="lanes", lazy="raise"
    )
    issues: Mapped[list[ReadingPlanIssue]] = relationship(
        "ReadingPlanIssue", back_populates="lane", cascade="all, delete-orphan", lazy="raise"
    )


class ReadingPlanIssue(Base):
    """One Issue occurrence in a Reading Plan (explicit plan-to-Issue join)."""

    __tablename__ = "reading_plan_issues"

    plan_id: Mapped[int] = mapped_column(
        ForeignKey("continuity_plans.id", ondelete="CASCADE"), nullable=False, primary_key=True
    )
    occurrence_id: Mapped[str] = mapped_column(String(80), nullable=False, primary_key=True)
    issue_id: Mapped[int] = mapped_column(ForeignKey("issues.id", ondelete="CASCADE"), nullable=False)
    lane_id: Mapped[str] = mapped_column(String(80), nullable=False)
    display_position: Mapped[int] = mapped_column(Integer, nullable=False)
    label: Mapped[str | None] = mapped_column(String(200), nullable=True)
    reader_role: Mapped[str | None] = mapped_column(String(32), nullable=True)
    reader_optional: Mapped[bool | None] = mapped_column(nullable=True)
    is_checkpoint: Mapped[bool] = mapped_column(default=False, nullable=False)
    source_metadata_json: Mapped[dict[str, object] | None] = mapped_column(JSON, nullable=True)

    __table_args__ = (
        ForeignKeyConstraint(
            ["plan_id", "lane_id"],
            ["reading_plan_lanes.plan_id", "reading_plan_lanes.lane_id"],
            name="fk_reading_plan_issue_lane",
            ondelete="CASCADE",
        ),
        UniqueConstraint("plan_id", "lane_id", "display_position", name="uq_reading_plan_issue_lane_position"),
        Index("ix_reading_plan_issues_plan_id", "plan_id"),
        Index("ix_reading_plan_issues_issue_id", "issue_id"),
        Index("ix_reading_plan_issues_plan_issue", "plan_id", "issue_id"),
    )

    plan: Mapped[ContinuityPlan] = relationship("ContinuityPlan", back_populates="issues", lazy="raise")
    lane: Mapped[ReadingPlanLane] = relationship("ReadingPlanLane", back_populates="issues", lazy="raise")
    issue: Mapped[Issue] = relationship("Issue", lazy="raise")
    source_placements: Mapped[list[ReadingPlanSourcePlacement]] = relationship(
        "ReadingPlanSourcePlacement", back_populates="occurrence", cascade="all, delete-orphan", lazy="raise"
    )


class ReadingPlanDependency(Base):
    """One Reading Plan's reference to a canonical Dependency edge."""

    __tablename__ = "reading_plan_dependencies"

    plan_id: Mapped[int] = mapped_column(
        ForeignKey("continuity_plans.id", ondelete="CASCADE"), nullable=False, primary_key=True
    )
    dependency_id: Mapped[int] = mapped_column(
        ForeignKey("dependencies.id", ondelete="CASCADE"), nullable=False, primary_key=True
    )
    explanation: Mapped[str | None] = mapped_column(String(500), nullable=True)

    __table_args__ = (
        Index("ix_reading_plan_dependencies_plan_id", "plan_id"),
        Index("ix_reading_plan_dependencies_dependency_id", "dependency_id"),
    )

    plan: Mapped[ContinuityPlan] = relationship("ContinuityPlan", back_populates="dependencies", lazy="raise")
    dependency: Mapped[Dependency] = relationship("Dependency", lazy="raise")


class ReadingPlanSource(Base):
    """Immutable source snapshot for a Reading Plan adoption/import."""

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
    adopted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    recorded_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(UTC), nullable=False
    )
    metadata_json: Mapped[dict[str, object] | None] = mapped_column(JSON, nullable=True)

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
        Index("ix_reading_plan_sources_cbl_list", "cbl_source_list_id"),
        Index("ix_reading_plan_sources_custom_list", "custom_cbl_list_id"),
    )

    plan: Mapped[ContinuityPlan] = relationship("ContinuityPlan", back_populates="sources", lazy="raise")
    cbl_source_list: Mapped[CBLSourceList | None] = relationship("CBLSourceList", lazy="raise")
    custom_cbl_list: Mapped[CustomCBLList | None] = relationship("CustomCBLList", lazy="raise")
    placements: Mapped[list[ReadingPlanSourcePlacement]] = relationship(
        "ReadingPlanSourcePlacement", back_populates="source", cascade="all, delete-orphan", lazy="raise"
    )


class ReadingPlanSourcePlacement(Base):
    """One source-position observation explaining an Issue occurrence."""

    __tablename__ = "reading_plan_source_placements"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    plan_id: Mapped[int] = mapped_column(
        ForeignKey("continuity_plans.id", ondelete="CASCADE"), nullable=False
    )
    occurrence_id: Mapped[str] = mapped_column(String(80), nullable=False)
    source_id: Mapped[int] = mapped_column(
        ForeignKey("reading_plan_sources.id", ondelete="CASCADE"), nullable=False
    )
    source_position: Mapped[int | None] = mapped_column(Integer, nullable=True)

    __table_args__ = (
        ForeignKeyConstraint(
            ["plan_id", "occurrence_id"],
            ["reading_plan_issues.plan_id", "reading_plan_issues.occurrence_id"],
            name="fk_reading_plan_source_placement_occurrence",
            ondelete="CASCADE",
        ),
        ForeignKeyConstraint(
            ["source_id"],
            ["reading_plan_sources.id"],
            name="fk_reading_plan_source_placement_source",
            ondelete="CASCADE",
        ),
        UniqueConstraint(
            "plan_id", "occurrence_id", "source_id", "source_position",
            name="uq_reading_plan_source_placement_unique",
            postgresql_nulls_not_distinct=True,
        ),
        Index("ix_reading_plan_source_placements_plan_id", "plan_id"),
        Index("ix_reading_plan_source_placements_occurrence", "plan_id", "occurrence_id"),
        Index("ix_reading_plan_source_placements_source", "plan_id", "source_id"),
    )

    occurrence: Mapped[ReadingPlanIssue] = relationship(
        "ReadingPlanIssue", back_populates="source_placements", lazy="raise"
    )
    source: Mapped[ReadingPlanSource] = relationship("ReadingPlanSource", back_populates="placements", lazy="raise")