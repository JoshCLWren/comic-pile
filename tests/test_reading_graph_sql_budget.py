"""SQL budget guard for ``GET /api/v2/reading-graph`` (#4347).

The 2026-11-07 #4335 update requires a reviewed ``sql_budget`` beside each
DB-backed Rust operation in ``docs/api/v2-route-inventory.json``. This test
records the budget for the reading-graph read as a static call-site pin: the
handler issues no direct queries, loading one Option E snapshot via
``load_option_diagnostics`` behind the authenticated-user extractor. A new
helper-internal query will not fail this test automatically; it requires a
manual inventory update backed by a measured budget. All statements are
set-based and independent of library size.
"""

from __future__ import annotations

import json
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
INVENTORY = ROOT / "docs" / "api" / "v2-route-inventory.json"
READING_GRAPH = ROOT / "native" / "roll-service" / "src" / "reading_graph.rs"
OPTION_INPUTS = ROOT / "native" / "roll-service" / "src" / "option_inputs.rs"
AUTH_IDENTITY = ROOT / "native" / "roll-service" / "src" / "auth" / "identity.rs"

QUERY_CALL = re.compile(r"\.(query|query_opt|query_one|query_one_optional)\(")


def _count_queries(source: str) -> int:
    """Return the number of DB query call sites in one Rust source file."""
    return len(QUERY_CALL.findall(source))


def _graph_entry() -> dict[str, object]:
    """Return the inventory entry for the reading-graph operation."""
    document = json.loads(INVENTORY.read_text(encoding="utf-8"))
    operations = document["operations"]
    assert isinstance(operations, list)
    for operation in operations:
        if not isinstance(operation, dict):
            raise AssertionError("inventory operations must be objects")
        if (
            operation.get("method") == "GET"
            and operation.get("path") == "/api/v2/reading-graph"
        ):
            return operation
    raise AssertionError("reading-graph missing from v2 route inventory")


def test_reading_graph_sql_budget_matches_handler_call_path() -> None:
    """The declared budget equals the statically pinned Rust call sites."""
    entry = _graph_entry()
    budget = entry.get("sql_budget")
    assert isinstance(budget, dict), "reading-graph entry must declare a sql_budget"

    reading_graph = READING_GRAPH.read_text(encoding="utf-8")
    option_inputs = OPTION_INPUTS.read_text(encoding="utf-8")
    auth_identity = AUTH_IDENTITY.read_text(encoding="utf-8")

    # Auth extractor: one owner/revocation/epoch lookup via one helper call.
    assert "query_one_optional" in auth_identity
    auth_statements = 1
    # The graph handler issues no direct queries; it loads one snapshot.
    handler = reading_graph.split("pub async fn reading_graph(", 1)[1].split(
        "fn remove_from_inputs(", 1
    )[0]
    assert _count_queries(handler) == 0
    assert "load_option_diagnostics(&state, user)" in handler
    assert "query_count = 1" in option_inputs
    snapshot_statements = 1

    expected = auth_statements + snapshot_statements
    assert budget.get("application_statements") == expected
    assert expected == 2
    # The snapshot runs inside a read-only transaction (BEGIN + ROLLBACK).
    assert budget.get("transaction_control_statements") == 2
    assert budget.get("total_statements") == expected + 2
    assert budget.get("basis") == (
        "auth 1 + one-statement Option E snapshot 1 (+2 tx control); "
        "set-based, independent of library size, no per-row N+1"
    )


def test_reading_graph_has_no_query_inside_a_loop() -> None:
    """The graph projection must not issue per-row (N+1) statements."""
    source = READING_GRAPH.read_text(encoding="utf-8")
    # The projection is a pure in-memory function over the loaded snapshot.
    project = source.split("fn project(", 1)[1].split("fn invalid_response(", 1)[0]
    assert ".query" not in project
    assert "::query" not in project
