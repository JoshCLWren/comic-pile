"""Timezone capture behavior for the Roll bootstrap endpoint (#1690).

The browser-resolved IANA timezone must be persisted exactly once for an
active reading session, must reject unusable identifiers without breaking
Roll, and must remain unset when no timezone is supplied.
"""

from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from app.api import roll as roll_api
from app.repositories import roll_bootstrap_repository as roll_bootstrap_repo
from app.services import roll_bootstrap_service


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
    """Patch the v1 bootstrap collaborators and return the async db double.

    Timezone capture is session behavior, so every collaborator that could
    perform unrelated database work is replaced and only the capture path
    itself stays real.
    """
    monkeypatch.setattr(
        roll_bootstrap_service,
        "get_or_create",
        AsyncMock(return_value=current_session),
    )
    monkeypatch.setattr(
        roll_bootstrap_service,
        "get_session_with_thread_safe",
        AsyncMock(return_value=(current_session, None)),
    )
    monkeypatch.setattr(
        roll_bootstrap_service,
        "get_current_die_for_session",
        AsyncMock(return_value=6),
    )
    monkeypatch.setattr(
        roll_bootstrap_service,
        "derive_cross_session_excluded_thread_ids",
        AsyncMock(return_value=set()),
    )
    monkeypatch.setattr(
        roll_bootstrap_repo,
        "fetch_owned_thread_inventory",
        AsyncMock(return_value=[]),
    )
    monkeypatch.setattr(
        roll_bootstrap_repo,
        "fetch_roll_pool_rows",
        AsyncMock(return_value=[]),
    )

    return AsyncMock()


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
