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
import shutil
import subprocess
import sys
from pathlib import Path

from scripts.schema_normalization import (
    normalize_schema,
    qualify_extension_operator_classes,
)

REPO_ROOT = Path(__file__).resolve().parents[1]
FIXTURE_PATH = REPO_ROOT / "native/roll-service/tests/fixtures/schema/public_schema.sql"


def _qualify_extension_operator_classes(sql: str) -> str:
    """Qualify ``pg_trgm`` operator classes so empty ``search_path`` can replay.

    Retained as a compatibility name; the implementation lives in
    :mod:`scripts.schema_normalization` so the production drift check
    normalizes identically.
    """
    return qualify_extension_operator_classes(sql)


def _normalize(raw: str) -> str:
    """Strip psql-only meta-commands and version-dependent banners.

    Compatibility alias for :func:`scripts.schema_normalization.normalize_schema`.
    """
    return normalize_schema(raw)


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
