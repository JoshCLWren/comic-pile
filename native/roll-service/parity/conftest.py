"""Bootstrap the native Roll parity suite for direct pytest invocation.

The rust-roll CI job sets ``PYTHONPATH=.`` before running
``uv run pytest native/roll-service/parity/``, but trusted factory pre-push
fast checks and any direct ``pytest native/roll-service/parity/test_*.py``
invocation from the repository root do not. The suite imports the repository
application package, so the conftest adds this file's repo root to ``sys.path``
itself; Python still deduplicates module objects because the same root is
inserted. See the #4447/#4200 Roll pool-parity regression attempts that kept
failing collection with ``ModuleNotFoundError: No module named 'app'``.

The disposable-Postgres tests may skip locally when no database is available,
but a CI run without ``RUST_ROLL_TEST_DATABASE_URL`` would silently drop every
database-backed parity assertion, so that configuration fails closed instead.
"""

import os
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[3]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

DATABASE_URL_ENV = "RUST_ROLL_TEST_DATABASE_URL"


def pytest_configure(config: pytest.Config) -> None:
    """Refuse to let CI skip the database-backed parity coverage."""
    if os.environ.get("CI") and not os.environ.get(DATABASE_URL_ENV):
        raise pytest.UsageError(
            f"{DATABASE_URL_ENV} must be set in CI; without it every "
            "database-backed parity test skips and the job passes on no coverage."
        )
