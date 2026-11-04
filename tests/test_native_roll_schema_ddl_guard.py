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
starts issuing persistent schema DDL again.
"""

from __future__ import annotations

import re
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
RUST_SRC = REPO_ROOT / "native" / "roll-service" / "src"

#: The only module permitted to reference schema DDL, because it applies the
#: generated Alembic fixture rather than defining tables by hand.
SCHEMA_OWNER = RUST_SRC / "test_support.rs"

#: Persistent schema DDL.
#:
#: Matching is case-insensitive and whitespace-tolerant, including across line
#: breaks, because ``CREATE  TABLE`` and ``CREATE\nTABLE`` are exactly as good at
#: reintroducing a hand-written schema as the single-space spelling.
#:
#: ``CREATE TEMP TABLE`` and ``CREATE TEMP VIEW`` are deliberately not matched:
#: they are per-session fixtures rather than schema ownership, and several tests
#: legitimately use them.
FORBIDDEN_DDL = re.compile(
    r"\b(?:CREATE\s+(?:UNIQUE\s+)?(?:TABLE|SCHEMA|INDEX)"
    r"|ALTER\s+TABLE"
    r"|DROP\s+(?:TABLE|SCHEMA|INDEX))\b",
    re.IGNORECASE,
)


def _offenders() -> list[str]:
    """Return ``path:line: token`` for every hand-written persistent DDL."""
    offenders: list[str] = []
    for path in sorted(RUST_SRC.rglob("*.rs")):
        if path == SCHEMA_OWNER:
            continue
        text = path.read_text(encoding="utf-8")
        for match in FORBIDDEN_DDL.finditer(text):
            line = text.count("\n", 0, match.start()) + 1
            token = " ".join(match.group(0).split()).upper()
            offenders.append(f"{path.relative_to(REPO_ROOT)}:{line}: {token}")
    return offenders


def test_native_roll_service_issues_no_schema_ddl() -> None:
    """No Rust module may create, alter or drop persistent database schema."""
    offenders = _offenders()
    assert not offenders, (
        "The native Roll service must use the Alembic schema loaded by "
        "`native/roll-service/src/test_support.rs`, never hand-written DDL. "
        "Seed rows instead of defining tables. Offending lines:\n"
        + "\n".join(offenders)
    )
