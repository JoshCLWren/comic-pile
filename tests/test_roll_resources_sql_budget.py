"""SQL budget guard for the Roll resource reads (#4737).

The 2026-11-07 #4335 update requires a reviewed ``sql_budget`` beside each
DB-backed Rust operation in ``docs/api/v2-route-inventory.json``. This test
pins both Roll resource reads against the Rust call sites in
``native/roll-service/src/roll_resources.rs``: each read folds authentication
into its own single owner-scoped statement (die-state: auth + die + last roll;
eligible: auth + Option E snapshot + die + pending offer), so the request keeps
one issued SQL statement including authentication. All statements are set-based
and independent of library size; no per-row N+1.
"""

from __future__ import annotations

import json
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
INVENTORY = ROOT / "docs" / "api" / "v2-route-inventory.json"
ROLL_RESOURCES = ROOT / "native" / "roll-service" / "src" / "roll_resources.rs"

QUERY_CALL = re.compile(r"\.(query|query_opt|query_one|query_one_optional)\(")


def _entry(path: str) -> dict[str, object]:
    """Return the inventory entry for one Roll resource operation."""
    document = json.loads(INVENTORY.read_text(encoding="utf-8"))
    operations = document["operations"]
    assert isinstance(operations, list)
    for operation in operations:
        if not isinstance(operation, dict):
            raise AssertionError("inventory operations must be objects")
        if operation.get("method") == "GET" and operation.get("path") == path:
            return operation
    raise AssertionError(f"{path} missing from v2 route inventory")


def _function_body(source: str, name: str, end_marker: str) -> str:
    """Return the body of one named Rust function."""
    start = source.index(f"async fn {name}(")
    end = source.index(end_marker, start)
    return source[start:end]


def test_roll_die_state_sql_budget_matches_handler_call_sites() -> None:
    """The declared budget equals the statically pinned Rust call sites."""
    entry = _entry("/api/v2/roll/die-state")
    budget = entry.get("sql_budget")
    assert isinstance(budget, dict), "die-state entry must declare a sql_budget"

    source = ROLL_RESOURCES.read_text(encoding="utf-8")
    load_die = _function_body(source, "load_die_payload", "async fn load_eligible_payload")

    # One handler-issued statement, including the folded auth lookup.
    assert "DIE_STATEMENTS_ISSUED.fetch_add(1, Ordering::Relaxed)" in load_die
    assert load_die.count("db::query_one_optional(") == 1
    assert "die_statement()" in load_die

    # The statement folds auth, die and last roll into one round trip.
    assert "FOLDED_AUTH_CTES" in source
    assert "LATEST_DIE_CTE" in source
    assert "LAST_ROLL_CTE" in source

    assert budget.get("application_statements") == 1
    assert budget.get("transaction_control_statements") == 0
    assert budget.get("total_statements") == 1


def test_roll_eligible_issue_ids_sql_budget_matches_handler_call_sites() -> None:
    """The declared budget equals the statically pinned Rust call sites."""
    entry = _entry("/api/v2/roll/eligible-issue-ids")
    budget = entry.get("sql_budget")
    assert isinstance(budget, dict), "eligible entry must declare a sql_budget"

    source = ROLL_RESOURCES.read_text(encoding="utf-8")
    load_eligible = _function_body(
        source, "load_eligible_payload", "fn parse_snoozed"
    )

    # One handler-issued statement, including the folded auth lookup.
    assert "ELIGIBLE_STATEMENTS_ISSUED.fetch_add(1, Ordering::Relaxed)" in load_eligible
    assert load_eligible.count("db::query_one_optional(") == 1
    assert "eligible_statement()" in load_eligible

    # The statement folds auth, the Option E snapshot, die and pending offer.
    assert "SNAPSHOT_CTES" in source
    assert "pending_offer_cte" in source

    assert budget.get("application_statements") == 1
    assert budget.get("transaction_control_statements") == 0
    assert budget.get("total_statements") == 1


def test_roll_resources_have_no_query_inside_a_loop() -> None:
    """Neither read issues per-row (N+1) statements."""
    source = ROLL_RESOURCES.read_text(encoding="utf-8")
    load_die = source.split("async fn load_die_payload(", 1)[1].split(
        "async fn load_eligible_payload(", 1
    )[0]
    load_eligible = source.split("async fn load_eligible_payload(", 1)[1].split(
        "fn parse_snoozed(", 1
    )[0]
    assert not re.search(r"(?m)^\s*(for|while)\s", load_die)
    assert not re.search(r"(?m)^\s*(for|while)\s", load_eligible)
