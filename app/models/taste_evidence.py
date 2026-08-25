"""Raw evidence rows backing rebuildable Taste Bank inference state.

Each row records a single feature observation derived from one rating event,
so every inferred statistic on the parent :class:`TasteSignal` stays
rebuildable from source history. Evidence rows are pure derived state: they
are replaced wholesale on every rebuild and never carry user-authored data.
"""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import (
    DateTime,
    Float,
    ForeignKey,
    Index,
    Integer,
    String,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base


class TasteEvidence(Base):
    """One raw observation contributing to a taste signal.

    Attributes:
        taste_signal_id: Parent signal this observation supports.
        user_id: Owner, denormalized for isolation queries and cleanup.
        signal_type: Feature type denormalized from the parent signal.
        external_key: Stable feature key denormalized from the parent signal.
        event_id: Rating event that produced this observation.
        thread_id: Thread where the observed issue lives.
        issue_id: Issue that was rated, when known.
        observed_rating: Rating value captured from the event.
        observed_at: When the event occurred.
    """

    __tablename__ = "taste_evidence"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    taste_signal_id: Mapped[int] = mapped_column(
        ForeignKey(
            "taste_signals.id",
            name="fk_taste_evidence_taste_signal_id_taste_signals",
            ondelete="CASCADE",
        ),
        nullable=False,
    )
    user_id: Mapped[int] = mapped_column(
        ForeignKey("users.id", name="fk_taste_evidence_user_id_users", ondelete="CASCADE"),
        nullable=False,
    )
    signal_type: Mapped[str] = mapped_column(String(20), nullable=False)
    external_key: Mapped[str] = mapped_column(String(255), nullable=False)
    event_id: Mapped[int] = mapped_column(
        ForeignKey("events.id", name="fk_taste_evidence_event_id_events", ondelete="CASCADE"),
        nullable=False,
    )
    thread_id: Mapped[int] = mapped_column(
        ForeignKey("threads.id", name="fk_taste_evidence_thread_id_threads", ondelete="CASCADE"),
        nullable=False,
    )
    issue_id: Mapped[int | None] = mapped_column(
        ForeignKey("issues.id", name="fk_taste_evidence_issue_id_issues", ondelete="SET NULL"),
        nullable=True,
    )
    observed_rating: Mapped[float] = mapped_column(Float, nullable=False)
    observed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)

    __table_args__ = (
        UniqueConstraint(
            "taste_signal_id",
            "event_id",
            name="uq_taste_evidence_signal_event",
        ),
        Index("ix_taste_evidence_user_id", "user_id"),
        Index("ix_taste_evidence_signal_id", "taste_signal_id"),
        Index("ix_taste_evidence_user_signal", "user_id", "signal_type", "external_key"),
    )
