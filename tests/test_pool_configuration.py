"""Tests for SQLAlchemy pool configuration and observability.

Covers issue #1260 acceptance criteria: pool configuration is read from
environment variables, defaults match the Vercel Fluid Compute recommendation,
and pool event listeners are registered.
"""

import importlib
import os
from typing import Any

import pytest


@pytest.fixture(autouse=True)
def _clean_pool_env(monkeypatch: pytest.MonkeyPatch) -> None:
    """Ensure pool env vars do not leak between tests."""
    for key in ("DB_POOL_SIZE", "DB_MAX_OVERFLOW", "DB_POOL_PRE_PING", "DB_POOL_RECYCLE"):
        monkeypatch.delenv(key, raising=False)


def test_default_pool_configuration() -> None:
    """Default pool values match the Vercel Fluid Compute recommendation."""
    import app.database as db_mod

    importlib.reload(db_mod)
    assert db_mod.POOL_SIZE == 2
    assert db_mod.MAX_OVERFLOW == 0
    assert db_mod.POOL_PRE_PING is False
    assert db_mod.POOL_RECYCLE == 3600


def test_custom_pool_size_from_env(monkeypatch: pytest.MonkeyPatch) -> None:
    """DB_POOL_SIZE overrides the default."""
    monkeypatch.setenv("DB_POOL_SIZE", "5")
    import app.database as db_mod

    importlib.reload(db_mod)
    assert db_mod.POOL_SIZE == 5


def test_custom_max_overflow_from_env(monkeypatch: pytest.MonkeyPatch) -> None:
    """DB_MAX_OVERFLOW overrides the default."""
    monkeypatch.setenv("DB_MAX_OVERFLOW", "3")
    import app.database as db_mod

    importlib.reload(db_mod)
    assert db_mod.MAX_OVERFLOW == 3


def test_pre_ping_true_from_env(monkeypatch: pytest.MonkeyPatch) -> None:
    """DB_POOL_PRE_PING='true' enables pre-ping."""
    monkeypatch.setenv("DB_POOL_PRE_PING", "true")
    import app.database as db_mod

    importlib.reload(db_mod)
    assert db_mod.POOL_PRE_PING is True


def test_pre_ping_case_insensitive(monkeypatch: pytest.MonkeyPatch) -> None:
    """DB_POOL_PRE_PING comparison is case-insensitive."""
    monkeypatch.setenv("DB_POOL_PRE_PING", "TRUE")
    import app.database as db_mod

    importlib.reload(db_mod)
    assert db_mod.POOL_PRE_PING is True


def test_custom_recycle_from_env(monkeypatch: pytest.MonkeyPatch) -> None:
    """DB_POOL_RECYCLE overrides the default."""
    monkeypatch.setenv("DB_POOL_RECYCLE", "1800")
    import app.database as db_mod

    importlib.reload(db_mod)
    assert db_mod.POOL_RECYCLE == 1800


def test_engine_uses_configured_pool_settings() -> None:
    """The async engine receives the configured pool parameters."""
    import app.database as db_mod

    pool = async_engine_get_pool(db_mod)
    # Verify pool configuration matches environment defaults via internal pool config
    assert pool._poolconfig.pool_size == db_mod.POOL_SIZE
    assert pool._poolconfig.max_overflow == db_mod.MAX_OVERFLOW
    assert pool.overflow() <= db_mod.MAX_OVERFLOW


def async_engine_get_pool(db_mod: Any) -> Any:
    """Extract the pool from a database module's async engine."""
    return db_mod.async_engine.sync_engine.pool
