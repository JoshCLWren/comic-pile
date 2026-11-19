#!/usr/bin/env python3
"""Audit the production database schema against the canonical fixture.

Scheduled, read-only comparison of production Neon PostgreSQL with the
committed Alembic-canonical dump at
``native/roll-service/tests/fixtures/schema/public_schema.sql`` (issue #4735).
The dump reuses the export normalizer from ``export_roll_test_schema`` plus
order-insensitive statement comparison, so owner/grant/version/ordering noise
does not mask real column/index/constraint/function changes.

Safety contract (no exceptions):

* The credential is read only from an environment variable
  (``--database-url-env``, default ``PRODUCTION_SCHEMA_AUDIT_DATABASE_URL``)
  and transported to ``pg_dump`` through ``PG*`` environment variables.
  The DSN or password is never placed in ``argv``, logs, summaries, or
  artifacts, and failures are redacted before printing.
* The session is read-only (role-level plus
  ``default_transaction_read_only=on``) and connect/statement timeouts are
  bounded. The dump itself is schema-only.
* This script performs no writes, creates no branches, and never reuses an
  admin or application-writer credential: the caller must provide the
  dedicated least-privilege role documented in
  ``docs/PRODUCTION_SCHEMA_AUDIT.md``.

Exit codes: 0 schemas match, 1 schemas differ, 2 operational failure.
"""

from __future__ import annotations

import argparse
import os
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Never
from urllib.parse import parse_qsl, urlsplit

REPO_ROOT = Path(__file__).resolve().parents[1]

try:
    from scripts.export_roll_test_schema import (
        FIXTURE_PATH,
        _compare_normalized_schemas,
        _normalize,
        _redact,
    )
except ImportError:
    # Direct runs (workflow, Makefile) have `scripts/` rather than the repo
    # root on sys.path; pytest provides the root via its rootdir insertion.
    sys.path.insert(0, str(REPO_ROOT))
    from scripts.export_roll_test_schema import (
        FIXTURE_PATH,
        _compare_normalized_schemas,
        _normalize,
        _redact,
    )
DEFAULT_TIMEOUT_SECONDS = 120
DEFAULT_MAX_DIFF_LINES = 200


def _fail(message: str) -> Never:
    """Print a redacted diagnostic and exit with the operational-error code.

    Args:
        message: Diagnostic text (must already be redacted when it could
            contain credential material).

    Raises:
        SystemExit: Always, with exit code 2.
    """
    print(message, file=sys.stderr)
    raise SystemExit(2)


def _parse_dsn(dsn: str) -> dict[str, str]:
    """Split a PostgreSQL DSN into libpq ``PG*`` properties.

    Args:
        dsn: A ``postgresql://user:password@host:port/db?sslmode=...`` URL.

    Returns:
        A dict with host, port, database, user, password, and sslmode keys.

    Raises:
        ValueError: If the DSN is malformed or not PostgreSQL.
    """
    parts = urlsplit(dsn)
    if parts.scheme not in {"postgresql", "postgresql+asyncpg", "postgresql+psycopg"}:
        raise ValueError("database URL must use the postgresql scheme")
    query = dict(parse_qsl(parts.query))
    host = parts.hostname or ""
    database = (parts.path or "").lstrip("/")
    if not host or not database:
        raise ValueError("database URL must include a host and a database name")
    return {
        "host": host,
        "port": str(parts.port) if parts.port is not None else "5432",
        "database": database,
        "user": parts.username or "",
        "password": parts.password or "",
        # Neon production URLs always pin sslmode=require; the default stays
        # `prefer` so local non-SSL throwaway databases remain auditable.
        "sslmode": query.get("sslmode", "prefer"),
    }


def _child_env(properties: dict[str, str]) -> dict[str, str]:
    """Build the subprocess environment carrying the credential safely.

    Args:
        properties: A dict as returned by `_parse_dsn`.

    Returns:
        A new environment with ``PG*`` connection settings including a
        read-only session and bounded timeouts. The password travels only
        in ``PGPASSWORD``, never in ``argv``.
    """
    env = dict(os.environ)
    env["PGHOST"] = properties["host"]
    env["PGPORT"] = properties["port"]
    env["PGDATABASE"] = properties["database"]
    env["PGUSER"] = properties["user"]
    env["PGPASSWORD"] = properties["password"]
    env["PGSSLMODE"] = properties["sslmode"]
    env["PGCONNECT_TIMEOUT"] = "10"
    env["PGAPPNAME"] = "comic-pile-schema-audit"
    # Read-only session plus bounded statement/lock wait. pg_dump only needs
    # to read catalogs, so a read-only transaction serially dumps fine.
    env["PGOPTIONS"] = (
        "-c default_transaction_read_only=on"
        " -c statement_timeout=60000"
        " -c lock_timeout=30000"
    )
    return env


def _dump_schema(env: dict[str, str], secrets: list[str], timeout: int) -> str:
    """Dump the public schema with ``pg_dump`` using env-only credentials.

    Args:
        env: Subprocess environment from `_child_env`.
        secrets: Raw secrets to redact from errors (the DSN and password).
        timeout: Maximum seconds to wait for ``pg_dump``.

    Returns:
        The normalized schema-only dump text.

    Raises:
        SystemExit: With exit code 2 and a redacted diagnostic on failure.
    """
    if shutil.which("pg_dump") is None:
        _fail("pg_dump not found in PATH; install the PostgreSQL client tools.")
    try:
        result = subprocess.run(
            [
                "pg_dump",
                "--schema-only",
                "--no-owner",
                "--no-privileges",
                "--no-comments",
            ],
            env=env,
            check=False,
            capture_output=True,
            text=True,
            timeout=timeout,
        )
    except subprocess.TimeoutExpired:
        _fail(f"pg_dump timed out after {timeout}s; refusing to proceed.")
    if result.returncode != 0:
        diagnostic = _redact(result.stderr.strip(), secrets)
        _fail(f"pg_dump failed: {diagnostic}")
    return _normalize(_redact(result.stdout, secrets))


def _write_diff_output(
    path: Path,
    fixture_sql: str,
    live_sql: str,
    max_lines: int,
    secrets: list[str],
) -> str:
    """Build a bounded, redacted unified diff of the normalized schemas.

    Args:
        path: Where to write the diff artifact.
        fixture_sql: Canonical fixture dump text.
        live_sql: Live database dump text.
        max_lines: Maximum diff lines to include before truncation.
        secrets: Raw secrets to redact before writing.

    Returns:
        The diff text (also written to ``path`` when non-empty).
    """
    import difflib

    from scripts.export_roll_test_schema import _normalize_catalog

    fixture_lines = _normalize_catalog(fixture_sql).splitlines(keepends=True)
    live_lines = _normalize_catalog(live_sql).splitlines(keepends=True)
    diff = difflib.unified_diff(
        fixture_lines,
        live_lines,
        fromfile="canonical-fixture",
        tofile="production-live",
    )
    limited: list[str] = []
    truncated = False
    for line in diff:
        if len(limited) >= max_lines:
            truncated = True
            break
        limited.append(line)
    text = _redact("".join(limited), secrets)
    if truncated:
        text += f"\n(diff truncated at {max_lines} lines)\n"
    path.write_text(text, encoding="utf-8")
    return text


def main() -> int:
    """Dump production, compare to the canonical fixture, and report."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--database-url-env",
        default="PRODUCTION_SCHEMA_AUDIT_DATABASE_URL",
        help=(
            "Name of the environment variable holding the direct PostgreSQL "
            "URL of the dedicated read-only audit role. The URL itself is "
            "never accepted on the command line."
        ),
    )
    parser.add_argument(
        "--fixture",
        default=str(FIXTURE_PATH),
        help="Canonical fixture SQL to compare against.",
    )
    parser.add_argument(
        "--timeout",
        type=int,
        default=DEFAULT_TIMEOUT_SECONDS,
        help="Maximum seconds to wait for pg_dump (default: 120).",
    )
    parser.add_argument(
        "--max-diff-lines",
        type=int,
        default=DEFAULT_MAX_DIFF_LINES,
        help="Maximum unified-diff lines to report and write (default: 200).",
    )
    parser.add_argument(
        "--diff-output",
        default=None,
        help="Optional path to write the bounded redacted diff artifact.",
    )
    args = parser.parse_args()

    dsn = os.environ.get(args.database_url_env, "")
    if not dsn:
        _fail(
            f"{args.database_url_env} is not set. Provide a direct PostgreSQL URL "
            "for the dedicated least-privilege read-only audit role; see "
            "docs/PRODUCTION_SCHEMA_AUDIT.md. Refusing to fall back to any "
            "other credential."
        )
    try:
        properties = _parse_dsn(dsn)
    except ValueError as error:
        _fail(f"invalid database URL in {args.database_url_env}: {error}")
    if properties["user"] in {"", "postgres", "neondb_owner"}:
        _fail(
            "refusing to run with an admin/owner database user; provision the "
            "dedicated read-only audit role (docs/PRODUCTION_SCHEMA_AUDIT.md)."
        )
    if not properties["password"]:
        _fail(
            "audit role URL has no password; provision the dedicated "
            "least-privilege role with password authentication."
        )

    fixture_path = Path(args.fixture)
    if not fixture_path.exists():
        _fail(f"missing canonical fixture: {fixture_path}")
    fixture_sql = fixture_path.read_text(encoding="utf-8")

    env = _child_env(properties)
    secrets = [dsn, properties["password"]]
    live_sql = _dump_schema(env, secrets, args.timeout)

    comparison = _compare_normalized_schemas(fixture_sql, live_sql)
    added = comparison["added"]
    removed = comparison["removed"]
    changed = comparison["changed"]

    print(f"canonical fixture: {args.fixture}")
    print(f"added: {len(added)}; removed: {len(removed)}; changed: {len(changed)}")
    for title, entries in (("added", added), ("removed", removed), ("changed", changed)):
        for entry in entries[:50]:
            print(f"{title}: {entry}")
        remaining = len(entries) - 50
        if remaining > 0:
            print(f"{title}: ... and {remaining} more")

    if args.diff_output:
        text = _write_diff_output(
            Path(args.diff_output),
            fixture_sql,
            live_sql,
            args.max_diff_lines,
            secrets,
        )
        print(f"wrote bounded diff artifact: {args.diff_output} ({len(text)} chars)")

    if added or removed or changed:
        print(
            "production schema differs from the canonical fixture. "
            "Regenerate the fixture from the Alembic head (make roll-test-schema) "
            "after confirming the difference is expected; do not edit the "
            "fixture by hand."
        )
        return 1
    print("production schema matches the canonical fixture.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
