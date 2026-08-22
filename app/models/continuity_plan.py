"""Persisted user-authored continuity planning documents."""

from __future__ import annotations

from datetime import UTC, datetime

from sqlalchemy import DateTime, ForeignKey, Index, Integer, JSON, String
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base


class ContinuityPlan(Base):
    """A durable editable continuity plan separate from compiled blocking rules."""

    __tablename__ = "continuity_plans"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    ordering_mode: Mapped[str] = mapped_column(String(32), nullable=False, default="informational")
    nodes_json: Mapped[list[dict[str, object]]] = mapped_column(JSON, nullable=False, default=list)
    lanes_json: Mapped[list[dict[str, object]]] = mapped_column(JSON, nullable=False, default=list)
    checkpoints_json: Mapped[list[dict[str, object]]] = mapped_column(JSON, nullable=False, default=list)
    convergence_gates_json: Mapped[list[dict[str, object]]] = mapped_column(
        JSON, nullable=False, default=list
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

    __table_args__ = (Index("ix_continuity_plans_user_id", "user_id"),)
