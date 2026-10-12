"""Durable one-plan-per-user-per-CBL-list receipts for adoption commit.

The unique constraint is the server-side idempotency guarantee: concurrent
adoption-commit workers and retries after a lost success response converge on
the same Reading Plan instead of creating a second one.
"""

from __future__ import annotations

from datetime import UTC, datetime

from sqlalchemy import DateTime, ForeignKey, Index, Integer, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base


class CblAdoptionReceipt(Base):
    """One adopted CBL source list for one user, pointing at its Reading Plan.

    ``request_fingerprint`` records the last successful commit payload so a
    lost-response retry can replay without writes, while a changed list or
    changed include/exclude choices still merge into this same plan.
    """

    __tablename__ = "cbl_adoption_receipts"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    cbl_source_list_id: Mapped[int] = mapped_column(
        ForeignKey("cbl_source_lists.id", ondelete="CASCADE"), nullable=False
    )
    plan_id: Mapped[int] = mapped_column(
        ForeignKey("continuity_plans.id", ondelete="CASCADE"), nullable=False
    )
    request_fingerprint: Mapped[str] = mapped_column(String(64), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(UTC), nullable=False
    )

    __table_args__ = (
        UniqueConstraint(
            "user_id",
            "cbl_source_list_id",
            name="uq_cbl_adoption_receipt_user_list",
        ),
        Index("ix_cbl_adoption_receipt_plan_id", "plan_id"),
    )
