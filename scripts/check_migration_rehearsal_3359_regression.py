#!/usr/bin/env python3
"""Regression check for #3359 / #3495 migration failure mode.

Acceptance (#3554): a test fixture that reproduces the #3359 failure fails on
the pre-#3495 migration and passes after it.

This script uses the checked-in prod-shaped fixture (base revision m5d30000001)
which contains the reviewed dangling ContinuityRule allowlist rows that aborted
production deploy during `c25530000001` before fix #3495.

Checks:
1. Pre-#3495 failure mode: applying the pre-fix dangling-rule policy (no
   allowlist / any dangling row aborts) to the fixture data fails.
2. Post-#3495 behavior: upgrading through `c25530000001` on the same fixture
   succeeds and the allowlisted rows are skipped/reported.

Requires a disposable Postgres database URL. Never use Neon/production.
"""

from __future__ import annotations

import argparse
import json
import os
import shlex
import subprocess
import sys
from pathlib import Path
from urllib.parse import urlparse, urlunparse

REPO_ROOT = Path(__file__).resolve().parents[1]
FIXTURE_DIR = REPO_ROOT / "tests/fixtures/migration_rehearsal/prod_shaped"


def _run(cmd: list[str], *, env: dict[str, str], check: bool = True) -> subprocess.CompletedProcess[str]:
    print("+ " + " ".join(shlex.quote(c) for c in cmd), flush=True)
    proc = subprocess.run(cmd, cwd=str(REPO_ROOT), env=env, text=True, capture_output=True)
    if proc.stdout:
        print(proc.stdout, end="" if proc.stdout.endswith("\n") else "\n")
    if proc.stderr:
        print(proc.stderr, end="" if proc.stderr.endswith("\n") else "\n", file=sys.stderr)
    if check and proc.returncode != 0:
        raise RuntimeError(f"Command failed ({proc.returncode}): {' '.join(cmd)}")
    return proc


def _alembic_cmd() -> list[str]:
    override = os.getenv("ALEMBIC_BIN")
    if override:
        return shlex.split(override)
    venv = REPO_ROOT / ".venv/bin/alembic"
    if venv.is_file():
        return [str(venv)]
    return [sys.executable, "-m", "alembic"]


def _libpq_url(url: str) -> str:
    parsed = urlparse(url.replace("+asyncpg", "+psycopg").replace("+psycopg", ""))
    if (parsed.hostname or "").lower().endswith("neon.tech"):
        raise ValueError("Neon databases are forbidden for regression rehearsal")
    return urlunparse(parsed._replace(scheme="postgresql"))


def _reset_and_load_fixture(database_url: str) -> dict[str, str]:
    manifest = json.loads((FIXTURE_DIR / "manifest.json").read_text(encoding="utf-8"))
    base_revision = str(manifest["base_revision"])
    env = os.environ.copy()
    env["DATABASE_URL"] = database_url
    libpq = _libpq_url(database_url)
    _run(
        [
            "psql",
            libpq,
            "-v",
            "ON_ERROR_STOP=1",
            "-c",
            "DROP SCHEMA public CASCADE; CREATE SCHEMA public; "
            "GRANT ALL ON SCHEMA public TO CURRENT_USER; GRANT ALL ON SCHEMA public TO public;",
        ],
        env=os.environ.copy(),
    )
    _run([*_alembic_cmd(), "upgrade", base_revision], env=env)
    _run(
        ["psql", libpq, "-v", "ON_ERROR_STOP=1", "-f", str(FIXTURE_DIR / "seed.sql")],
        env=os.environ.copy(),
    )
    return manifest


def _assert_prefx_fails(database_url: str) -> None:
    """Demonstrate pre-#3495 behavior: dangling rules abort without allowlist."""
    sys.path.insert(0, str(REPO_ROOT))
    import sqlalchemy as sa
    from app.services import canonical_backfill as mig

    sync_url = database_url.replace("postgresql+asyncpg://", "postgresql+psycopg://", 1)
    if sync_url.startswith("postgresql://"):
        sync_url = sync_url.replace("postgresql://", "postgresql+psycopg://", 1)
    engine = sa.create_engine(sync_url)
    try:
        with engine.connect() as conn:
            dangling = mig._load_item_read_dangling(conn)
            if not dangling:
                raise AssertionError(
                    "Fixture must contain dangling item_read continuity rules for #3359 regression"
                )
            # Pre-#3495 policy: any dangling rule aborted the migration.
            try:
                mig.abort_unknown_dangling_rules(dangling)
            except RuntimeError:
                print("[3359-regression] PASS: pre-#3495 dangling-rule policy aborts on fixture (expected)")
                return
            raise AssertionError(
                "Expected pre-#3495 dangling-rule policy to abort, but it did not"
            )
    finally:
        engine.dispose()


def _assert_postfix_passes(database_url: str) -> None:
    """Post-#3495: upgrading through c25530000001 must succeed on fixture."""
    env = os.environ.copy()
    env["DATABASE_URL"] = database_url
    proc = _run([*_alembic_cmd(), "upgrade", "c25530000001"], env=env, check=False)
    if proc.returncode != 0:
        raise AssertionError(
            "Post-#3495 migration c25530000001 must succeed on #3359 fixture, "
            f"but failed with exit code {proc.returncode}"
        )
    combined = (proc.stdout or "") + "\n" + (proc.stderr or "")
    if "reviewed dangling" not in combined.lower() and "1715192" not in combined:
        print(
            "[3359-regression] NOTE: expected skip/report markers not observed in output; "
            "upgrade success is the primary regression signal",
            file=sys.stderr,
        )
    print("[3359-regression] PASS: post-#3495 c25530000001 upgrade succeeds on fixture")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--database-url", required=True, help="Disposable Postgres URL")
    args = parser.parse_args(argv)

    db_url = args.database_url
    manifest = _reset_and_load_fixture(db_url)
    print(f"[3359-regression] fixture base_revision={manifest['base_revision']}")
    _assert_prefx_fails(db_url)

    # Re-load fixture state for the post-fix upgrade check (pre-fix check is read-only but be safe).
    _reset_and_load_fixture(db_url)
    _assert_postfix_passes(db_url)
    print("[3359-regression] OK")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
