"""Durable per-reader selection choices for one CBL source list.

Reopening an already adopted CBL source must restore the reader's saved
include/exclude choices instead of resetting them to the all-checked first-add
default. The record is scoped to one reader and one shared source list, so it
never mutates the global source catalog and never leaks one reader's choices
to another reader.

``entry_decisions`` maps a CBL source position to the reader's saved decision
for that occurrence. A position that is absent was never decided by the reader
and keeps the source default, which keeps newly published source occurrences
visible on the next review instead of silently inheriting an old choice.
"""

from __future__ import annotations

from datetime import UTC, datetime

from sqlalchemy import DateTime, ForeignKey, Index, Integer, JSON, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base


class CblSourceSelection(Base):
    """One reader's saved include/exclude choices for one CBL source list."""

    __tablename__ = "cbl_source_selections"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    cbl_source_list_id: Mapped[int] = mapped_column(
        ForeignKey("cbl_source_lists.id", ondelete="CASCADE"), nullable=False
    )
    entry_decisions: Mapped[dict[str, bool]] = mapped_column(
        JSON, nullable=False, default=dict, server_default="{}"
    )
    content_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    revision_sha: Mapped[str] = mapped_column(String(64), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(UTC), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(UTC),
        onupdate=lambda: datetime.now(UTC),
        nullable=False,
    )

    __table_args__ = (
        UniqueConstraint(
            "user_id",
            "cbl_source_list_id",
            name="uq_cbl_source_selection_user_list",
        ),
        Index("ix_cbl_source_selection_user_id", "user_id"),
    )
