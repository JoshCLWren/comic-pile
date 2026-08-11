"""Normalized persistence for imported CBL reading-list provenance."""

from __future__ import annotations

from datetime import UTC, datetime

from sqlalchemy import Boolean, DateTime, ForeignKey, Index, Integer, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base


class CBLSource(Base):
    """One configured CBL repository and its most recently synchronized revision."""

    __tablename__ = "cbl_sources"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    repository: Mapped[str] = mapped_column(String(255), nullable=False, unique=True)
    revision_sha: Mapped[str] = mapped_column(String(64), nullable=False)
    synced_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(UTC), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(UTC),
        onupdate=lambda: datetime.now(UTC),
        nullable=False,
    )


class CBLSourceList(Base):
    """One source-relative CBL list with current revision and content provenance."""

    __tablename__ = "cbl_source_lists"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    source_id: Mapped[int] = mapped_column(
        ForeignKey("cbl_sources.id", ondelete="CASCADE"), nullable=False
    )
    source_path: Mapped[str] = mapped_column(String(1000), nullable=False)
    name: Mapped[str] = mapped_column(String(500), nullable=False)
    declared_issue_count: Mapped[int | None] = mapped_column(Integer, nullable=True)
    content_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    revision_sha: Mapped[str] = mapped_column(String(64), nullable=False)
    active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
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
        UniqueConstraint("source_id", "source_path", name="uq_cbl_source_list_path"),
        Index("ix_cbl_source_list_source_active", "source_id", "active"),
    )


class CBLSourceEntry(Base):
    """One ordered comic reference in an imported CBL list."""

    __tablename__ = "cbl_source_entries"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    list_id: Mapped[int] = mapped_column(
        ForeignKey("cbl_source_lists.id", ondelete="CASCADE"), nullable=False
    )
    position: Mapped[int] = mapped_column(Integer, nullable=False)
    series_name: Mapped[str] = mapped_column(String(500), nullable=False)
    issue_number: Mapped[str] = mapped_column(String(100), nullable=False)
    volume_year: Mapped[int | None] = mapped_column(Integer, nullable=True)
    publication_year: Mapped[int | None] = mapped_column(Integer, nullable=True)
    external_series_identity_id: Mapped[int | None] = mapped_column(
        ForeignKey("external_identities.id", ondelete="SET NULL"), nullable=True
    )
    external_issue_identity_id: Mapped[int | None] = mapped_column(
        ForeignKey("external_identities.id", ondelete="SET NULL"), nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(UTC), nullable=False
    )

    __table_args__ = (
        UniqueConstraint("list_id", "position", name="uq_cbl_source_entry_position"),
        Index("ix_cbl_source_entry_list_id", "list_id"),
        Index("ix_cbl_source_entry_series_identity", "external_series_identity_id"),
        Index("ix_cbl_source_entry_issue_identity", "external_issue_identity_id"),
    )
