"""Persistent account-wide Roll tag exclusions.

Issue #3033: a user may say "do not roll anything tagged X". Exclusions are
persistent and account-wide (not ReadingSession-only) and remain active until
the user removes them. One row per ``(user_id, tag_id)`` pair records that the
user excluded a tag from Roll eligibility.

Exclusions are eligibility constraints only. They never snooze a thread,
change the die, feed bandwidth correction, move queue positions, or affect
ratings and recommendation weighting. The roll path consults these rows
through ``app.repositories.roll_tag_exclusion_repository`` and
``app.services.roll_tag_exclusion_service``.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import TYPE_CHECKING

from sqlalchemy import DateTime, ForeignKey, Index, Integer
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base

if TYPE_CHECKING:
    from app.models.tag import Tag


class RollTagExclusion(Base):
    """One user's persistent exclusion of a tag from Roll eligibility.

    Attributes:
        id: Primary key.
        user_id: Owner of the exclusion. Exclusions are user-scoped even when
            the excluded tag itself is global: excluding a global tag hides
            matching candidates only for the excluding user.
        tag_id: Excluded tag. May reference a global tag or a private tag
            owned by the same user.
        created_at: When the exclusion was recorded.
    """

    __tablename__ = "roll_tag_exclusions"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[int] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )
    tag_id: Mapped[int] = mapped_column(
        ForeignKey("tags.id", ondelete="CASCADE"), nullable=False
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(UTC), nullable=False
    )

    tag: Mapped[Tag] = relationship("Tag", lazy="raise")

    __table_args__ = (
        Index("ix_roll_tag_exclusions_user_id", "user_id"),
        Index("ix_roll_tag_exclusions_tag_id", "tag_id"),
        Index(
            "uq_roll_tag_exclusions_user_tag",
            "user_id",
            "tag_id",
            unique=True,
        ),
    )
