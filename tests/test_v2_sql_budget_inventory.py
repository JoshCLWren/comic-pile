"""Shared SQL budget inventory guard for native v2 operations (#4347).

The 2026-11-07 #4335 update requires a reviewed ``sql_budget`` beside each
DB-backed Rust operation in ``docs/api/v2-route-inventory.json``, counted
from live call sites. Per-route tests pin each budget against its handler;
this guard keeps the inventory side honest:

* every budgeted entry is an operation present in the generated native
  OpenAPI contract with consistent arithmetic;
* the budgeted set is recorded exactly, so adding a budget requires a
  deliberate test update alongside its per-route pin;
* native operations without a budget are recorded exactly as gaps, so a
  new native operation cannot land without either a budget or an explicit
  entry here. Some gaps may be non-DB operations (e.g. CSRF) that need an
  explicit exemption rather than a budget in a follow-up slice.
"""

from __future__ import annotations

import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
INVENTORY = ROOT / "docs" / "api" / "v2-route-inventory.json"
SOURCES = ROOT / "docs" / "api" / "sql-budget-sources.json"
OPENAPI = ROOT / "native" / "contracts" / "v2-runtime.openapi.json"

_BUDGETED_OPERATIONS = frozenset(
    {
        ("delete", "/api/v2/dependencies/{dependency_id}"),
        ("delete", "/api/v2/issues/{issue_id}"),
        ("delete", "/api/v2/reading-lists/{list_id}"),
        ("get", "/api/v2/analytics/metrics"),
        ("get", "/api/v2/auth/csrf"),
        ("get", "/api/v2/auth/me"),
        ("get", "/api/v2/continuity-plans/{plan_id}/reader"),
        ("get", "/api/v2/continuity-plans/{plan_id}/recovery"),
        ("get", "/api/v2/demo-roll"),
        ("get", "/api/v2/issues/{issue_id}/comicvine"),
        ("get", "/api/v2/queue-entries/{thread_id}"),
        ("get", "/api/v2/reading-graph"),
        ("get", "/api/v2/reading-lists"),
        ("get", "/api/v2/reading-lists/{list_id}"),
        ("get", "/api/v2/reading-lists/{list_id}/reader"),
        ("get", "/api/v2/roll/bootstrap"),
        ("get", "/api/v2/roll/die-state"),
        ("get", "/api/v2/roll/eligible-issue-ids"),
        ("get", "/api/v2/threads"),
        ("patch", "/api/v2/issues/{issue_id}"),
        ("patch", "/api/v2/queue-entries/{thread_id}"),
        ("post", "/api/v2/auth/forgot-password"),
        ("post", "/api/v2/auth/login"),
        ("post", "/api/v2/auth/logout"),
        ("post", "/api/v2/auth/refresh"),
        ("post", "/api/v2/auth/register"),
        ("post", "/api/v2/auth/reset-password"),
        ("post", "/api/v2/continuity-plans/{plan_id}/recovery"),
        ("post", "/api/v2/dependencies/"),
        ("post", "/api/v2/issues/cards"),
        ("post", "/api/v2/queue-orders"),
        ("post", "/api/v2/reading-boundaries"),
        ("post", "/api/v2/reading-graph/repairs"),
        ("post", "/api/v2/reading-lists"),
        ("post", "/api/v2/reading-sessions"),
        ("post", "/api/v2/roll/dice-command"),
        ("post", "/api/v2/roll/offer"),
        ("post", "/api/v2/roll/reset"),
        ("post", "/api/v2/threads/{thread_id}/issues"),
        ("put", "/api/v2/reading-lists/{list_id}"),
        ("put", "/api/v2/threads/{thread_id}/issue-order"),
    }
)

# Native operations without a recorded sql_budget. Shrink this set as each
# operation gains a budget (or records a non-DB exemption); never grow it
# silently — a new native operation must arrive with its budget.
_KNOWN_BUDGET_GAPS = frozenset()

def _inventory_operations() -> list[dict[str, object]]:
    """Load and validate the inventory operations."""
    document = json.loads(INVENTORY.read_text(encoding="utf-8"))
    operations = document["operations"]
    assert isinstance(operations, list)
    entries: list[dict[str, object]] = []
    for operation in operations:
        assert isinstance(operation, dict)
        entries.append(operation)
    return entries


def _deployed_operations() -> set[tuple[str, str]]:
    """Read native operations from generated OpenAPI, without count snapshots."""
    document = json.loads(OPENAPI.read_text(encoding="utf-8"))
    paths = document.get("paths")
    assert isinstance(paths, dict) and paths, "native OpenAPI must declare paths"
    return {
        (method.lower(), path)
        for path, operations in paths.items()
        if path.startswith("/api/v2/")
        for method in operations
    }


def _key(operation: dict[str, object]) -> tuple[str, str]:
    """Return the lowercase ``(method, path)`` pair for one entry."""
    method = operation.get("method")
    path = operation.get("path")
    assert isinstance(method, str) and isinstance(path, str)
    return (method.lower(), path)


def _budget(operation: dict[str, object]) -> dict[str, object]:
    """Return the validated ``sql_budget`` for one entry."""
    budget = operation.get("sql_budget")
    assert isinstance(budget, dict), "budgeted entry must declare a sql_budget"
    application = budget.get("application_statements")
    control = budget.get("transaction_control_statements")
    total = budget.get("total_statements")
    maximum = budget.get("max_statements")
    overhead = budget.get("runtime_overhead_statements", 0)
    basis = budget.get("basis")
    grows = budget.get("grows_with_data")
    assert isinstance(application, int) and application >= 0
    assert isinstance(control, int) and control >= 0
    assert isinstance(total, int)
    assert total == application + control
    assert isinstance(overhead, int) and overhead >= 0
    assert maximum == total + overhead
    assert isinstance(grows, bool)
    if total == 0:
        assert operation.get("db_free") is True
    assert isinstance(basis, str) and basis.strip() != ""
    return budget


def test_budget_source_matches_generated_inventory() -> None:
    """Editable SQL budget sources must survive route generation unchanged."""
    source_document = json.loads(SOURCES.read_text(encoding="utf-8"))
    source_operations = source_document.get("operations")
    assert isinstance(source_operations, list)
    sources = {
        (entry["method"].lower(), entry["path"]): entry
        for entry in source_operations
    }
    assert len(sources) == len(source_operations), "duplicate SQL budget source"
    inventory = {
        _key(operation): operation
        for operation in _inventory_operations()
    }
    for key, source in sources.items():
        assert key in inventory, f"stale SQL budget source {key}"
        assert inventory[key].get("sql_budget") == source["sql_budget"]


def test_every_budget_is_a_deployed_native_operation() -> None:
    """Budgeted entries are native-rust and present in the generated contract."""
    operations = _inventory_operations()
    deployed = _deployed_operations()
    budgeted = [op for op in operations if "sql_budget" in op]
    assert budgeted, "at least one operation must carry a sql_budget"
    for operation in budgeted:
        assert operation.get("runtime") == "native-rust"
        assert _key(operation) in deployed, (
            f"budgeted {_key(operation)} is absent from native OpenAPI"
        )
        _budget(operation)


def test_budgeted_operations_are_the_recorded_set() -> None:
    """The budgeted set is exactly the recorded one; update deliberately."""
    operations = _inventory_operations()
    budgeted = {_key(op) for op in operations if "sql_budget" in op}
    assert budgeted == _BUDGETED_OPERATIONS, (
        f"budgeted set changed: recorded {sorted(_BUDGETED_OPERATIONS)}, "
        f"found {sorted(budgeted)}"
    )


def test_unbudgeted_native_operations_are_recorded_gaps() -> None:
    """Pinned gaps: a new native operation must arrive with its budget."""
    operations = _inventory_operations()
    native = [op for op in operations if op.get("runtime") == "native-rust"]
    gaps = {_key(op) for op in native if "sql_budget" not in op}
    budgeted = {_key(op) for op in native if "sql_budget" in op}
    assert budgeted.isdisjoint(gaps)
    assert budgeted | gaps == {_key(op) for op in native}
    assert gaps == _KNOWN_BUDGET_GAPS, (
        f"budget gaps changed: recorded {sorted(_KNOWN_BUDGET_GAPS)}, "
        f"found {sorted(gaps)}"
    )
