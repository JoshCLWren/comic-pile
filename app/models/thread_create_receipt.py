"""Durable idempotency receipts for thread creation.

A receipt records one successful ``POST /threads/`` request and the thread it
produced, so a retry or double-submit with the same idempotency key converges
on the same thread instead of creating a duplicate series. Receipts are
durable on purpose: process memory cannot coordinate concurrent API workers.

A reused key with a materially different payload is a 409 conflict, matching
the catalog commit idempotency contract.
"""

from __future__ import annotations

from datetime import UTC, datetime

from sqlalchemy import DateTime, ForeignKey, Index, Integer, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base


class ThreadCreateReceipt(Base):
    """One durable idempotency receipt for a thread creation request."""

    __tablename__ = "thread_create_receipts"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    idempotency_key: Mapped[str] = mapped_column(String(100), nullable=False)
    thread_id: Mapped[int] = mapped_column(
        ForeignKey("threads.id", ondelete="CASCADE"), nullable=False
    )
    request_fingerprint: Mapped[str] = mapped_column(String(64), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(UTC)
    )

    __table_args__ = (
        UniqueConstraint("user_id", "idempotency_key", name="uq_thread_create_receipt_user_key"),
        Index("ix_thread_create_receipt_user_id", "user_id"),
        Index("ix_thread_create_receipt_created_at", "created_at"),
    )
