"""Regression tests for the conftest ``worker_id`` fixture.

pytest-xdist already provides a session-scoped ``worker_id`` fixture
(``gw0``, ``gw1``, ... or ``master``). The conftest fixture previously shadowed
it and returned ``"master"`` for every worker, breaking xdist schema-init
coordination in ``db_engine``. The fixture must honor xdist's real value via
the ``PYTEST_XDIST_WORKER`` environment variable.
"""

import inspect
import os

import pytest

from tests import conftest


def test_worker_id_honors_xdist_value(worker_id: str) -> None:
    """The pytest-injected fixture must match the live xdist environment.

    Under ``pytest -n2`` each worker has ``PYTEST_XDIST_WORKER`` set to
    ``gw0`` / ``gw1``; without xdist the variable is absent and the default is
    ``"master"``. This asserts the real, pytest-resolved fixture value, so it is
    the strongest end-to-end check when the suite runs under xdist.
    """
    expected = os.environ.get("PYTEST_XDIST_WORKER", "master")
    assert worker_id == expected

    # Under xdist every worker must report a distinct, non-master id so that
    # exactly one worker performs schema initialization in db_engine.
    if expected.startswith("gw"):
        assert worker_id != "master"
        assert worker_id == expected


def test_worker_id_fixture_reads_env_var(monkeypatch: pytest.MonkeyPatch) -> None:
    """The fixture function must return a supplied non-default worker id.

    A session-scoped fixture is evaluated once at session start, so
    ``monkeypatch.setenv`` inside a test cannot influence the *injected* value.
    Resolve the fixture's underlying function (``inspect.unwrap`` follows the
    ``__wrapped__`` pytest attaches) and set the environment before calling it.
    This fails against the original ``return "master"`` stub even in normal
    (non-xdist) CI, which is exactly the regression this file guards.
    """
    monkeypatch.setenv("PYTEST_XDIST_WORKER", "gw1")
    fixture_function = inspect.unwrap(conftest.worker_id)
    assert fixture_function() == "gw1"


def test_worker_id_fixture_defaults_to_master(monkeypatch: pytest.MonkeyPatch) -> None:
    """Without ``PYTEST_XDIST_WORKER`` the fixture function defaults to master."""
    monkeypatch.delenv("PYTEST_XDIST_WORKER", raising=False)
    fixture_function = inspect.unwrap(conftest.worker_id)
    assert fixture_function() == "master"
