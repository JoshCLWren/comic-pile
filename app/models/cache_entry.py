"""SQLAlchemy model for cached key/value entries."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import TYPE_CHECKING

from sqlalchemy import DateTime, Index, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base

if TYPE_CHECKING:
    pass


class CacheEntry(Base):
    """Persistent key/value cache entry with optional TTL-based expiry."""

    __tablename__ = "cache_entries"

    __table_args__ = (
        Index("ix_cache_entries_expires_at", "expires_at"),
    )

    key: Mapped[str] = mapped_column(String(500), primary_key=True, nullable=False)
    value: Mapped[str] = mapped_column(Text, nullable=False)
    ttl: Mapped[int | None] = mapped_column(Integer, nullable=True)
    expires_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )