"""Tests for SQLAlchemy pool event listeners added in issue #1260.

Verifies that observability hooks for checkout, checkin, connect,
first_connect, and invalidate are registered on the engine pool.
"""

import pytest


@pytest.fixture()
def _reload_database() -> None:
    """Force a fresh import of app.database to pick up event registrations."""
    import importlib

    import app.database as db_mod

    importlib.reload(db_mod)


def _listener_count(dispatch: object, event_name: str) -> int:
    """Return the listener count for a dynamically typed SQLAlchemy event."""
    event = getattr(dispatch, event_name, None)
    assert event is not None
    return len(list(event.listeners))


def test_checkout_listener_registered(_reload_database: None) -> None:
    """The checkout pool event has at least one listener."""
    import app.database as db_mod

    dispatch = db_mod.async_engine.sync_engine.pool.dispatch
    assert _listener_count(dispatch, "checkout") >= 1


def test_checkin_listener_registered(_reload_database: None) -> None:
    """The checkin pool event has at least one listener."""
    import app.database as db_mod

    dispatch = db_mod.async_engine.sync_engine.pool.dispatch
    assert _listener_count(dispatch, "checkin") >= 1


def test_connect_listener_registered(_reload_database: None) -> None:
    """The connect pool event has at least one listener."""
    import app.database as db_mod

    dispatch = db_mod.async_engine.sync_engine.pool.dispatch
    assert _listener_count(dispatch, "connect") >= 1


def test_first_connect_listener_registered(_reload_database: None) -> None:
    """The first_connect pool event has at least one listener."""
    import app.database as db_mod

    dispatch = db_mod.async_engine.sync_engine.pool.dispatch
    assert _listener_count(dispatch, "first_connect") >= 1


def test_invalidate_listener_registered(_reload_database: None) -> None:
    """The invalidate pool event has at least one listener."""
    import app.database as db_mod

    dispatch = db_mod.async_engine.sync_engine.pool.dispatch
    assert _listener_count(dispatch, "invalidate") >= 1


def test_before_cursor_execute_listener_registered(_reload_database: None) -> None:
    """The before_cursor_execute engine event has at least one listener."""
    import app.database as db_mod

    dispatch = db_mod.async_engine.sync_engine.dispatch
    assert _listener_count(dispatch, "before_cursor_execute") >= 1


def test_after_cursor_execute_listener_registered(_reload_database: None) -> None:
    """The after_cursor_execute engine event has at least one listener."""
    import app.database as db_mod

    dispatch = db_mod.async_engine.sync_engine.dispatch
    assert _listener_count(dispatch, "after_cursor_execute") >= 1
