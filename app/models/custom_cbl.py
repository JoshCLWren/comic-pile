"""User-authored CBL lists that reference canonical ComicPile issues."""

from __future__ import annotations

from datetime import UTC, datetime

from sqlalchemy import DateTime, ForeignKey, Index, Integer, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base


class CustomCBLList(Base):
    """One user-owned editable comic reading list.

    Custom CBLs are reader-authored source material. They do not own Roll
    eligibility or reader intent; a Reading Plan does that after explicit
    application of the list.
    """

    __tablename__ = "custom_cbl_lists"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[int] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
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
        Index("ix_custom_cbl_lists_user_updated", "user_id", "updated_at"),
    )


class CustomCBLEntry(Base):
    """One ordered canonical issue reference in a custom CBL."""

    __tablename__ = "custom_cbl_entries"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    list_id: Mapped[int] = mapped_column(
        ForeignKey("custom_cbl_lists.id", ondelete="CASCADE"), nullable=False
    )
    issue_id: Mapped[int] = mapped_column(
        ForeignKey("issues.id", ondelete="CASCADE"), nullable=False
    )
    position: Mapped[int] = mapped_column(Integer, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(UTC), nullable=False
    )

    __table_args__ = (
        UniqueConstraint("list_id", "position", name="uq_custom_cbl_entry_position"),
        UniqueConstraint("list_id", "issue_id", name="uq_custom_cbl_entry_issue"),
        Index("ix_custom_cbl_entries_list", "list_id"),
        Index("ix_custom_cbl_entries_issue", "issue_id"),
    )
