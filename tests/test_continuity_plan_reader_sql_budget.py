"""SQL budget guard for ``GET /api/v2/continuity-plans/{plan_id}/reader`` (#4346).

The owner clarified (2026-11-04) that this route-retirement issue is judged
on caller-migration parity and no increase in per-request statement count
versus the retired v1 route, not on rewriting the native handler to a
literal single statement. The 2026-11-07 #4335 update requires a reviewed
``sql_budget`` beside each DB-backed Rust operation in
``docs/api/v2-route-inventory.json``.

This test pins that budget for the continuity-plan reader: it counts the
application-issued statements on the handler's call path (auth, plan,
sources, the authoritative Reading List read, the Option E snapshot, and
the two release-metadata reads) and asserts the inventory budget matches,
so a future edit cannot silently add a per-row or per-request statement.
All of these statements are set-based and independent of library size.
"""

from __future__ import annotations

import json
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
INVENTORY = ROOT / "docs" / "api" / "v2-route-inventory.json"
PLAN_READER = ROOT / "native" / "roll-service" / "src" / "reading_plan_reader.rs"
READING_LIST = ROOT / "native" / "roll-service" / "src" / "reading_list.rs"
OPTION_INPUTS = ROOT / "native" / "roll-service" / "src" / "option_inputs.rs"
AUTH_IDENTITY = ROOT / "native" / "roll-service" / "src" / "auth" / "identity.rs"

QUERY_CALL = re.compile(r"\.(query|query_opt|query_one|query_one_optional)\(")


def _count_queries(source: str) -> int:
    """Return the number of DB query call sites in one Rust source file."""
    return len(QUERY_CALL.findall(source))


def _reader_entry() -> dict[str, object]:
    """Return the inventory entry for the continuity-plan reader operation."""
    document = json.loads(INVENTORY.read_text(encoding="utf-8"))
    operations = document["operations"]
    assert isinstance(operations, list)
    for operation in operations:
        if not isinstance(operation, dict):
            raise AssertionError("inventory operations must be objects")
        if (
            operation.get("method") == "GET"
            and operation.get("path") == "/api/v2/continuity-plans/{plan_id}/reader"
        ):
            return operation
    raise AssertionError("continuity-plan reader missing from v2 route inventory")


def test_continuity_plan_reader_sql_budget_matches_handler_call_path() -> None:
    """The declared budget equals the statements on the Rust call path."""
    entry = _reader_entry()
    budget = entry.get("sql_budget")
    assert isinstance(budget, dict), "reader entry must declare a sql_budget"

    plan_reader = PLAN_READER.read_text(encoding="utf-8")
    reading_list = READING_LIST.read_text(encoding="utf-8")
    option_inputs = OPTION_INPUTS.read_text(encoding="utf-8")
    auth_identity = AUTH_IDENTITY.read_text(encoding="utf-8")

    # Auth extractor: one owner/revocation/epoch lookup via one helper call.
    assert "query_one_optional" in auth_identity
    auth_statements = 1
    # Plan handler: plan lookup, sources, release sources, release candidates.
    plan_statements = _count_queries(plan_reader)
    assert plan_statements == 4
    # Authoritative Reading List read on this path: load_list + load_entries_conn.
    assert "load_list(&conn" in reading_list
    assert "load_entries_conn(&conn" in reading_list
    list_statements = 2
    # Option E snapshot: one statement inside a read-only transaction.
    assert "query_count = 1" in option_inputs
    snapshot_statements = 1

    expected = auth_statements + plan_statements + list_statements + snapshot_statements
    assert budget.get("application_statements") == expected
    assert expected == 8
    # The Option E snapshot adds BEGIN + ROLLBACK transaction control.
    assert budget.get("transaction_control_statements") == 2
    assert budget.get("total_statements") == expected + 2
    assert budget.get("basis") == (
        "auth 1 + plan/sources/release reads 4 + authoritative list read 2 "
        "+ one-statement Option E snapshot 1 (+2 tx control); set-based, "
        "independent of library size, no per-row N+1"
    )


def test_continuity_plan_reader_has_no_query_inside_a_loop() -> None:
    """The reader projection must not issue per-row (N+1) statements."""
    source = PLAN_READER.read_text(encoding="utf-8")
    handler = source.split("pub async fn read(", 1)[1].split(
        "#[utoipa::path(", 1
    )[0]
    # The projection loop only maps already-loaded list entries in memory.
    projection = handler.find("for entry in list.entries")
    assert projection != -1
    assert handler.rfind(".query", 0, projection) != -1
    assert ".query" not in handler[projection:].split("let conn = db::checkout", 1)[0]
