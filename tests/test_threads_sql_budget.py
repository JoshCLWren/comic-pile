"""SQL budget guard for ``GET /api/v2/threads`` (#4347).

The 2026-11-07 #4335 update requires a reviewed ``sql_budget`` beside each
DB-backed Rust operation in ``docs/api/v2-route-inventory.json``. This test
records the budget for the threads collection read as a static call-site pin:
it counts the page statement in ``threads.rs`` and checks the inventory
budget matches. The Option E preview path (auth helper + snapshot helper)
is presence-checked, not counted in the production-default budget; activating
the preview requires a manual inventory update backed by a measured budget.
All statements are set-based and independent of library size.
"""

from __future__ import annotations

import json
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
INVENTORY = ROOT / "docs" / "api" / "v2-route-inventory.json"
THREADS = ROOT / "native" / "roll-service" / "src" / "threads.rs"
OPTION_INPUTS = ROOT / "native" / "roll-service" / "src" / "option_inputs.rs"
AUTH_IDENTITY = ROOT / "native" / "roll-service" / "src" / "auth" / "identity.rs"

# The page statement is issued via ``db::query_one_optional``, not a
# ``.query(`` method call, so the pin counts both method and helper forms.
QUERY_CALL = re.compile(r"(?:\.|::)(query|query_opt|query_one|query_one_optional)\(")


def _count_queries(source: str) -> int:
    """Return the number of DB query call sites in one Rust source file."""
    return len(QUERY_CALL.findall(source))


def _threads_entry() -> dict[str, object]:
    """Return the inventory entry for the threads operation."""
    document = json.loads(INVENTORY.read_text(encoding="utf-8"))
    operations = document["operations"]
    assert isinstance(operations, list)
    for operation in operations:
        if not isinstance(operation, dict):
            raise AssertionError("inventory operations must be objects")
        if (
            operation.get("method") == "GET"
            and operation.get("path") == "/api/v2/threads"
        ):
            return operation
    raise AssertionError("threads missing from v2 route inventory")


def test_threads_sql_budget_matches_handler_call_path() -> None:
    """The declared budget equals the statically pinned Rust call sites."""
    entry = _threads_entry()
    budget = entry.get("sql_budget")
    assert isinstance(budget, dict), "threads entry must declare a sql_budget"

    threads = THREADS.read_text(encoding="utf-8")
    option_inputs = OPTION_INPUTS.read_text(encoding="utf-8")
    auth_identity = AUTH_IDENTITY.read_text(encoding="utf-8")

    # Default legacy path: one page statement issues auth, whole-queue
    # total, list names and rows together via one helper call.
    page_statements = _count_queries(threads)
    assert page_statements == 1
    assert "query_one_optional(state, connection, &sql" in threads
    # The default path is the production default: the Option E preview
    # requires explicit env opt-in and is off unless both flags are set.
    assert "fn option_e_enabled()" in threads
    assert "unwrap_or(false)" in threads
    # Preview-path helpers are presence-checked, not counted in this budget.
    assert "query_one_optional" in auth_identity
    assert "load_option_inputs_contained" in threads
    assert "query_count = 1" in option_inputs

    expected = page_statements
    assert budget.get("application_statements") == expected
    assert expected == 1
    assert budget.get("transaction_control_statements") == 0
    assert budget.get("total_statements") == expected
    assert budget.get("basis") == (
        "default legacy path: one page statement including auth, total, lists "
        "and rows; option_e preview adds auth 1 + one-statement Option E "
        "snapshot 1 (+2 tx control) when activated; set-based, independent "
        "of library size, no per-row N+1"
    )


def test_threads_has_no_query_inside_a_loop() -> None:
    """The threads projection must not issue per-row (N+1) statements."""
    source = THREADS.read_text(encoding="utf-8")
    handler = source.split("pub async fn list_threads(", 1)[1].split(
        "fn validate_auth(", 1
    )[0]
    # Rows are mapped onto PageRow values after the single page statement;
    # the in-memory projection must not query.
    projection = handler.find("rows")
    assert projection != -1
    assert ".query" not in handler[projection:]
    assert "::query" not in handler[projection:]
