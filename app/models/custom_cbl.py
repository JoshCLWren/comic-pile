"""User-authored CBL lists that reference canonical ComicPile issues."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Literal

from sqlalchemy import (
    JSON,
    Boolean,
    CheckConstraint,
    DateTime,
    ForeignKey,
    ForeignKeyConstraint,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base


class CustomCBLList(Base):
    """One user-owned editable comic reading list.

    Custom CBLs hold reader-authored membership and Option E positional intent.
    These fields remain inactive in Roll until the separately approved cutover;
    the transitional Reading Plan runtime still serves current eligibility.
    """

    __tablename__ = "custom_cbl_lists"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    mode: Mapped[Literal["strict", "loose"]] = mapped_column(
        String(6), nullable=False, default="loose", server_default="loose"
    )
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
    #: Version token of this list's reader-approved overlap decisions. It is
    #: independent of ``updated_at`` so that an ordinary membership upsert
    #: never invalidates an approved choice, and a choice change never rewrites
    #: the list's own revision.
    overlap_decisions_updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(UTC),
        nullable=False,
    )

    __table_args__ = (
        CheckConstraint("mode IN ('strict', 'loose')", name="ck_custom_cbl_lists_mode"),
        # Backs the composite owner-scoped foreign key of
        # custom_cbl_overlap_decisions: a stored decision can only name a list
        # whose owner is the same reader.
        UniqueConstraint("id", "user_id", name="uq_custom_cbl_lists_id_user"),
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
    gate: Mapped[Literal["none", "hold", "after_previous"]] = mapped_column(
        String(14), nullable=False, default="none", server_default="none"
    )
    skipped: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False, server_default="false"
    )
    is_checkpoint: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    checkpoint_target_issue_ids: Mapped[list[int]] = mapped_column(
        JSON, nullable=False, default=list, server_default="[]"
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(UTC), nullable=False
    )

    __table_args__ = (
        CheckConstraint(
            "gate IN ('none', 'hold', 'after_previous')", name="ck_custom_cbl_entries_gate"
        ),
        UniqueConstraint("list_id", "position", name="uq_custom_cbl_entry_position"),
        UniqueConstraint("list_id", "issue_id", name="uq_custom_cbl_entry_issue"),
        Index("ix_custom_cbl_entries_list", "list_id"),
        Index("ix_custom_cbl_entries_issue", "issue_id"),
    )


class CustomCBLOverlapDecision(Base):
    """One reader-approved overlap exception inside one owned Reading List.

    A decision names the exact pair of Comic Vine volume identities the reader
    allowed to overlap: the continuing volume keeps progressing while earlier
    unread entries of the waiting volume remain. Both sides reference confirmed
    provider series identities instead of free-text titles, so a stored choice
    can never drift onto a same-titled other volume or another provider.

    Owner scope is enforced in the database. The composite foreign key requires
    the decision's ``user_id`` to be the owner of the referenced list, so one
    reader's choice can never be attached to another reader's list. Deleting the
    list or its owner removes the decision with them; deleting a referenced
    provider identity is rejected instead of silently dropping the choice.
    """

    __tablename__ = "custom_cbl_overlap_decisions"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[int] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )
    list_id: Mapped[int] = mapped_column(nullable=False)
    continuing_external_identity_id: Mapped[int] = mapped_column(
        ForeignKey("external_identities.id", ondelete="RESTRICT"), nullable=False
    )
    waiting_external_identity_id: Mapped[int] = mapped_column(
        ForeignKey("external_identities.id", ondelete="RESTRICT"), nullable=False
    )
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
        CheckConstraint(
            "continuing_external_identity_id <> waiting_external_identity_id",
            name="ck_custom_cbl_overlap_decision_distinct_volumes",
        ),
        UniqueConstraint(
            "list_id",
            "continuing_external_identity_id",
            "waiting_external_identity_id",
            name="uq_custom_cbl_overlap_decision_pair",
        ),
        ForeignKeyConstraint(
            ["list_id", "user_id"],
            ["custom_cbl_lists.id", "custom_cbl_lists.user_id"],
            name="fk_custom_cbl_overlap_decision_owner_list",
            ondelete="CASCADE",
        ),
        Index("ix_custom_cbl_overlap_decisions_list", "list_id"),
        Index("ix_custom_cbl_overlap_decisions_user", "user_id"),
    )
