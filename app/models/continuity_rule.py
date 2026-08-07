"""Generalized continuity-rule persistence models."""

from __future__ import annotations

from datetime import UTC, datetime

from sqlalchemy import CheckConstraint, DateTime, ForeignKey, Index, Integer, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base

NODE_TYPES = ("issue", "crossover")
SATISFACTION_TYPES = ("item_read", "all_members_read", "checkpoint", "selected_members_read")


class ContinuityRule(Base):
    """A user-owned directional blocking rule between issue or crossover nodes."""

    __tablename__ = "continuity_rules"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    legacy_dependency_id: Mapped[int | None] = mapped_column(
        ForeignKey("dependencies.id", ondelete="CASCADE"), nullable=True, unique=True
    )
    source_type: Mapped[str] = mapped_column(String(20), nullable=False)
    source_id: Mapped[int] = mapped_column(Integer, nullable=False)
    target_type: Mapped[str] = mapped_column(String(20), nullable=False)
    target_id: Mapped[int] = mapped_column(Integer, nullable=False)
    satisfaction_type: Mapped[str] = mapped_column(String(32), nullable=False)
    checkpoint_issue_id: Mapped[int | None] = mapped_column(
        ForeignKey("issues.id", ondelete="RESTRICT"), nullable=True
    )
    note: Mapped[str | None] = mapped_column(String(500), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(UTC), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(UTC),
        onupdate=lambda: datetime.now(UTC),
        nullable=False,
    )

    selected_members: Mapped[list[ContinuityRuleSelectedMember]] = relationship(
        "ContinuityRuleSelectedMember",
        back_populates="rule",
        cascade="all, delete-orphan",
        lazy="selectin",
    )

    __table_args__ = (
        CheckConstraint("source_type IN ('issue', 'crossover')", name="ck_continuity_rule_source_type"),
        CheckConstraint("target_type IN ('issue', 'crossover')", name="ck_continuity_rule_target_type"),
        CheckConstraint(
            "satisfaction_type IN ('item_read', 'all_members_read', 'checkpoint', 'selected_members_read')",
            name="ck_continuity_rule_satisfaction_type",
        ),
        CheckConstraint(
            "NOT (source_type = target_type AND source_id = target_id)",
            name="ck_continuity_rule_not_self",
        ),
        CheckConstraint(
            "(satisfaction_type = 'checkpoint' AND checkpoint_issue_id IS NOT NULL) OR "
            "(satisfaction_type <> 'checkpoint' AND checkpoint_issue_id IS NULL)",
            name="ck_continuity_rule_checkpoint_shape",
        ),
        UniqueConstraint(
            "user_id", "source_type", "source_id", "target_type", "target_id",
            name="uq_continuity_rule_edge",
        ),
        Index("ix_continuity_rules_user_id", "user_id"),
        Index("ix_continuity_rules_source", "user_id", "source_type", "source_id"),
        Index("ix_continuity_rules_target", "user_id", "target_type", "target_id"),
    )


class ContinuityRuleSelectedMember(Base):
    """An issue required by a selected-members continuity satisfaction policy."""

    __tablename__ = "continuity_rule_selected_members"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    rule_id: Mapped[int] = mapped_column(
        ForeignKey("continuity_rules.id", ondelete="CASCADE"), nullable=False
    )
    issue_id: Mapped[int] = mapped_column(ForeignKey("issues.id", ondelete="CASCADE"), nullable=False)

    rule: Mapped[ContinuityRule] = relationship("ContinuityRule", back_populates="selected_members")

    __table_args__ = (
        UniqueConstraint("rule_id", "issue_id", name="uq_continuity_rule_selected_member"),
        Index("ix_continuity_rule_selected_members_rule_id", "rule_id"),
        Index("ix_continuity_rule_selected_members_issue_id", "issue_id"),
    )
