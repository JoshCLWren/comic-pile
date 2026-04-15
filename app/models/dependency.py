"""Dependency model for hard-blocking issue roll eligibility."""

from datetime import UTC, datetime
from typing import TYPE_CHECKING

from sqlalchemy import CheckConstraint, DateTime, ForeignKey, Integer, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base

if TYPE_CHECKING:
    from app.models.issue import Issue


class Dependency(Base):
    """A directed dependency edge between issues."""

    __tablename__ = "dependencies"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    source_issue_id: Mapped[int] = mapped_column(
        ForeignKey("issues.id", ondelete="CASCADE"), nullable=False
    )
    target_issue_id: Mapped[int] = mapped_column(
        ForeignKey("issues.id", ondelete="CASCADE"), nullable=False
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(UTC), nullable=False
    )
    note: Mapped[str | None] = mapped_column(String(255), nullable=True)

    __table_args__ = (
        CheckConstraint(
            "source_issue_id IS NOT NULL AND target_issue_id IS NOT NULL",
            name="ck_dependency_exactly_one_type",
        ),
        UniqueConstraint("source_issue_id", "target_issue_id", name="uq_dependency_issue_edge"),
    )

    source_issue: Mapped["Issue"] = relationship(
        "Issue",
        foreign_keys=[source_issue_id],
        back_populates="dependencies_out",
        lazy="raise",
    )
    target_issue: Mapped["Issue"] = relationship(
        "Issue",
        foreign_keys=[target_issue_id],
        back_populates="dependencies_in",
        lazy="raise",
    )
