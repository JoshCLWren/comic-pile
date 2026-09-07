"""Postgres-backed cache schema for always-on swappable caching.

Provides three tables:
- ``cache_entries``: key-value cache with TTL expiry and namespace partitioning.
- ``cache_generations``: semantic invalidation counters scoped to cache namespaces.
- ``cache_usage``: month-scoped durable command accounting row for quota telemetry.
"""

from __future__ import annotations

from datetime import UTC, datetime

from sqlalchemy import BigInteger, DateTime, Index, PrimaryKeyConstraint, String
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base


class CacheEntry(Base):
    """A single cache entry with namespace/key partitioning and TTL expiry."""

    __tablename__ = "cache_entries"

    namespace: Mapped[str] = mapped_column(String(255), nullable=False)
    cache_key: Mapped[str] = mapped_column(String(255), nullable=False)
    value: Mapped[dict] = mapped_column(JSONB, nullable=False)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(UTC)
    )

    __table_args__ = (
        PrimaryKeyConstraint("namespace", "cache_key"),
        Index("ix_cache_entries_expires_at", "expires_at"),
    )


class CacheGeneration(Base):
    """Per-scope generation counter for semantic cache invalidation."""

    __tablename__ = "cache_generations"

    scope: Mapped[str] = mapped_column(String(255), primary_key=True)
    generation: Mapped[int] = mapped_column(BigInteger, nullable=False, default=0)


class CacheUsage(Base):
    """Month-scoped durable command-count row for quota telemetry.

    Each calendar month gets one row keyed by ``YYYY-MM``.  Multiple Vercel
    instances atomically reserve command blocks via ``INSERT ... ON CONFLICT
    DO UPDATE`` so the aggregate ``commands`` column reflects the true
    month-to-date total without requiring per-command Neon round trips.
    """

    __tablename__ = "cache_usage"

    month: Mapped[str] = mapped_column(String(7), primary_key=True)
    commands: Mapped[int] = mapped_column(BigInteger, nullable=False, default=0)
