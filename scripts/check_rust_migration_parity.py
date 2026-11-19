#!/usr/bin/env python3
"""Fail when the Rust migration baseline drifts from the Alembic head schema.

While Alembic and the Rust runner (``native/migrate``) coexist, a database
built by ``alembic upgrade head`` and one built by ``comicpile-migrate up`` must
be schema-identical. This dumps both with ``pg_dump --schema-only``, normalizes
them with the same rules as ``export_roll_test_schema.py``, and diffs them. The
Rust-only ``refinery_schema_history`` bookkeeping table is excluded, and the Rust
runner's pinned Alembic head must equal the repository's Alembic head.

    python scripts/check_rust_migration_parity.py \
        --alembic-url postgresql://... --rust-url postgresql://...
"""

from __future__ import annotations

import argparse
import difflib
import importlib
import re
import shutil
import subprocess
import sys
from collections.abc import Callable
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
RUNNER_LIB = REPO_ROOT / "native/migrate/src/lib.rs"


def _normalizers() -> tuple[Callable[[str], str], Callable[[str], str]]:
    """Load the dump normalizers shared with export_roll_test_schema.py."""
    sys.path.insert(0, str(REPO_ROOT / "scripts"))
    module = importlib.import_module("export_roll_test_schema")
    return module._normalize, module._normalize_catalog


def _dump(url: str) -> str:
    """Dump a database's schema, excluding the Rust-only bookkeeping table."""
    if shutil.which("pg_dump") is None:
        raise SystemExit("pg_dump not found in PATH; install the PostgreSQL client tools.")
    result = subprocess.run(
        [
            "pg_dump",
            "--schema-only",
            "--no-owner",
            "--no-privileges",
            "--no-comments",
            "--exclude-table=public.refinery_schema_history",
            url.replace("postgresql+asyncpg://", "postgresql://", 1),
        ],
        check=False,
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        raise SystemExit(f"pg_dump failed: {result.stderr.strip()}")
    normalize, normalize_catalog = _normalizers()
    return normalize_catalog(normalize(result.stdout))


def _pinned_head() -> str:
    """Return the Alembic head the Rust baseline claims to reproduce."""
    match = re.search(r'BASELINE_ALEMBIC_HEAD: &str = "([^"]+)"', RUNNER_LIB.read_text())
    if match is None:
        raise SystemExit(f"BASELINE_ALEMBIC_HEAD not found in {RUNNER_LIB}")
    return match.group(1)


def _alembic_head() -> str:
    """Return the repository Alembic head revision."""
    from alembic.config import Config
    from alembic.script import ScriptDirectory

    head = ScriptDirectory.from_config(Config(str(REPO_ROOT / "alembic.ini"))).get_current_head()
    if head is None:
        raise SystemExit("alembic reports no head revision")
    return head


def main() -> int:
    """Compare the two databases and report drift."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--alembic-url", required=True, help="Database built by alembic upgrade head."
    )
    parser.add_argument("--rust-url", required=True, help="Database built by comicpile-migrate up.")
    args = parser.parse_args()

    pinned, head = _pinned_head(), _alembic_head()
    if pinned != head:
        raise SystemExit(
            f"Alembic head is {head!r} but the Rust baseline is pinned to {pinned!r}. A new "
            "Alembic revision must be mirrored by a new Rust migration (and the pin updated) "
            "until Alembic is retired."
        )
    alembic_sql, rust_sql = _dump(args.alembic_url), _dump(args.rust_url)
    if alembic_sql != rust_sql:
        diff = difflib.unified_diff(
            alembic_sql.splitlines(),
            rust_sql.splitlines(),
            "alembic-head",
            "rust-migrations",
            lineterm="",
        )
        print("\n".join(diff), file=sys.stderr)
        raise SystemExit("Rust migration schema differs from the Alembic head schema.")
    print(f"Rust migrations match the Alembic head schema ({head}).")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
