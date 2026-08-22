"""SQLAlchemy model for per-user cache generation counters."""

from __future__ import annotations

from typing import TYPE_CHECKING

from sqlalchemy import Integer
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base

if TYPE_CHECKING:
    from app.models.user import User


class CacheGeneration(Base):
    """Per-user cache generation counter for invalidation.

    Incrementing the generation for a user instantly makes all prior
    generation-scoped cached values unreachable without wildcard scans
    or individual key deletions.
    """

    __tablename__ = "cache_generations"

    user_id: Mapped[int] = mapped_column(
        Integer,
        primary_key=True,
        nullable=False,
        autoincrement=False,
    )
    generation: Mapped[int] = mapped_column(Integer, nullable=False, default=0)