"""Disposable-Postgres migration rehearsal runner (issue #3554).

Production deploy rehearses pending Alembic migrations against a throwaway
PostgreSQL database before touching the production (Neon) database. This module
owns that rehearsal so the CI job, the deploy workflow and local runs share one
fail-closed implementation.

The canonical rehearsal sequence against a disposable database is:

1. ``upgrade_head`` - run ``alembic upgrade head`` (fresh disposable database -> head);
2. ``apply_fixture`` - load the prod-shaped synthetic migration fixture;
3. ``downgrade_base`` - run ``alembic downgrade <base_revision>`` to roll back the migrations under rehearsal;
4. ``upgrade_head`` - run ``alembic upgrade head`` again to re-apply.

Every step is timed and fail-closed: the first failing step raises
:class:`MigrationRehearsalError` and the runner stops, so a rehearsal can never
report success through a partial cycle.

Deploy gates treat any rehearsal failure as fatal and must not proceed to the
production migration; production is never used as the rehearsal database. The
rollback target defaults to the migration base revision and is scoped to the
migration set under rehearsal by deploy/CI callers.
"""

from __future__ import annotations

import os
import time
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

from alembic import command
from alembic.config import Config
from alembic.script import ScriptDirectory
from sqlalchemy import create_engine
from sqlalchemy.engine import Engine

#: Ordered rehearsal steps executed against the disposable database.
REHEARSAL_STEPS: tuple[str, ...] = (
    "upgrade_head",
    "apply_fixture",
    "downgrade_base",
    "upgrade_head",
)

ALEMBIC_CONFIG_PATH = Path("alembic.ini")
# Default rollback target: one revision down. A full ``base`` downgrade is not
# possible because history-preserving migrations are deliberately irreversible;
# CI and deploy pass the PR's base Alembic head explicitly.
BASE_REVISION = "-1"


class MigrationRehearsalError(RuntimeError):
    """Raised when a migration rehearsal step fails (fail-closed)."""


@dataclass(frozen=True)
class RehearsalStepResult:
    """Outcome of one migration rehearsal step."""

    step: str
    duration_ms: float
    error: str | None = None


@dataclass(frozen=True)
class MigrationRehearsalResult:
    """Aggregate outcome of a completed migration rehearsal."""

    final_revision: str | None
    steps: tuple[RehearsalStepResult, ...]


def _sync_database_url(database_url: str) -> str:
    """Normalize a database URL for Alembic's synchronous psycopg driver.

    Alembic runs migrations on a synchronous engine, while the application
    standard is the async-only asyncpg driver. The conversion mirrors
    ``alembic/env.py`` so rehearsal targets behave exactly like migration runs.

    Args:
        database_url: Database URL, possibly driver-qualified.

    Returns:
        A URL the synchronous Alembic engine accepts.
    """
    url = database_url.strip()
    if url.startswith("postgresql+asyncpg://"):
        return "postgresql+psycopg://" + url[len("postgresql+asyncpg://") :]
    if url.startswith("postgresql://"):
        return "postgresql+psycopg://" + url[len("postgresql://") :]
    if url.startswith("postgres://"):
        return "postgresql+psycopg://" + url[len("postgres://") :]
    return url


def _alembic_config(database_url: str, alembic_config_path: Path) -> Config:
    """Build an Alembic config bound to one rehearsal database URL.

    Args:
        database_url: Disposable rehearsal database URL.
        alembic_config_path: Repository ``alembic.ini`` path.

    Returns:
        Configured Alembic config.
    """
    config = Config(str(alembic_config_path))
    config.set_main_option("sqlalchemy.url", _sync_database_url(database_url))
    return config


def _run_step(step: str, action: Callable[[], object]) -> RehearsalStepResult:
    """Execute one rehearsal step, timing it and failing closed on error.

    Args:
        step: Rehearsal step name (for evidence reporting).
        action: Zero-argument callable performing the step.

    Returns:
        The step result.

    Raises:
        MigrationRehearsalError: When the step fails; no later step runs.
    """
    started = time.monotonic()
    error: str | None = None
    try:
        action()
    except Exception as exc:
        error = f"{type(exc).__name__}: {exc}"
        raise MigrationRehearsalError(f"migration rehearsal step {step!r} failed: {error}") from exc
    finally:
        duration_ms = (time.monotonic() - started) * 1000
    return RehearsalStepResult(step=step, duration_ms=round(duration_ms, 3), error=error)


def run_migration_rehearsal(
    database_url: str,
    *,
    alembic_config_path: Path = ALEMBIC_CONFIG_PATH,
    fixture_applier: Callable[[Engine], None] | None = None,
    base_revision: str = BASE_REVISION,
    budget_seconds: float | None = None,
) -> MigrationRehearsalResult:
    """Run the disposable-Postgres migration rehearsal cycle.

    Args:
        database_url: Disposable rehearsal database URL (throwaway container).
        alembic_config_path: Repository ``alembic.ini`` path.
        fixture_applier: Optional callable that receives the disposable sync
            engine and loads the prod-shaped fixture before the rollback step.
            When omitted, only the migration cycle runs.
        base_revision: Migration revision the rollback step targets (the base
            revision of the migration set under rehearsal, or ``-1``).
        budget_seconds: Optional migration safety budget. When the summed step
            duration exceeds it the rehearsal fails closed.

    Returns:
        The per-step results and the final revision reached by the cycle.

    Raises:
        MigrationRehearsalError: When any rehearsal step fails.
    """
    steps: list[RehearsalStepResult] = []
    final_revision: str | None = None
    sync_url = _sync_database_url(database_url)
    engine = create_engine(sync_url) if fixture_applier is not None else None

    def _upgrade_head() -> None:
        nonlocal final_revision
        config = _alembic_config(database_url, alembic_config_path)
        command.upgrade(config, "head")
        final_revision = ScriptDirectory.from_config(config).get_current_head()

    def _downgrade_base() -> None:
        command.downgrade(_alembic_config(database_url, alembic_config_path), base_revision)

    # alembic/env.py prefers DATABASE_URL over the config URL. Pin it to the
    # disposable database so an ambient (production) DATABASE_URL can never
    # redirect the rehearsal.
    previous_database_url = os.environ.get("DATABASE_URL")
    os.environ["DATABASE_URL"] = sync_url
    try:
        steps.append(_run_step("upgrade_head", _upgrade_head))
        if fixture_applier is not None and engine is not None:
            steps.append(_run_step("apply_fixture", lambda: fixture_applier(engine)))
        steps.append(_run_step("downgrade_base", _downgrade_base))
        steps.append(_run_step("upgrade_head", _upgrade_head))
    finally:
        if previous_database_url is None:
            os.environ.pop("DATABASE_URL", None)
        else:
            os.environ["DATABASE_URL"] = previous_database_url
        if engine is not None:
            engine.dispose()

    total_seconds = sum(step.duration_ms for step in steps) / 1000
    if budget_seconds is not None and total_seconds > budget_seconds:
        raise MigrationRehearsalError(
            f"migration rehearsal took {total_seconds:.1f}s, over the {budget_seconds:.1f}s safety budget"
        )
    return MigrationRehearsalResult(final_revision=final_revision, steps=tuple(steps))


def main(argv: list[str] | None = None) -> int:
    """CLI entry point for the migration rehearsal.

    Args:
        argv: Optional argument vector; defaults to ``sys.argv``.

    Returns:
        Process exit code: 0 when the rehearsal cycle passes, 1 on failure.
    """
    import argparse

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--database-url", required=True, help="Disposable rehearsal database URL")
    parser.add_argument(
        "--alembic-config",
        type=Path,
        default=ALEMBIC_CONFIG_PATH,
        help="Path to alembic.ini",
    )
    parser.add_argument(
        "--base-revision",
        default=BASE_REVISION,
        help="Migration revision the rollback step targets (default: -1)",
    )
    parser.add_argument(
        "--budget-seconds",
        type=float,
        default=None,
        help="Fail when the rehearsal's total step time exceeds this migration safety budget",
    )
    parser.add_argument(
        "--apply-fixture",
        action="store_true",
        help="Load the prod-shaped migration fixture before upgrading",
    )
    args = parser.parse_args(argv)

    # Importing app models loads settings that require DATABASE_URL; make sure
    # any ambient (possibly production) value is replaced by the disposable one.
    os.environ["DATABASE_URL"] = _sync_database_url(args.database_url)

    fixture_applier = None
    if args.apply_fixture:
        import sys

        repo_root = Path(__file__).resolve().parents[1]
        if str(repo_root) not in sys.path:
            sys.path.insert(0, str(repo_root))
        from scripts.generate_migration_fixture import apply_fixture

        fixture_applier = apply_fixture

    try:
        result = run_migration_rehearsal(
            args.database_url,
            alembic_config_path=args.alembic_config,
            fixture_applier=fixture_applier,
            base_revision=args.base_revision,
            budget_seconds=args.budget_seconds,
        )
    except MigrationRehearsalError as error:
        print(f"MIGRATION REHEARSAL FAILED: {error}")
        return 1
    for step in result.steps:
        status = "ok" if step.error is None else f"FAILED ({step.error})"
        print(f"migration-rehearsal step {step.step}: {status} ({step.duration_ms}ms)")
    print(f"Migration rehearsal completed; final revision: {result.final_revision}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
