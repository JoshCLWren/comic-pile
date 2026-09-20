"""Persisted user-authored continuity planning documents."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import TYPE_CHECKING

from sqlalchemy import DateTime, ForeignKey, Index, Integer, JSON, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base

if TYPE_CHECKING:
    from app.models.reading_plan import ReadingPlanDependency, ReadingPlanIssue, ReadingPlanLane, ReadingPlanSource


class ContinuityPlan(Base):
    """A durable editable Reading Plan separate from compiled blocking rules.

    Logical name: ReadingPlan. Physical table name remains continuity_plans for
    migration continuity. JSON fields are retained for compatibility but are no
    longer the canonical membership representation.
    """

    __tablename__ = "continuity_plans"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    ordering_mode: Mapped[str] = mapped_column(String(32), nullable=False, default="informational")
    nodes_json: Mapped[list[dict[str, object]]] = mapped_column(JSON, nullable=False, default=list)
    lanes_json: Mapped[list[dict[str, object]]] = mapped_column(JSON, nullable=False, default=list)
    presentation_json: Mapped[dict[str, object] | None] = mapped_column(JSON, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(UTC), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(UTC),
        onupdate=lambda: datetime.now(UTC),
        nullable=False,
    )

    __table_args__ = (Index("ix_continuity_plans_user_id", "user_id"),)

    # Normalized relational collections
    lanes: Mapped[list[ReadingPlanLane]] = relationship(
        "ReadingPlanLane", back_populates="plan", cascade="all, delete-orphan", lazy="raise"
    )
    issues: Mapped[list[ReadingPlanIssue]] = relationship(
        "ReadingPlanIssue", back_populates="plan", cascade="all, delete-orphan", lazy="raise"
    )
    dependencies: Mapped[list[ReadingPlanDependency]] = relationship(
        "ReadingPlanDependency", back_populates="plan", cascade="all, delete-orphan", lazy="raise"
    )
    sources: Mapped[list[ReadingPlanSource]] = relationship(
        "ReadingPlanSource", back_populates="plan", cascade="all, delete-orphan", lazy="raise"
    )
