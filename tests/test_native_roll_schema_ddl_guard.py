"""Guard: the native Roll service must never create its own database schema.

The Rust service is a pure cutover of the Roll API. It reads and writes rows; it
does not own schema. Tests must not hand-write tables either, because hand-rolled
fixtures only approximated production — which is how a production-only schema
difference (#4535) escaped the suite.

Every test loads the Alembic head schema fixture through
``native/roll-service/src/test_support.rs`` (a ``pg_dump --schema-only`` of a
database migrated to head). That module is the single place allowed to talk
about schema DDL, and it does so only by applying the generated fixture.

This guard fails if any other Rust source under ``native/roll-service/src``
starts issuing schema DDL again.
"""

from __future__ import annotations

from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
RUST_SRC = REPO_ROOT / "native" / "roll-service" / "src"

#: The only module permitted to reference schema DDL, because it applies the
#: generated Alembic fixture rather than defining tables by hand.
SCHEMA_OWNER = RUST_SRC / "test_support.rs"

FORBIDDEN_DDL = (
    "CREATE TABLE",
    "CREATE SCHEMA",
    "DROP SCHEMA",
    "ALTER TABLE",
    "CREATE INDEX",
    "CREATE UNIQUE INDEX",
)


def _offenders() -> list[str]:
    """Return ``path:line: token`` for every hand-written DDL in Rust sources."""
    offenders: list[str] = []
    for path in sorted(RUST_SRC.rglob("*.rs")):
        if path == SCHEMA_OWNER:
            continue
        for lineno, line in enumerate(
            path.read_text(encoding="utf-8").splitlines(), start=1
        ):
            upper = line.upper()
            for token in FORBIDDEN_DDL:
                if token in upper:
                    offenders.append(f"{path.relative_to(REPO_ROOT)}:{lineno}: {token}")
    return offenders


def test_native_roll_service_issues_no_schema_ddl() -> None:
    """No Rust module may create, alter or drop database schema."""
    offenders = _offenders()
    assert not offenders, (
        "The native Roll service must use the Alembic schema loaded by "
        "`native/roll-service/src/test_support.rs`, never hand-written DDL. "
        "Seed rows instead of defining tables. Offending lines:\n"
        + "\n".join(offenders)
    )
