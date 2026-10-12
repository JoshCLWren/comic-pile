"""Durable performance-alarm counters and incident state.

Shared across Vercel serverless instances so daily breach counts and open
issue identity survive process recycling (issue #3552 review).
"""

from __future__ import annotations

from datetime import date, datetime

from sqlalchemy import Date, DateTime, Integer, String
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base


class PerfAlarmCounter(Base):
    """Per-fingerprint warm over-budget hit count for one UTC day."""

    __tablename__ = "perf_alarm_counters"

    fingerprint: Mapped[str] = mapped_column(String(32), primary_key=True)
    utc_day: Mapped[date] = mapped_column(Date, primary_key=True)
    hit_count: Mapped[int] = mapped_column(Integer, nullable=False, default=1)


class PerfAlarmIncident(Base):
    """Open/closed GitHub issue identity and filing/comment leases."""

    __tablename__ = "perf_alarm_incidents"

    fingerprint: Mapped[str] = mapped_column(String(32), primary_key=True)
    open_issue_number: Mapped[int | None] = mapped_column(Integer, nullable=True)
    last_closed_issue_number: Mapped[int | None] = mapped_column(Integer, nullable=True)
    last_comment_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )
    filing_claimed_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )
