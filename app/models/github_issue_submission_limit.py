"""Durable per-user GitHub issue submission rate-limit state."""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, Integer
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base


class GithubIssueSubmissionLimit(Base):
    """Cross-instance record of a user's last successful GitHub issue submission.

    One row per user that has attempted a ComicPile GitHub issue submission.
    ``last_submitted_at`` is written only after GitHub confirms the issue was
    created, so failed or concurrent attempts never consume the rolling-hour
    allowance. The row is the authoritative limit state; it lives in
    PostgreSQL rather than process memory so every app instance and serverless
    invocation observes the same allowance.
    """

    __tablename__ = "github_issue_submission_limits"

    user_id: Mapped[int] = mapped_column(
        Integer,
        ForeignKey("users.id", ondelete="CASCADE"),
        primary_key=True,
    )
    last_submitted_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )
