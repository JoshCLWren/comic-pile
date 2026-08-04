"""Named dependency-group persistence models."""

from __future__ import annotations

from datetime import UTC, datetime

from sqlalchemy import CheckConstraint, DateTime, ForeignKey, Index, Integer, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base


class DependencyGroup(Base):
    """User-owned name for a set of related dependency participants."""

    __tablename__ = "dependency_groups"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[int] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )
    name: Mapped[str] = mapped_column(String(120), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(UTC), nullable=False
    )

    memberships: Mapped[list[DependencyGroupMembership]] = relationship(
        "DependencyGroupMembership",
        back_populates="group",
        cascade="all, delete-orphan",
        lazy="selectin",
    )

    __table_args__ = (
        UniqueConstraint("user_id", "name", name="uq_dependency_groups_user_name"),
        Index("ix_dependency_groups_user_id", "user_id"),
    )


class DependencyGroupMembership(Base):
    """Thread- or issue-level membership in a named dependency group."""

    __tablename__ = "dependency_group_memberships"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    group_id: Mapped[int] = mapped_column(
        ForeignKey("dependency_groups.id", ondelete="CASCADE"), nullable=False
    )
    thread_id: Mapped[int | None] = mapped_column(
        ForeignKey("threads.id", ondelete="CASCADE"), nullable=True
    )
    issue_id: Mapped[int | None] = mapped_column(
        ForeignKey("issues.id", ondelete="CASCADE"), nullable=True
    )

    group: Mapped[DependencyGroup] = relationship(
        "DependencyGroup", back_populates="memberships"
    )

    __table_args__ = (
        CheckConstraint(
            "(thread_id IS NOT NULL AND issue_id IS NULL) OR "
            "(thread_id IS NULL AND issue_id IS NOT NULL)",
            name="ck_dependency_group_membership_one_target",
        ),
        UniqueConstraint("group_id", "thread_id", name="uq_dependency_group_thread"),
        UniqueConstraint("group_id", "issue_id", name="uq_dependency_group_issue"),
        Index("ix_dependency_group_memberships_group_id", "group_id"),
        Index("ix_dependency_group_memberships_thread_id", "thread_id"),
        Index("ix_dependency_group_memberships_issue_id", "issue_id"),
    )
