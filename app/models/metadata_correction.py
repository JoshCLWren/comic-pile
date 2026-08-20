"""Canonical metadata correction persistence for user-contributed overrides."""

from __future__ import annotations

from datetime import UTC, datetime

from sqlalchemy import ForeignKey, Index, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base


class IssueMetadataCorrection(Base):
    """One user-contributed canonical override for a ComicPile issue's metadata field."""

    __tablename__ = "issue_metadata_corrections"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    issue_id: Mapped[int] = mapped_column(ForeignKey("issues.id", ondelete="CASCADE"), nullable=False)
    field_name: Mapped[str] = mapped_column(String(100), nullable=False)
    provider_value: Mapped[str | None] = mapped_column(Text, nullable=True)
    canonical_value: Mapped[str] = mapped_column(Text, nullable=False)
    provenance: Mapped[str] = mapped_column(String(100), nullable=False, default="user_correction")
    created_by: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    reverted_at: Mapped[datetime | None] = mapped_column(
        "reverted_at", nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(default=lambda: datetime.now(UTC))
    updated_at: Mapped[datetime] = mapped_column(
        default=lambda: datetime.now(UTC),
        onupdate=lambda: datetime.now(UTC),
    )

    __table_args__ = (
        Index("ix_issue_metadata_correction_issue_id", "issue_id"),
        Index("ix_issue_metadata_correction_created_by", "created_by"),
    )
