"""Durable per-reader, per-external-CBL source links to owned Option E lists (#4021).

``custom_cbl_source_links`` is the stable adoption key between the shared
user-independent CBL source catalog and one reader-owned ``custom_cbl_lists``
row:

- the source side never gains a ``user_id`` column (global facts stay global);
- one reader can link the same source at most once -- the unique
  ``(user_id, cbl_source_list_id)`` constraint is the transactional idempotency
  guarantee, so retries and concurrent first-add commits converge on the same
  owned list instead of creating a copy;
- one owned list is claimed by at most one source link;
- the link is keyed by source identity (repository/path/revision) and never by
  list title, and its destination is an owned custom CBL list -- never a
  legacy ``ContinuityPlan`` receipt;
- ``source_revision_sha`` and ``source_content_hash`` capture the source
  provenance at first-add time so later source changes are compared and
  reviewed, not silently applied.
"""

from __future__ import annotations

from datetime import UTC, datetime

from sqlalchemy import DateTime, ForeignKey, Index, Integer, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base


class CustomCBLSourceLink(Base):
    """One reader's durable claim on one external CBL source list.

    The linked ``custom_cbl_lists`` row is the reader's editable Option E
    Reading List destination. The source snapshot columns record the exact
    revision and content hash observed when the link was first created.
    """

    __tablename__ = "custom_cbl_source_links"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    cbl_source_list_id: Mapped[int] = mapped_column(
        ForeignKey("cbl_source_lists.id", ondelete="CASCADE"), nullable=False
    )
    custom_cbl_list_id: Mapped[int] = mapped_column(
        ForeignKey("custom_cbl_lists.id", ondelete="CASCADE"), nullable=False
    )
    source_revision_sha: Mapped[str] = mapped_column(String(64), nullable=False)
    source_content_hash: Mapped[str] = mapped_column(String(64), nullable=False)
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
            name="uq_custom_cbl_source_link_user_source",
        ),
        UniqueConstraint("custom_cbl_list_id", name="uq_custom_cbl_source_link_list"),
        Index(
            "ix_custom_cbl_source_link_source_list",
            "cbl_source_list_id",
        ),
    )
