#!/usr/bin/env python3
"""Regenerate the checked-in migration rehearsal fixture.

Creates a throwaway Postgres database at the fixture's base Alembic revision,
loads the canonical prod-shaped seed, and rewrites seed.sql as a deterministic
pg_dump of the seeded data. Never use Neon/production databases.

Usage:
  python3 scripts/generate_migration_rehearsal_fixture.py \
    --database-url postgresql://postgres:postgres@127.0.0.1:5432/mig_fixture_gen

The database URL must point to a disposable local/container Postgres instance.
"""

from __future__ import annotations

import argparse
import json
import os
import shlex
import subprocess
import sys
import tempfile
from pathlib import Path
from urllib.parse import urlparse, urlunparse

REPO_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_FIXTURE_DIR = REPO_ROOT / "tests/fixtures/migration_rehearsal/prod_shaped"

# Tables to include in the data-only fixture dump, in dependency-safe order.
# Keep this aligned with seed content and foreign-key dependencies.
SEED_TABLES = [
    "users",
    "threads",
    "issues",
    "dependencies",
    "continuity_plans",
    "continuity_rules",
    "cbl_sources",
    "cbl_source_lists",
    "cbl_source_entries",
    "reading_plan_sources",
    "reading_plan_issues",
    "reading_orders",
    "reading_order_items",
]


def _eprint(msg: str) -> None:
    print(msg, file=sys.stderr)


def _run(cmd: list[str], *, env: dict[str, str] | None = None, cwd: Path = REPO_ROOT) -> None:
    print("+ " + " ".join(shlex.quote(c) for c in cmd), flush=True)
    proc = subprocess.run(cmd, cwd=str(cwd), env=env or os.environ.copy(), check=False)
    if proc.returncode != 0:
        raise RuntimeError(f"Command failed ({proc.returncode}): {' '.join(cmd)}")


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
    if parsed.scheme not in {"postgresql", "postgres"}:
        raise ValueError(f"Unsupported URL scheme: {parsed.scheme!r}")
    host = (parsed.hostname or "").lower()
    if "neon.tech" in host or "neon.build" in host:
        raise ValueError("Neon/preview databases are forbidden for fixture generation")
    return urlunparse(parsed._replace(scheme="postgresql"))


def _load_manifest(fixture_dir: Path) -> dict[str, str]:
    with (fixture_dir / "manifest.json").open(encoding="utf-8") as handle:
        return json.load(handle)


def _reset_schema(libpq: str) -> None:
    env = os.environ.copy()
    env["PGCONNECT_TIMEOUT"] = env.get("PGCONNECT_TIMEOUT", "10")
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
        env=env,
    )


def _dump_seed(libpq: str, fixture_dir: Path) -> None:
    """Dump seeded data tables to seed.sql (deterministic inserts)."""
    cmd = [
        "pg_dump",
        libpq,
        "--data-only",
        "--inserts",
        "--column-inserts",
        "--rows-per-insert=100",
        "--no-owner",
        "--no-privileges",
        "--no-comments",
    ]
    for table in SEED_TABLES:
        cmd.extend(["--table", f"public.{table}"])
    print("+ " + " ".join(shlex.quote(c) for c in cmd) + " > seed.sql", flush=True)
    env = os.environ.copy()
    env["PGCONNECT_TIMEOUT"] = env.get("PGCONNECT_TIMEOUT", "10")
    proc = subprocess.run(cmd, cwd=str(REPO_ROOT), env=env, text=True, capture_output=True, check=False)
    if proc.returncode != 0:
        _eprint(proc.stderr)
        raise RuntimeError(f"pg_dump failed with exit code {proc.returncode}")

    header = (
        "-- Prod-shaped migration rehearsal seed for #3554 (regenerated).\n"
        "-- Loaded after: alembic upgrade <base_revision> (see manifest.json).\n"
        "-- Synthetic/anonymized data only. No production credentials or PII.\n"
        "-- Regenerate with: python3 scripts/generate_migration_rehearsal_fixture.py --database-url <throwaway-db>\n\n"
        "BEGIN;\n"
        "SET session_replication_role = 'replica';\n\n"
    )
    footer = "\nSET session_replication_role = 'origin';\nCOMMIT;\n"
    body = proc.stdout.strip() + "\n"
    # Normalize sequence setval noise only if desired; keep dump as-is for fidelity.
    out = header + body + footer
    seed_path = fixture_dir / "seed.sql"
    seed_path.write_text(out, encoding="utf-8")
    print(f"Wrote {seed_path}", flush=True)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--database-url", required=True, help="Throwaway Postgres URL")
    parser.add_argument("--fixture-dir", type=Path, default=DEFAULT_FIXTURE_DIR)
    parser.add_argument(
        "--source-seed",
        type=Path,
        default=None,
        help="Seed SQL to load before dumping (default: <fixture-dir>/seed.sql)",
    )
    parser.add_argument(
        "--dump-only",
        action="store_true",
        help="Assume DB already contains seeded data at base revision; only dump",
    )
    args = parser.parse_args(argv)

    fixture_dir = args.fixture_dir.resolve()
    manifest = _load_manifest(fixture_dir)
    base_revision = str(manifest["base_revision"])
    libpq = _libpq_url(args.database_url)
    source_seed = (args.source_seed or (fixture_dir / "seed.sql")).resolve()

    env = os.environ.copy()
    env["DATABASE_URL"] = args.database_url

    if not args.dump_only:
        _reset_schema(libpq)
        _run([*_alembic_cmd(), "upgrade", base_revision], env=env)
        if not source_seed.is_file():
            raise FileNotFoundError(f"Source seed not found: {source_seed}")
        _run(["psql", libpq, "-v", "ON_ERROR_STOP=1", "-f", str(source_seed)], env=os.environ.copy())

    _dump_seed(libpq, fixture_dir)
    print(f"Regenerated fixture at {fixture_dir} (base_revision={base_revision})", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
