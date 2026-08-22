"""TasteSignal model for persistent Taste Bank discoveries (issue #1750).

A taste signal is one inferred pattern about a reader's preferences, such as
"comics written by Alan Moore rate well above this reader's baseline". Signals
are created by inference passes and confirmed, qualified, or rejected by the
reader through the discovery card.

Inferred evidence and explicit verdicts are stored separately so a later
inference refresh can update evidence without ever overwriting an explicit
verdict.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import TYPE_CHECKING

from sqlalchemy import DateTime, Float, ForeignKey, Index, Integer, String
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base

if TYPE_CHECKING:
    from app.models.user import User

SIGNAL_VERDICT_CONFIRMED = "confirmed"
SIGNAL_VERDICT_SOMETIMES = "sometimes"
SIGNAL_VERDICT_REJECTED = "rejected"
SIGNAL_VERDICTS = frozenset(
    {SIGNAL_VERDICT_CONFIRMED, SIGNAL_VERDICT_SOMETIMES, SIGNAL_VERDICT_REJECTED}
)


class TasteSignal(Base):
    """One persistent inferred taste pattern for a single user.

    Attributes:
        user_id: Owning user. All discovery access is scoped to this value.
        feature_type: Coarse evidence family, e.g. ``creator`` or ``series``.
        feature_key: Stable normalized identifier of the feature within its
            family (for example ``alan_moore``).
        creator_role: Optional creator role such as ``writer`` or ``artist``;
            only meaningful when ``feature_type`` is ``creator``.
        label: Human-readable feature name used directly in prompt copy.
        evidence_count: Number of supporting observations behind the pattern.
        distinct_threads: Number of distinct threads contributing evidence,
            used as the diversity requirement for prompting.
        affinity_delta: Mean rating delta versus the reader's baseline. This
            is stored as plain evidence context; it is never recommendation
            weighting.
        verdict: Explicit reader verdict once responded: ``confirmed``,
            ``sometimes``, or ``rejected``. ``None`` while only inferred.
        verdict_at: When the reader last submitted an explicit verdict.
        prompted_at: When this signal was last surfaced as a discovery card.
        prompt_count: How many times this signal has been surfaced.
        dismissed_at: When the reader last dismissed the card without giving a
            verdict. Dismissal is a temporary suppression, never confirmation.
    """

    __tablename__ = "taste_signals"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[int] = mapped_column(
        Integer,
        ForeignKey("users.id", name="fk_taste_signals_user_id_users", ondelete="CASCADE"),
        nullable=False,
    )
    feature_type: Mapped[str] = mapped_column(String(50), nullable=False)
    feature_key: Mapped[str] = mapped_column(String(200), nullable=False)
    creator_role: Mapped[str | None] = mapped_column(String(50), nullable=True)
    label: Mapped[str] = mapped_column(String(200), nullable=False)
    evidence_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    distinct_threads: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    affinity_delta: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    verdict: Mapped[str | None] = mapped_column(String(20), nullable=True)
    verdict_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    prompted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    prompt_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    dismissed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(UTC), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(UTC),
        onupdate=lambda: datetime.now(UTC),
        nullable=False,
    )

    user: Mapped[User] = relationship("User", back_populates="taste_signals", lazy="raise")

    __table_args__ = (
        Index(
            "ix_taste_signals_user_identity",
            "user_id",
            "feature_type",
            "creator_role",
            "feature_key",
        ),
        Index("ix_taste_signals_user_verdict", "user_id", "verdict"),
    )


def apply_inferred_evidence(
    signal: TasteSignal,
    *,
    evidence_count: int,
    distinct_threads: int,
    affinity_delta: float,
) -> None:
    """Refresh inferred evidence on a signal without touching its verdict.

    Inference passes call this so later re-analysis can strengthen or weaken
    the underlying evidence while an explicit reader verdict always wins.

    Args:
        signal: The signal to refresh.
        evidence_count: New supporting observation count.
        distinct_threads: New distinct-thread diversity count.
        affinity_delta: New mean rating delta versus baseline.
    """
    signal.evidence_count = evidence_count
    signal.distinct_threads = distinct_threads
    signal.affinity_delta = affinity_delta
