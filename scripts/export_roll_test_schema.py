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
FIXTURE_PATH = REPO_ROOT / "native/roll-service/tests/fixtures/schema/public_schema.sql"

# pg_dump emits psql meta-commands and version banners that vary by client
# version or per invocation. Dropping them keeps the fixture diffable and
# loadable through a plain SQL batch (no psql required).
DROPPED_PREFIXES = ("\\restrict", "\\unrestrict")
DROPPED_COMMENT_PREFIXES = (
    "-- Dumped from database version",
    "-- Dumped by pg_dump version",
)
# pg_dump built with newer PostgreSQL emits per-column storage parameters
# (`ALTER TABLE ... SET (pg_attver=N)`) whose numeric value changes on every
# freshly migrated throwaway database, so the CI fixture check could never
# match byte-for-byte. They carry no portable schema information; the
# canonical fixture describes types/keys/indexes/constraints, not this
# storage-parameter bookkeeping.
_PG_ATTVER_LINE = re.compile(
    r"^ALTER TABLE ONLY \S+ ALTER COLUMN \S+ SET \(pg_attver=\d+\);$"
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
        if _PG_ATTVER_LINE.match(stripped):
            continue
        kept.append(line)
    return _qualify_extension_operator_classes("\n".join(kept).rstrip("\n") + "\n")


# --- Shared schema-comparison normalization (issue #4735) ---------------------
# The audit (`scripts/production_schema_audit.py`) reuses the export
# normalization above and additionally compares dumps order-insensitively.
# Only deliberately-narrow normalization is applied for comparison: session
# `SET` lines, dump ownership/privilege metadata, and extension version
# pins. Real table/column/index/constraint/function changes are never
# normalized away.

# Production-only extensions that are intentionally not part of the canonical
# fixture. Empty on purpose: any platform extension found in production must
# be added here individually with a rationale after the first live run, never
# via a blanket extension/function ignore. See docs/PRODUCTION_SCHEMA_AUDIT.md.
PROD_ONLY_EXTENSION_ALLOWLIST: frozenset[str] = frozenset()

_DOLLAR_TAG = re.compile(r"\$[A-Za-z_][A-Za-z0-9_]*\$|\$\$")
_NAME_COMMENT = re.compile(r"--\s*Name:\s*(.+?);")
_EXTENSION_RE = re.compile(
    r"CREATE\s+EXTENSION\s+IF\s+NOT\s+EXISTS\s+(\w+)(?:\s+WITH\s+SCHEMA\s+(\w+))?",
    re.IGNORECASE,
)


def _split_statements(sql: str) -> list[str]:
    """Split pg_dump output into top-level statement units.

    A unit includes the ``-- Name:``/``-- Type:`` header comments pg_dump
    emits immediately before the statement they describe, so a unit carries
    a stable object identity even when units are reordered. Dollar-quoted
    function bodies and single-quoted strings are tracked so semicolons
    inside them end no statement.

    Args:
        sql: Schema-only SQL, typically the output of `_normalize`.

    Returns:
        Statement units in dump order, each ending with ``;`` or trailing
        comment lines at end of input.
    """
    units: list[str] = []
    pending: list[str] = []
    dollar: str | None = None
    in_single = False
    for line in sql.splitlines():
        if not pending and not line.strip():
            continue
        pending.append(line)
        scan = line
        index = 0
        while index < len(scan):
            if in_single:
                if scan[index] == "'":
                    if index + 1 < len(scan) and scan[index + 1] == "'":
                        index += 2
                        continue
                    in_single = False
                index += 1
                continue
            if dollar is not None:
                if scan.startswith(dollar, index):
                    index += len(dollar)
                    dollar = None
                    continue
                index += 1
                continue
            char = scan[index]
            if char == "-" and index + 1 < len(scan) and scan[index + 1] == "-":
                break
            if char == "'":
                in_single = True
                index += 1
                continue
            if char == "$":
                match = _DOLLAR_TAG.match(scan, index)
                if match is not None:
                    dollar = match.group(0)
                    index += len(dollar)
                    continue
            index += 1
        if dollar is None and not in_single and line.rstrip().endswith(";"):
            units.append("\n".join(pending))
            pending = []
    if any(part.strip() for part in pending):
        units.append("\n".join(pending))
    return units


_TYPE_COMMENT = re.compile(r"--\s*Type:\s*(.+?);\s*Schema:")

# PostgreSQL ruleutils deparse differs between server releases for
# `= ANY (ARRAY[...]::text[])` CHECK expressions: older servers print the
# array-level cast `((ARRAY['a'::character varying, ...])::text[])`, newer
# servers print per-element casts
# `(ARRAY[('a'::character varying)::text, ...])`. Both denote the identical
# membership test, so comparison canonicalizes the newer form into the
# fixture (older) form. Only this exact array-of-varchar-casts shape is
# rewritten; literal lists and operators are preserved verbatim.
_ARRAY_PER_ELEMENT_CAST = re.compile(
    r"\(ARRAY\[((?:\('(?:[^']|'')*'::character varying\)::text(?:, )?)+)\]\)"
)
_ARRAY_ELEMENT = re.compile(r"\('((?:[^']|'')*)'::character varying\)::text")


def _canonicalize_array_memberships(text: str) -> str:
    """Rewrite per-element ``::text`` array casts into array-level casts.

    Args:
        text: One dump line (already split, typically a CHECK clause).

    Returns:
        The same line with every newer-style
        ``(ARRAY[('x'::character varying)::text, ...])`` membership list
        rewritten to the fixture-style
        ``((ARRAY['x'::character varying, ...])::text[])``.
    """

    def _to_array_level(match: re.Match[str]) -> str:
        literals = _ARRAY_ELEMENT.findall(match.group(1))
        members = ", ".join(f"'{item}'::character varying" for item in literals)
        return f"((ARRAY[{members}])::text[])"

    return _ARRAY_PER_ELEMENT_CAST.sub(_to_array_level, text)


def _statement_key(unit: str) -> str:
    """Derive a stable object identity for a statement unit.

    Args:
        unit: One statement unit from `_split_statements`.

    Returns:
        The pg_dump ``-- Name:``/``-- Type:`` identity when present,
        otherwise the first meaningful line collapsed to single spaces.
    """
    match = _NAME_COMMENT.search(unit)
    if match is not None:
        name = match.group(1).strip()
        type_match = _TYPE_COMMENT.search(unit)
        if type_match is not None:
            return f"{name}; Type: {type_match.group(1).strip()}"
        return name
    for line in unit.splitlines():
        stripped = line.strip()
        if stripped and not stripped.startswith("--"):
            return re.sub(r"\s+", " ", stripped)[:120]
    return "<empty>"


def _categorize(unit: str) -> str:
    """Classify a statement unit for the targeted diagnostic summary.

    Args:
        unit: One statement unit from `_split_statements`.

    Returns:
        A coarse category: EXTENSION, FUNCTION, TABLE, SEQUENCE, INDEX,
        CONSTRAINT, VIEW, TRIGGER, TYPE, or OTHER.
    """
    head = unit.upper()
    if "CREATE EXTENSION" in head:
        return "EXTENSION"
    if "CREATE FUNCTION" in head or "CREATE OR REPLACE FUNCTION" in head:
        return "FUNCTION"
    if "CREATE TABLE" in head:
        return "TABLE"
    if "CREATE SEQUENCE" in head or "ALTER SEQUENCE" in head:
        return "SEQUENCE"
    if "CREATE INDEX" in head or "CREATE UNIQUE INDEX" in head:
        return "INDEX"
    if "ADD CONSTRAINT" in head or "ALTER TABLE" in head:
        return "CONSTRAINT"
    if "CREATE VIEW" in head:
        return "VIEW"
    if "CREATE TRIGGER" in head or "CREATE CONSTRAINT TRIGGER" in head:
        return "TRIGGER"
    if "CREATE TYPE" in head:
        return "TYPE"
    return "OTHER"


def _normalize_catalog(sql: str) -> str:
    """Canonicalize a dump for order-insensitive comparison.

    Only harmless variability is removed: session-level ``SET``/``set_config``
    lines, dump ownership/privilege metadata, extension version pins, and
    statement ordering. Everything else (columns, indexes, constraints,
    function bodies) is preserved verbatim.

    Args:
        sql: Schema-only SQL, typically already passed through `_normalize`.

    Returns:
        Canonical comparison text: statement units sorted by object identity
        and joined by a blank line, ending with a single newline.
    """
    kept: list[str] = []
    for line in sql.splitlines():
        stripped = line.strip()
        if not stripped:
            continue
        if stripped.startswith(DROPPED_PREFIXES):
            continue
        if stripped.startswith(DROPPED_COMMENT_PREFIXES):
            continue
        if stripped.startswith("SET "):
            continue
        if stripped.startswith("SELECT pg_catalog.set_config('search_path'"):
            continue
        if stripped in DROPPED_SETTINGS or stripped in DROPPED_STATEMENTS:
            continue
        if stripped.startswith("GRANT ") or stripped.startswith("REVOKE "):
            continue
        line = re.sub(r"Owner:\s*\S+", "Owner: -", line)
        line = _canonicalize_array_memberships(line)
        extension = _EXTENSION_RE.search(line)
        if extension is not None and "CREATE EXTENSION" in line.upper():
            schema = extension.group(2) or "public"
            line = (
                f"CREATE EXTENSION IF NOT EXISTS {extension.group(1)} "
                f"WITH SCHEMA {schema};"
            )
        kept.append(line.rstrip())
    units = _split_statements("\n".join(kept))
    cleaned: list[str] = []
    for unit in units:
        text = unit.strip()
        if not text:
            continue
        if all(
            not part.strip() or part.strip().startswith("--")
            for part in text.splitlines()
        ):
            # Header-free comment blocks (e.g. the dump-complete trailer)
            # carry no schema identity and only add noise.
            continue
        cleaned.append(text)
    cleaned.sort(key=lambda unit: (_statement_key(unit), unit))
    return "\n\n".join(cleaned).rstrip("\n") + "\n"


def _extension_name(unit: str) -> str | None:
    """Return the extension name for an EXTENSION unit, else None."""
    match = _EXTENSION_RE.search(unit)
    return match.group(1).lower() if match is not None else None


def _compare_normalized_schemas(
    fixture_sql: str,
    live_sql: str,
    allowlist: frozenset[str] = PROD_ONLY_EXTENSION_ALLOWLIST,
) -> dict[str, list[str]]:
    """Compare canonical fixture SQL against live SQL unit by unit.

    Args:
        fixture_sql: Canonical fixture dump text.
        live_sql: Live database dump text.
        allowlist: Extension names present only in production that are
            deliberately excluded from the comparison.

    Returns:
        A dict with sorted ``added`` (live-only), ``removed``
        (fixture-only), and ``changed`` object keys, each carrying its
        category as ``"<CATEGORY> <key>"``.
    """
    def index_units(sql: str) -> dict[str, str]:
        grouped: dict[str, list[str]] = {}
        for raw_unit in _split_statements(_normalize_catalog(sql)):
            unit = raw_unit.strip()
            key = _statement_key(unit)
            if _categorize(unit) == "EXTENSION":
                name = _extension_name(unit)
                if name is not None and name in allowlist:
                    continue
            grouped.setdefault(key, []).append(unit)
        expanded: dict[str, str] = {}
        for key in sorted(grouped):
            for position, unit in enumerate(sorted(grouped[key])):
                expanded[f"{key}#{position}"] = unit
        return expanded

    fixture_units = index_units(fixture_sql)
    live_units = index_units(live_sql)

    def label(key: str, unit: str) -> str:
        base = key.split("#", 1)[0]
        return f"{_categorize(unit)} {base}"

    added = [
        label(key, live_units[key]) for key in sorted(live_units) if key not in fixture_units
    ]
    removed = [
        label(key, fixture_units[key])
        for key in sorted(fixture_units)
        if key not in live_units
    ]
    changed = [
        label(key, live_units[key])
        for key in sorted(live_units)
        if key in fixture_units and live_units[key] != fixture_units[key]
    ]
    return {"added": added, "removed": removed, "changed": changed}


def _redact(text: str, secrets: list[str]) -> str:
    """Replace every occurrence of a secret with a safe placeholder.

    Args:
        text: Diagnostic text that must not leak credentials.
        secrets: Raw secrets (passwords, full DSNs) to remove.

    Returns:
        The same text with each non-empty secret replaced by ``<redacted>``.
    """
    redacted = text
    for secret in sorted((item for item in secrets if item), key=len, reverse=True):
        redacted = redacted.replace(secret, "<redacted>")
    return redacted


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
