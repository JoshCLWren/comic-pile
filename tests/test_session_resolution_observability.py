"""Regression coverage for structured current-session resolution diagnostics."""

import logging
from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import Session, User
from app.performance_diagnostics import begin_request_diagnostics, end_request_diagnostics
from comic_pile.session import get_or_create


def _resolution_record(caplog: pytest.LogCaptureFixture) -> logging.LogRecord:
    return next(
        record
        for record in caplog.records
        if getattr(record, "event", None) == "reading_session_resolution"
    )


def _field(record: logging.LogRecord, name: str) -> object:
    """Read a structured logging field without inventing LogRecord attributes for typing."""
    return record.__dict__[name]


@pytest.mark.asyncio
async def test_reused_session_logs_resolution_and_request_context(
    async_db: AsyncSession,
    default_user: User,
    caplog: pytest.LogCaptureFixture,
) -> None:
    """Reusing a current session emits enough context to trace the decision."""
    current = Session(
        started_at=datetime.now(UTC) - timedelta(minutes=5),
        start_die=12,
        user_id=default_user.id,
    )
    stale = Session(
        started_at=datetime.now(UTC) - timedelta(hours=9),
        start_die=6,
        user_id=default_user.id,
    )
    async_db.add_all([current, stale])
    await async_db.commit()

    token = begin_request_diagnostics(
        request_id="request-987-reuse",
        route="/api/v1/roll/bootstrap",
    )
    try:
        with caplog.at_level(logging.INFO, logger="comic_pile.session"):
            resolved = await get_or_create(async_db, default_user.id)
    finally:
        end_request_diagnostics(token)

    assert resolved.id == current.id
    record = _resolution_record(caplog)
    assert _field(record, "session_id") == current.id
    assert _field(record, "session_resolution") == "reused"
    assert _field(record, "session_creation_reason") is None
    assert _field(record, "candidate_unended_sessions") == 2
    assert _field(record, "has_pending_thread") is False
    assert _field(record, "has_pending_issue") is False
    assert _field(record, "request_id") == "request-987-reuse"
    assert _field(record, "route") == "/api/v1/roll/bootstrap"


@pytest.mark.asyncio
async def test_created_session_logs_reason_and_candidate_count(
    async_db: AsyncSession,
    default_user: User,
    caplog: pytest.LogCaptureFixture,
) -> None:
    """Creating a session explains why no prior row was reused."""
    stale = Session(
        started_at=datetime.now(UTC) - timedelta(hours=9),
        start_die=10,
        user_id=default_user.id,
    )
    async_db.add(stale)
    await async_db.commit()

    token = begin_request_diagnostics(
        request_id="request-987-create",
        route="/api/v1/roll/bootstrap",
    )
    try:
        with caplog.at_level(logging.INFO, logger="comic_pile.session"):
            created = await get_or_create(async_db, default_user.id)
    finally:
        end_request_diagnostics(token)

    record = _resolution_record(caplog)
    assert _field(record, "session_id") == created.id
    assert _field(record, "session_resolution") == "created"
    assert _field(record, "session_creation_reason") == "no_recent_unended_session"
    assert _field(record, "candidate_unended_sessions") == 1
    assert _field(record, "has_pending_thread") is False
    assert _field(record, "has_pending_issue") is False
    assert _field(record, "request_id") == "request-987-create"
    assert _field(record, "route") == "/api/v1/roll/bootstrap"
