#!/usr/bin/env python3
"""Export the canonical Alembic schema as the native Roll test fixture.

The native Roll service is a pure cutover: it never creates or alters schema
objects. Its integration tests therefore must not hand-write tables either.
They load this fixture, which is a `pg_dump --schema-only` of a database that
Alembic migrated to head, so every Rust test runs against the schema
production actually serves.

Regenerate after any Alembic migration:

    make roll-test-schema

CI regenerates and diffs (`--check`), so a stale fixture fails the build
instead of silently drifting from the migrations.
"""

from __future__ import annotations

import argparse
import os
import re
import shutil
import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
FIXTURE_PATH = REPO_ROOT / "native/roll-service/src/schema/public_schema.sql"

# pg_dump emits psql meta-commands and version banners that vary by client
# version or per invocation. Dropping them keeps the fixture diffable and
# loadable through a plain SQL batch (no psql required).
DROPPED_PREFIXES = ("\\restrict", "\\unrestrict")
DROPPED_COMMENT_PREFIXES = (
    "-- Dumped from database version",
    "-- Dumped by pg_dump version",
)
# pg_dump emits settings newer than the oldest server the suite supports
# (PostgreSQL 16, the CI image). Loading them into 16 is a hard error.
DROPPED_SETTINGS = ("SET transaction_timeout = 0;",)
# `public` always exists; restoring the schema statement only breaks loading.
# The fixture is a whole-database dump so extension creation (pg_trgm, created
# by migration c40080000001) travels with the tables that index with it.
DROPPED_STATEMENTS = ("CREATE SCHEMA public;",)
# pg_dump always emits `SET search_path = ''`. Some client versions then leave
# the pg_trgm GIN operator class unqualified. Qualify it so the fixture replays
# against an empty search_path the same way production objects live in public.
_UNQUALIFIED_GIN_TRGM_OPS = re.compile(r"(?<![\w.])gin_trgm_ops\b")


def _qualify_extension_operator_classes(sql: str) -> str:
    """Qualify ``pg_trgm`` operator classes so empty ``search_path`` can replay.

    Production creates ``pg_trgm`` in ``public`` (Alembic ``c40080000001``).
    The dump must name ``public.gin_trgm_ops`` explicitly because pg_dump
    clears ``search_path`` before emitting index DDL. Already-qualified names
    are left unchanged so regeneration stays idempotent across pg_dump versions.

    Args:
        sql: Schema-only SQL, possibly with unqualified ``gin_trgm_ops``.

    Returns:
        The same SQL with every bare ``gin_trgm_ops`` token schema-qualified.
    """
    return _UNQUALIFIED_GIN_TRGM_OPS.sub("public.gin_trgm_ops", sql)


def _normalize(raw: str) -> str:
    """Strip psql-only meta-commands and version-dependent banners."""
    kept: list[str] = []
    for line in raw.splitlines():
        stripped = line.strip()
        if stripped.startswith(DROPPED_PREFIXES):
            continue
        if stripped.startswith(DROPPED_COMMENT_PREFIXES):
            continue
        if stripped in DROPPED_SETTINGS:
            continue
        if stripped in DROPPED_STATEMENTS:
            continue
        kept.append(line)
    return _qualify_extension_operator_classes("\n".join(kept).rstrip("\n") + "\n")


def _assert_at_head(database_url: str) -> None:
    """Refuse to dump a database that is not migrated to the current head."""
    from alembic.config import Config
    from alembic.script import ScriptDirectory
    from sqlalchemy import create_engine, text

    sync_url = database_url.replace("postgresql+asyncpg://", "postgresql+psycopg://", 1)
    script = ScriptDirectory.from_config(Config(str(REPO_ROOT / "alembic.ini")))
    head = script.get_current_head()
    engine = create_engine(sync_url)
    try:
        with engine.connect() as connection:
            applied = connection.execute(text("SELECT version_num FROM alembic_version")).scalar()
    finally:
        engine.dispose()
    if applied != head:
        raise SystemExit(
            f"database is at alembic revision {applied!r}, but the repository head is {head!r}. "
            "Run `alembic upgrade head` against it before exporting."
        )


def _dump(database_url: str) -> str:
    """Dump the public schema with pg_dump."""
    if shutil.which("pg_dump") is None:
        raise SystemExit("pg_dump not found in PATH; install the PostgreSQL client tools.")
    sync_url = database_url.replace("postgresql+asyncpg://", "postgresql://", 1)
    result = subprocess.run(
        [
            "pg_dump",
            "--schema-only",
            "--no-owner",
            "--no-privileges",
            "--no-comments",
            sync_url,
        ],
        check=False,
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        raise SystemExit(f"pg_dump failed: {result.stderr.strip()}")
    return _normalize(result.stdout)


def main() -> int:
    """Write the fixture, or verify it is current with ``--check``."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--database-url",
        default=None,
        help="Migrated PostgreSQL URL to dump. Defaults to DATABASE_URL.",
    )
    parser.add_argument(
        "--check",
        action="store_true",
        help="Fail instead of writing when the checked-in fixture is stale.",
    )
    args = parser.parse_args()

    database_url = args.database_url or os.environ.get("DATABASE_URL", "")
    if not database_url:
        raise SystemExit("provide --database-url or set DATABASE_URL to a migrated database")

    _assert_at_head(database_url)
    exported = _dump(database_url)

    if args.check:
        if not FIXTURE_PATH.exists():
            raise SystemExit(f"missing fixture: {FIXTURE_PATH.relative_to(REPO_ROOT)}")
        current = FIXTURE_PATH.read_text()
        if current != exported:
            diff = subprocess.run(
                ["diff", "-u", str(FIXTURE_PATH), "-"],
                input=exported,
                text=True,
                capture_output=True,
                check=False,
            )
            print(diff.stdout, file=sys.stderr)
            raise SystemExit(
                "native Roll test schema fixture is stale. Run `make roll-test-schema`."
            )
        print(f"{FIXTURE_PATH.relative_to(REPO_ROOT)} matches the Alembic head schema.")
        return 0

    FIXTURE_PATH.parent.mkdir(parents=True, exist_ok=True)
    FIXTURE_PATH.write_text(exported)
    print(
        f"Wrote {FIXTURE_PATH.relative_to(REPO_ROOT)} "
        f"({len(exported.splitlines())} lines) from the Alembic head schema."
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
