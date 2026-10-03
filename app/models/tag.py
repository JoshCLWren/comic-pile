"""Tag and polymorphic assignment models.

A tag is either global (visible to everyone, owned by an admin) or private
(visible only to its owner). Tag assignments are polymorphic: a single
``tag_assignments`` table points at issues, threads, and reading plans without
needing a new join table per target type.
"""

from __future__ import annotations

from datetime import UTC, datetime

from sqlalchemy import DateTime, ForeignKey, Index, Integer, String, text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base


class Tag(Base):
    """A reusable tag, either global or user-private.

    Attributes:
        id: Primary key.
        name: The human-readable tag name with original casing preserved.
        normalized_name: Lowercased, trimmed name used for matching and
            uniqueness (a private tag cannot reuse a global name, and two
            private tags owned by the same user cannot share a name).
        scope: Either ``"global"`` (visible to everyone, admin-only CRUD) or
            ``"private"`` (visible only to the owner).
        owner_user_id: Owner of a private tag; ``NULL`` for global tags.
        color: Hex ``#RRGGBB`` value from the fixed 32-color palette.
        created_at: When the tag was created.
        updated_at: When the tag was last updated.
    """

    __tablename__ = "tags"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    name: Mapped[str] = mapped_column(String(100), nullable=False)
    normalized_name: Mapped[str] = mapped_column(String(100), nullable=False)
    scope: Mapped[str] = mapped_column(String(10), nullable=False)
    owner_user_id: Mapped[int | None] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), nullable=True
    )
    color: Mapped[str] = mapped_column(String(7), nullable=False)
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
        # Global tags are unique by normalized name.
        Index(
            "uq_tags_global_names",
            "normalized_name",
            unique=True,
            postgresql_where=text("scope = 'global'"),
        ),
        # Two private tags owned by the same user cannot share a normalized name;
        # different users may independently have identically named private tags.
        Index(
            "uq_tags_private_names",
            "owner_user_id",
            "normalized_name",
            unique=True,
            postgresql_where=text("scope = 'private'"),
        ),
        Index("ix_tags_owner_user_id", "owner_user_id"),
        Index("ix_tags_scope", "scope"),
        Index("ix_tags_normalized_name", "normalized_name"),
    )

    assignments: Mapped[list[TagAssignment]] = relationship(
        "TagAssignment",
        back_populates="tag",
        lazy="raise",
        cascade="all, delete-orphan",
        passive_deletes=True,
    )


class TagAssignment(Base):
    """A tag attached to a target of a known type.

    Attributes:
        id: Primary key.
        tag_id: Referenced tag.
        target_type: One of ``"Issue"``, ``"Thread"``, or ``"ContinuityPlan"``.
        target_id: Primary key of the target row within its own table.
        created_at: When the assignment was made.
    """

    __tablename__ = "tag_assignments"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    tag_id: Mapped[int] = mapped_column(ForeignKey("tags.id", ondelete="CASCADE"), nullable=False)
    target_type: Mapped[str] = mapped_column(String(50), nullable=False)
    target_id: Mapped[int] = mapped_column(Integer, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(UTC), nullable=False
    )

    __table_args__ = (
        Index("ix_tag_assignments_tag_id", "tag_id"),
        Index("ix_tag_assignments_target", "target_type", "target_id"),
        Index(
            "uq_tag_assignments_target",
            "tag_id",
            "target_type",
            "target_id",
            unique=True,
        ),
    )

    tag: Mapped[Tag] = relationship("Tag", back_populates="assignments", lazy="raise")
