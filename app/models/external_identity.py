"""Provider-independent comic and series identity persistence."""

from __future__ import annotations

from datetime import UTC, datetime

from sqlalchemy import (
    CheckConstraint,
    DateTime,
    Float,
    ForeignKey,
    Index,
    Integer,
    JSON,
    String,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base


class ExternalIdentity(Base):
    """One provider-owned external comic issue or series identity."""

    __tablename__ = "external_identities"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    provider: Mapped[str] = mapped_column(String(50), nullable=False)
    entity_type: Mapped[str] = mapped_column(String(20), nullable=False)
    external_id: Mapped[str] = mapped_column(String(100), nullable=False)
    external_url: Mapped[str | None] = mapped_column(String(500), nullable=True)
    metadata_json: Mapped[dict[str, object]] = mapped_column(JSON, default=dict, nullable=False)
    provider_updated_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=lambda: datetime.now(UTC))
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(UTC),
        onupdate=lambda: datetime.now(UTC),
    )

    __table_args__ = (
        CheckConstraint("entity_type IN ('issue', 'series')", name="ck_external_identity_entity_type"),
        UniqueConstraint("provider", "entity_type", "external_id", name="uq_external_identity_provider_entity"),
        Index("ix_external_identity_provider_type", "provider", "entity_type"),
    )


class IssueExternalIdentityMapping(Base):
    """Candidate or confirmed external issue identity for one ComicPile issue."""

    __tablename__ = "issue_external_identity_mappings"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    issue_id: Mapped[int] = mapped_column(ForeignKey("issues.id", ondelete="CASCADE"), nullable=False)
    external_identity_id: Mapped[int] = mapped_column(
        ForeignKey("external_identities.id", ondelete="CASCADE"), nullable=False
    )
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="candidate")
    evidence_source: Mapped[str | None] = mapped_column(String(100), nullable=True)
    evidence_json: Mapped[dict[str, object]] = mapped_column(JSON, default=dict, nullable=False)
    confidence: Mapped[float | None] = mapped_column(Float, nullable=True)
    rejection_reason: Mapped[str | None] = mapped_column(String(500), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=lambda: datetime.now(UTC))
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(UTC),
        onupdate=lambda: datetime.now(UTC),
    )

    __table_args__ = (
        CheckConstraint(
            "status IN ('unresolved', 'candidate', 'confirmed', 'rejected')",
            name="ck_issue_external_identity_status",
        ),
        CheckConstraint(
            "confidence IS NULL OR (confidence >= 0 AND confidence <= 1)",
            name="ck_issue_external_identity_confidence",
        ),
        UniqueConstraint(
            "issue_id",
            "external_identity_id",
            name="uq_issue_external_identity_mapping",
        ),
        Index("ix_issue_external_identity_issue_id", "issue_id"),
        Index("ix_issue_external_identity_external_id", "external_identity_id"),
    )


class SeriesMappingCommitReceipt(Base):
    """Durable idempotency receipt for one user-approved series mapping commit.

    The receipt is the durable record of a material commit request. It is written
    inside the same transaction as the identity writes, so a stored receipt
    always means the confirmed mappings it describes are durable. A retry with
    the same ``idempotency_key`` and the same ``request_digest`` replays the
    stored response; a different digest is an idempotency conflict.
    """

    __tablename__ = "series_mapping_commit_receipts"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    idempotency_key: Mapped[str] = mapped_column(String(200), nullable=False)
    request_digest: Mapped[str] = mapped_column(String(64), nullable=False)
    provider: Mapped[str] = mapped_column(String(50), nullable=False)
    provider_series_external_id: Mapped[str] = mapped_column(String(100), nullable=False)
    origin_issue_id: Mapped[int] = mapped_column(Integer, nullable=False)
    response_json: Mapped[dict[str, object]] = mapped_column(JSON, default=dict, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=lambda: datetime.now(UTC))
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(UTC),
        onupdate=lambda: datetime.now(UTC),
    )

    __table_args__ = (
        UniqueConstraint("user_id", "idempotency_key", name="uq_series_mapping_commit_receipt_key"),
        Index("ix_series_mapping_commit_receipt_user_id", "user_id"),
    )


class ThreadExternalSeriesMapping(Base):
    """Non-exclusive external series evidence associated with a reading-project thread."""

    __tablename__ = "thread_external_series_mappings"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    thread_id: Mapped[int] = mapped_column(ForeignKey("threads.id", ondelete="CASCADE"), nullable=False)
    external_identity_id: Mapped[int] = mapped_column(
        ForeignKey("external_identities.id", ondelete="CASCADE"), nullable=False
    )
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="candidate")
    evidence_source: Mapped[str | None] = mapped_column(String(100), nullable=True)
    confidence: Mapped[float | None] = mapped_column(Float, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=lambda: datetime.now(UTC))
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(UTC),
        onupdate=lambda: datetime.now(UTC),
    )

    __table_args__ = (
        CheckConstraint(
            "status IN ('unresolved', 'candidate', 'confirmed', 'rejected')",
            name="ck_thread_external_series_status",
        ),
        CheckConstraint(
            "confidence IS NULL OR (confidence >= 0 AND confidence <= 1)",
            name="ck_thread_external_series_confidence",
        ),
        UniqueConstraint(
            "thread_id",
            "external_identity_id",
            name="uq_thread_external_series_mapping",
        ),
        Index("ix_thread_external_series_thread_id", "thread_id"),
        Index("ix_thread_external_series_external_id", "external_identity_id"),
    )
