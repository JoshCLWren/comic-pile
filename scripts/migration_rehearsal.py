"""Disposable-Postgres migration rehearsal runner (issue #3554).

Production deploy rehearses pending Alembic migrations against a throwaway
PostgreSQL database before touching the production (Neon) database. This module
owns that rehearsal so the CI job, the deploy workflow and local runs share one
fail-closed implementation.

The canonical rehearsal sequence for a disposable database prepared at the
migration base revision is:

1. ``upgrade_base`` - ensure the disposable schema sits at the rehearsal base;
2. ``apply_fixture`` - load the prod-shaped synthetic migration fixture;
3. ``upgrade_head`` - run ``alembic upgrade head`` from the fixture revision;
4. ``downgrade_base`` - run ``alembic downgrade <base>`` to roll back applied work;
5. ``upgrade_head`` - run ``alembic upgrade head`` again to re-apply.

Every step is timed and fail-closed: the first failing step raises
:class:`MigrationRehearsalError` and the runner stops, so a rehearsal can never
report success through a partial cycle.

Deploy gates treat any rehearsal failure as fatal and must not proceed to the
production migration; production is never used as the rehearsal database.
"""

from __future__ import annotations

import time
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

from alembic import command
from alembic.config import Config

#: Ordered rehearsal steps executed against the disposable database.
REHEARSAL_STEPS: tuple[str, ...] = (
    "upgrade_base",
    "apply_fixture",
    "upgrade_head",
    "downgrade_base",
    "upgrade_head",
)

ALEMBIC_CONFIG_PATH = Path("alembic.ini")
BASE_REVISION = "base"


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
    fixture_applier: Callable[[], object] | None = None,
) -> MigrationRehearsalResult:
    """Run the disposable-Postgres migration rehearsal cycle.

    Args:
        database_url: Disposable rehearsal database URL (throwaway container).
        alembic_config_path: Repository ``alembic.ini`` path.
        fixture_applier: Optional callable that loads the prod-shaped fixture
            before the upgrade step. When omitted, only the migration cycle runs.

    Returns:
        The per-step results and the final revision reached by the cycle.

    Raises:
        MigrationRehearsalError: When any rehearsal step fails.
    """
    steps: list[RehearsalStepResult] = []
    final_revision: str | None = None

    def _upgrade_base() -> None:
        command.upgrade(_alembic_config(database_url, alembic_config_path), BASE_REVISION)

    def _upgrade_head() -> None:
        nonlocal final_revision
        config = _alembic_config(database_url, alembic_config_path)
        command.upgrade(config, "head")
        final_revision = command.current_head(config)

    def _downgrade_base() -> None:
        command.downgrade(_alembic_config(database_url, alembic_config_path), BASE_REVISION)

    steps.append(_run_step("upgrade_base", _upgrade_base))
    if fixture_applier is not None:
        steps.append(_run_step("apply_fixture", fixture_applier))
    steps.append(_run_step("upgrade_head", _upgrade_head))
    steps.append(_run_step("downgrade_base", _downgrade_base))
    steps.append(_run_step("upgrade_head", _upgrade_head))

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
        "--apply-fixture",
        action="store_true",
        help="Load the prod-shaped migration fixture before upgrading",
    )
    args = parser.parse_args(argv)

    fixture_applier = None
    if args.apply_fixture:
        from scripts.generate_migration_fixture import apply_fixture

        fixture_applier = apply_fixture

    try:
        result = run_migration_rehearsal(
            args.database_url,
            alembic_config_path=args.alembic_config,
            fixture_applier=fixture_applier,
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
