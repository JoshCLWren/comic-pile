"""Timezone capture behavior for the Roll bootstrap endpoint (#1690).

The browser-resolved IANA timezone must be persisted exactly once for an
active reading session, must reject unusable identifiers without breaking
Roll, and must remain unset when no timezone is supplied.
"""

from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from app.api import roll as roll_api


class _Result:
    """Minimal SQLAlchemy result double for the bootstrap query sequence."""

    def __init__(self, *, rows=None, scalar_value=None):
        self._rows = rows or []
        self._scalar_value = scalar_value

    def all(self):
        return self._rows

    def scalar(self):
        return self._scalar_value

    def first(self):
        return self._rows[0] if self._rows else None

    def scalars(self):
        return self


def _session(timezone=None):
    return SimpleNamespace(
        id=55,
        manual_die=None,
        pending_thread_id=None,
        snoozed_thread_ids=[],
        skipped_thread_ids=[],
        timezone=timezone,
        active_bandwidth=None,
        predicted_bandwidth=None,
        bandwidth_confidence=None,
        bandwidth_source=None,
        bandwidth_version=None,
        active_intent=None,
        predicted_intent=None,
        intent_confidence=None,
        intent_source=None,
        intent_version=None,
        session_mode_correction_guidance=None,
    )


def _patch_bootstrap(monkeypatch, current_session):
    monkeypatch.setattr(
        roll_api,
        "get_or_create",
        AsyncMock(return_value=current_session),
    )
    monkeypatch.setattr(
        roll_api,
        "get_session_with_thread_safe",
        AsyncMock(return_value=(current_session, None)),
    )
    monkeypatch.setattr(
        roll_api,
        "get_current_die_for_session",
        AsyncMock(return_value=6),
    )

    db = AsyncMock()
    db.execute.side_effect = [
        _Result(rows=[]),
        _Result(rows=[]),
        _Result(scalar_value=0),
        _Result(rows=[]),
        _Result(scalar_value=0),
    ]
    return db


@pytest.mark.asyncio
async def test_bootstrap_persists_valid_browser_timezone(monkeypatch):
    """A valid IANA identifier is captured exactly once and echoed back."""
    current_session = _session()
    db = _patch_bootstrap(monkeypatch, current_session)

    response = await roll_api.roll_bootstrap(
        current_user=SimpleNamespace(id=7),
        db=db,
        timezone="America/Chicago",
    )

    assert current_session.timezone == "America/Chicago"
    db.commit.assert_awaited_once()
    assert response.timezone == "America/Chicago"


@pytest.mark.asyncio
async def test_bootstrap_strips_surrounding_whitespace_before_capture(monkeypatch):
    """Whitespace around an otherwise valid identifier does not block capture."""
    current_session = _session()
    db = _patch_bootstrap(monkeypatch, current_session)

    await roll_api.roll_bootstrap(
        current_user=SimpleNamespace(id=7),
        db=db,
        timezone="  Europe/Berlin  ",
    )

    assert current_session.timezone == "Europe/Berlin"
    db.commit.assert_awaited_once()


@pytest.mark.asyncio
async def test_bootstrap_without_timezone_leaves_field_unset(monkeypatch):
    """No query parameter means no persistence attempt and a null field."""
    current_session = _session()
    db = _patch_bootstrap(monkeypatch, current_session)

    response = await roll_api.roll_bootstrap(
        current_user=SimpleNamespace(id=7),
        db=db,
    )

    db.commit.assert_not_awaited()
    assert current_session.timezone is None
    assert response.timezone is None


@pytest.mark.asyncio
async def test_bootstrap_rejects_malformed_timezone_values(monkeypatch):
    """Unusable identifiers fail safely: nothing persists and Roll still renders."""
    invalid_timezones = [
        "Not/ARealZone",
        "../../etc/passwd",
        "America/Chicago; DROP TABLE sessions",
        "   ",
        "d" * 101,
    ]

    for invalid_timezone in invalid_timezones:
        current_session = _session()
        db = _patch_bootstrap(monkeypatch, current_session)

        response = await roll_api.roll_bootstrap(
            current_user=SimpleNamespace(id=7),
            db=db,
            timezone=invalid_timezone,
        )

        db.commit.assert_not_awaited()
        assert current_session.timezone is None
        assert response.timezone is None


@pytest.mark.asyncio
async def test_bootstrap_never_rewrites_existing_session_timezone(monkeypatch):
    """Later bootstrap calls must not rewrite historical session timezone."""
    current_session = _session(timezone="Europe/Berlin")
    db = _patch_bootstrap(monkeypatch, current_session)

    response = await roll_api.roll_bootstrap(
        current_user=SimpleNamespace(id=7),
        db=db,
        timezone="America/Chicago",
    )

    db.commit.assert_not_awaited()
    assert current_session.timezone == "Europe/Berlin"
    assert response.timezone == "Europe/Berlin"
