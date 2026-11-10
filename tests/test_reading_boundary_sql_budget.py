"""SQL budget guard for ``POST /api/v2/reading-boundaries`` (#4347 G4).

The 2026-11-07 #4335 update requires a reviewed ``sql_budget`` beside each
DB-backed Rust operation in ``docs/api/v2-route-inventory.json``.

This test records the budget for the reading-boundaries batch as a static
call-site pin: it counts the boundary label query call sites in
``reading_boundary.rs`` and checks the inventory budget matches (auth/snapshot
helper statements are presence-checked, not counted). A new helper-internal
query will not fail this test automatically; it requires a manual inventory
update backed by a measured budget. All of these statements are set-based and
independent of library size.
"""

from __future__ import annotations

import json
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
INVENTORY = ROOT / "docs" / "api" / "v2-route-inventory.json"
READING_BOUNDARY = ROOT / "native" / "roll-service" / "src" / "reading_boundary.rs"
OPTION_INPUTS = ROOT / "native" / "roll-service" / "src" / "option_inputs.rs"
AUTH_IDENTITY = ROOT / "native" / "roll-service" / "src" / "auth" / "identity.rs"

QUERY_CALL = re.compile(r"\.(query|query_opt|query_one|query_one_optional)\(")


def _count_queries(source: str) -> int:
    """Return the number of DB query call sites in one Rust source file."""
    return len(QUERY_CALL.findall(source))


def _boundary_entry() -> dict[str, object]:
    """Return the inventory entry for the reading-boundaries operation."""
    document = json.loads(INVENTORY.read_text(encoding="utf-8"))
    operations = document["operations"]
    assert isinstance(operations, list)
    for operation in operations:
        if not isinstance(operation, dict):
            raise AssertionError("inventory operations must be objects")
        if (
            operation.get("method") == "POST"
            and operation.get("path") == "/api/v2/reading-boundaries"
        ):
            return operation
    raise AssertionError("reading-boundaries missing from v2 route inventory")


def test_reading_boundary_sql_budget_matches_handler_call_path() -> None:
    """The declared budget equals the statically pinned Rust call sites."""
    entry = _boundary_entry()
    budget = entry.get("sql_budget")
    assert isinstance(budget, dict), "reading-boundaries entry must declare a sql_budget"

    reading_boundary = READING_BOUNDARY.read_text(encoding="utf-8")
    option_inputs = OPTION_INPUTS.read_text(encoding="utf-8")
    auth_identity = AUTH_IDENTITY.read_text(encoding="utf-8")

    # Auth extractor: one owner/revocation/epoch lookup via one helper call.
    assert "query_one_optional" in auth_identity
    auth_statements = 1
    # Boundary label reads: threads, volume labels, issues ANY, lists,
    # active-list entries, membership entries, prerequisites.
    label_statements = _count_queries(reading_boundary)
    assert label_statements == 7
    # Option E snapshot: one statement inside a read-only transaction.
    assert "query_count = 1" in option_inputs
    snapshot_statements = 1

    expected = auth_statements + label_statements + snapshot_statements
    assert budget.get("application_statements") == expected
    assert expected == 9
    # The Option E snapshot adds BEGIN + ROLLBACK transaction control.
    assert budget.get("transaction_control_statements") == 2
    assert budget.get("total_statements") == expected + 2
    assert budget.get("basis") == (
        "auth 1 + boundary label reads 7 + one-statement Option E snapshot 1 "
        "(+2 tx control); set-based, independent of library size, no per-row N+1"
    )


def test_reading_boundary_has_no_query_inside_a_loop() -> None:
    """The boundary projection must not issue per-row (N+1) statements."""
    source = READING_BOUNDARY.read_text(encoding="utf-8")
    # The per-thread projection is a pure in-memory function over already-loaded
    # labels/snapshot; it must not query.
    projection = source.split("pub async fn project_boundary_explanation(", 1)[1].split(
        "async fn get_reading_boundary_explanations(", 1
    )[0]
    assert ".query" not in projection
    # The per-thread loop in the handler only calls the in-memory projection.
    handler = source.split("async fn get_reading_boundary_explanations(", 1)[1].split(
        "fn build_eligibility_snapshot(", 1
    )[0]
    loop = handler.find("for thread_id in thread_ids")
    assert loop != -1
    assert ".query" not in handler[loop:]
