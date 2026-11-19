"""Closure-gate contract for the continuity-rules same-path Rust cutover (#4848).

The five browser-called ``/api/v1/continuity-rules`` operations must be served
by the native Rust binary at the same method/path pairs, with the Python
handlers retired and the wire contracts unchanged. These tests are stdlib-only
so they run without the project virtualenv; CI runs them under pytest.
"""

from __future__ import annotations

import ast
import json
from pathlib import Path
from typing import Final

REPO_ROOT: Final = Path(__file__).resolve().parents[1]

COLLECTION: Final = "/api/v1/continuity-rules/"
ITEM: Final = "/api/v1/continuity-rules/{rule_id}"
NATIVE_INGRESS: Final = "/api/native_roll.rs"

EXPECTED_OPERATIONS: Final = {
    (COLLECTION, "GET"): "continuity_rules_list",
    (COLLECTION, "POST"): "continuity_rules_create",
    (ITEM, "GET"): "continuity_rules_get",
    (ITEM, "PUT"): "continuity_rules_update",
    (ITEM, "DELETE"): "continuity_rules_delete",
}


def _vercel_routes() -> list[dict]:
    return json.loads((REPO_ROOT / "vercel.json").read_text())["routes"]


def _fragment() -> dict:
    return json.loads(
        (REPO_ROOT / "docs" / "api" / "route-fragments" / "continuity-rules.json").read_text()
    )


def test_vercel_rewrites_send_every_operation_to_the_native_binary_first() -> None:
    """Both method/path groups rewrite to native_roll.rs ahead of the catch-all."""
    routes = _vercel_routes()
    catch_all = next(
        index
        for index, route in enumerate(routes)
        if route.get("src") == "/api(?:/.*)?"
    )
    expected = {
        ("^/api/v1/continuity\\-rules/$", frozenset({"GET", "POST"})),
        ("^/api/v1/continuity\\-rules/[^/]+$", frozenset({"GET", "PUT", "DELETE"})),
    }
    found = {
        (route["src"], frozenset(route["methods"]))
        for route in routes[:catch_all]
        if "continuity\\-rules" in route.get("src", "")
    }
    assert found == expected
    for route in routes[:catch_all]:
        if "continuity\\-rules" in route.get("src", ""):
            assert route["dest"] == NATIVE_INGRESS


def test_route_fragment_declares_native_rust_target_owned_by_4848() -> None:
    fragment = _fragment()
    assert fragment["family"] == "continuity-rules"
    assert fragment["defaults"]["runtime"] == "native-rust"
    assert fragment["defaults"]["status"] == "target"
    assert fragment["defaults"]["owning_issue"] == 4848
    operations = {(op["method"], op["path"]) for op in fragment["operations"]}
    assert operations == {(method, path) for path, method in EXPECTED_OPERATIONS}
    for op in fragment["operations"]:
        assert op["dest"] == NATIVE_INGRESS
        assert op.get("runtime", fragment["defaults"]["runtime"]) == "native-rust"
        assert op["exclude_from_inventory"] is True


def test_native_contracts_declare_all_five_operations_with_bearer_security() -> None:
    for contract in (
        REPO_ROOT / "native" / "contracts" / "v2-runtime.openapi.json",
        REPO_ROOT / "native" / "contracts" / "same-path-runtime.openapi.json",
    ):
        document = json.loads(contract.read_text())
        for (path, method), operation_id in EXPECTED_OPERATIONS.items():
            operation = document["paths"][path][method.lower()]
            assert operation["operationId"] == operation_id, contract.name
            assert operation["security"] == [{"HTTPBearer": []}], contract.name


def test_rust_router_and_vercel_entry_register_the_same_paths() -> None:
    lib_rs = (REPO_ROOT / "native" / "roll-service" / "src" / "lib.rs").read_text()
    router_body = lib_rs.split("pub fn router(", 1)[1]
    assert '"/api/v1/continuity-rules/"' in router_body
    assert '"/api/v1/continuity-rules/{rule_id}"' in router_body
    assert "continuity_rules::list" in router_body
    assert "continuity_rules::create" in router_body
    assert "continuity_rules::get" in router_body
    assert "continuity_rules::update" in router_body
    assert "continuity_rules::delete" in router_body

    entry = (REPO_ROOT / "api" / "native_roll.rs").read_text()
    assert '.route("/api/v1/continuity-rules/", get(native_dispatch))' in entry
    assert '.route("/api/v1/continuity-rules/", post(native_dispatch))' in entry
    assert '.route("/api/v1/continuity-rules/{rule_id}", get(native_dispatch))' in entry
    assert '.route("/api/v1/continuity-rules/{rule_id}", put(native_dispatch))' in entry
    assert 'delete(native_dispatch)' in entry


def test_retirement_fixture_pins_all_five_python_operations() -> None:
    fixture = json.loads(
        (REPO_ROOT / "tests" / "fixtures" / "retired-python-handlers.json").read_text()
    )
    retired = {
        (method, operation["path"])
        for operation in fixture
        if operation["module"] == "app.api.continuity_rule"
        for method in operation["methods"]
    }
    assert retired == {(method, path) for path, method in EXPECTED_OPERATIONS}


def test_python_handler_and_exclusive_helpers_are_gone() -> None:
    assert not (REPO_ROOT / "app" / "api" / "continuity_rule.py").exists()
    dependency_router = (REPO_ROOT / "app" / "api" / "dependency.py").read_text()
    assert "continuity_rule" not in dependency_router
    module = ast.parse((REPO_ROOT / "app" / "continuity_rules.py").read_text())
    functions = {
        node.name
        for node in ast.walk(module)
        if isinstance(node, (ast.AsyncFunctionDef, ast.FunctionDef))
    }
    # Shared helpers used by the continuity-plan writer must survive; the
    # CRUD-handler-exclusive reference checker must not.
    assert "ensure_owned_continuity_node" in functions
    assert "_would_create_cycle" in functions
    assert "ensure_owned_continuity_rule_references" not in functions


def test_generated_frontend_client_keeps_the_unchanged_v1_paths() -> None:
    native_client = (REPO_ROOT / "frontend" / "src" / "generated" / "nativeV2Client.ts").read_text()
    assert '"/v1/continuity-rules/"' in native_client
    assert "/v1/continuity-rules/${encodeURIComponent(String(args.path.rule_id))}" in native_client
    openapi_client = (REPO_ROOT / "frontend" / "src" / "generated" / "openapi.ts").read_text()
    assert '"/api/v1/continuity-rules/"' in openapi_client
    assert '"/api/v1/continuity-rules/{rule_id}"' in openapi_client


def test_native_route_db_test_guard_covers_continuity_rules() -> None:
    """The module has a DB-backed HTTP test and is no longer a guard gap."""
    test_file = REPO_ROOT / "native" / "roll-service" / "tests" / "continuity_rules_v1_http.rs"
    assert test_file.exists()
    source = test_file.read_text()
    assert "test_support::test_state" in source
    assert "test_support::reset_for_test" in source
    assert '"/api/v1/continuity-rules/"' in source
    assert "/api/v1/continuity-rules/{rule_id}" in source

    guard = (REPO_ROOT / "scripts" / "check_native_route_db_tests.mjs").read_text()
    allowlist = guard.split("export const ALLOWLIST", 1)[1].split("]);", 1)[0]
    assert "'continuity_rules'" not in allowlist
