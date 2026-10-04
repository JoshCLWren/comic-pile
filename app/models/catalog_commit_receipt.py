"""Durable idempotency receipts for catalog series-mapping commits.

A receipt records one material commit request and the logical result it produced, so a retry
of the same request converges on the same answer without duplicating confirmed identities.
Receipts are durable on purpose: process memory cannot coordinate concurrent API workers.

A preview token expires after :data:`app.services.catalog.PREVIEW_TOKEN_TTL_SECONDS`, so a
receipt older than that window can never be replayed by a later request. Retention pruning is
intentionally out of scope here; ``created_at`` is indexed so a future bounded cleanup can
select expired rows cheaply.
"""

from __future__ import annotations

from datetime import UTC, datetime

from sqlalchemy import DateTime, ForeignKey, Index, Integer, JSON, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base


class CatalogCommitReceipt(Base):
    """One durable idempotency receipt for a catalog series-mapping commit."""

    __tablename__ = "catalog_commit_receipts"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    idempotency_key: Mapped[str] = mapped_column(String(100), nullable=False)
    endpoint: Mapped[str] = mapped_column(String(100), nullable=False)
    request_fingerprint: Mapped[str] = mapped_column(String(64), nullable=False)
    response_json: Mapped[dict[str, object]] = mapped_column(JSON, default=dict, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=lambda: datetime.now(UTC))
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(UTC),
        onupdate=lambda: datetime.now(UTC),
    )

    __table_args__ = (
        UniqueConstraint("user_id", "idempotency_key", name="uq_catalog_commit_receipt_user_key"),
        Index("ix_catalog_commit_receipt_user_id", "user_id"),
        Index("ix_catalog_commit_receipt_created_at", "created_at"),
    )