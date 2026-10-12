"""Shared catalog identity models for cross-reader comic identity."""

from __future__ import annotations

from datetime import UTC, datetime

from sqlalchemy import BigInteger, DateTime, ForeignKey, Index, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base


class CatalogSeries(Base):
    """Shared canonical series identity across all readers.

    Each CatalogSeries references exactly one confirmed ExternalIdentity of
    entity_type='series'. The ExternalIdentity remains the metadata authority;
    this table provides a stable shared key for reader libraries to reference.
    """

    __tablename__ = "catalog_series"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    canonical_external_identity_id: Mapped[int] = mapped_column(
        ForeignKey("external_identities.id", ondelete="RESTRICT"),
        nullable=False,
        unique=True,
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(UTC)
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(UTC),
        onupdate=lambda: datetime.now(UTC),
    )

    __table_args__ = (
        Index("ix_catalog_series_external_identity", "canonical_external_identity_id"),
    )


class CatalogIssue(Base):
    """Shared canonical issue identity across all readers.

    Each CatalogIssue references exactly one confirmed ExternalIdentity of
    entity_type='issue'. May optionally link to a CatalogSeries once the
    series identity is confirmed. The link is additive and never overwrites
    reader ownership.
    """

    __tablename__ = "catalog_issues"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    canonical_external_identity_id: Mapped[int] = mapped_column(
        ForeignKey("external_identities.id", ondelete="RESTRICT"),
        nullable=False,
        unique=True,
    )
    catalog_series_id: Mapped[int | None] = mapped_column(
        ForeignKey("catalog_series.id", ondelete="SET NULL"),
        nullable=True,
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(UTC)
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(UTC),
        onupdate=lambda: datetime.now(UTC),
    )

    catalog_series: Mapped[CatalogSeries | None] = relationship(
        "CatalogSeries", lazy="raise", foreign_keys=[catalog_series_id]
    )

    __table_args__ = (
        Index("ix_catalog_issues_external_identity", "canonical_external_identity_id"),
        Index("ix_catalog_issues_catalog_series", "catalog_series_id"),
    )