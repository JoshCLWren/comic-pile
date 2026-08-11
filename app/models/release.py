"""Database-backed release ledger for user-facing What's New entries."""

from __future__ import annotations

from datetime import UTC, datetime

from sqlalchemy import CheckConstraint, DateTime, Index, Integer, JSON, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base


class Release(Base):
    """One durable release record, optionally backed by a merged GitHub pull request."""

    __tablename__ = "releases"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    source_repository: Mapped[str] = mapped_column(String(255), nullable=False)
    source_pr_number: Mapped[int | None] = mapped_column(Integer, nullable=True)
    source_merge_sha: Mapped[str | None] = mapped_column(String(64), nullable=True)
    merged_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    released_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    category: Mapped[str] = mapped_column(String(100), nullable=False)
    title: Mapped[str] = mapped_column(String(255), nullable=False)
    summary: Mapped[str] = mapped_column(Text, nullable=False)
    body: Mapped[str | None] = mapped_column(Text, nullable=True)
    visibility: Mapped[str] = mapped_column(String(20), nullable=False, default="public")
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="published")
    sort_order: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    provenance_json: Mapped[dict[str, object]] = mapped_column(JSON, nullable=False, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=lambda: datetime.now(UTC))
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(UTC),
        onupdate=lambda: datetime.now(UTC),
    )

    __table_args__ = (
        CheckConstraint("visibility IN ('public', 'internal')", name="ck_release_visibility"),
        CheckConstraint("status IN ('draft', 'published', 'retracted')", name="ck_release_status"),
        UniqueConstraint("source_repository", "source_pr_number", name="uq_release_source_pr"),
        UniqueConstraint("source_repository", "source_merge_sha", name="uq_release_source_merge_sha"),
        Index("ix_release_published_order", "status", "visibility", "released_at", "sort_order", "id"),
    )
