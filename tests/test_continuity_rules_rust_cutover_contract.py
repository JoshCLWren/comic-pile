"""Closure-critical validation for continuity-rules Rust cutover (issue #4848).

All five browser-called continuity-rules operations now route to native Rust.
Python handlers retired in #5162, remnant cleanup in #5443.

This test pins the verified state and ensures the cutover contract stays true.
"""

import json
from pathlib import Path


# The five browser-called continuity-rules operations
CONTINUITY_RULES_PATHS = {
    "GET": [
        "/api/v1/continuity-rules/",
        "/api/v1/continuity-rules/{rule_id}",
    ],
    "POST": [
        "/api/v1/continuity-rules/",
    ],
    "PUT": [
        "/api/v1/continuity-rules/{rule_id}",
    ],
    "DELETE": [
        "/api/v1/continuity-rules/{rule_id}",
    ],
}


def test_continuity_rules_registered_in_native_rust() -> None:
    """Continuity-rules handlers are registered in the Rust lib.rs router."""
    root = Path(__file__).resolve().parents[1]
    native_lib = (root / "native/roll-service/src/lib.rs").read_text()

    # Check that continuity_rules module is imported
    assert "pub mod continuity_rules;" in native_lib, "continuity_rules module should be declared"

    # Check routes are registered
    assert '"/api/v1/continuity-rules/"' in native_lib, "list/create routes should be registered"
    assert '"/api/v1/continuity-rules/{rule_id}"' in native_lib, (
        "get/update/delete routes should be registered"
    )


def test_continuity_rules_v1_inventory_status() -> None:
    """Continuity-rules v1 operations are in full_surface.v1_operations with native-rust status."""
    root = Path(__file__).resolve().parents[1]
    inventory = json.loads((root / "docs/api/v2-route-inventory.json").read_text())

    count = 0
    for op in inventory["full_surface"]["v1_operations"]:
        if op.get("path", "").startswith("/api/v1/continuity-rules"):
            count += 1
            assert op.get("runtime") == "native-rust", (
                f"{op['method']} {op['path']} should be native-rust"
            )
            assert op.get("status") == "target", (
                f"{op['method']} {op['path']} should be target status"
            )
            assert op.get("owning_issue") == 4848, (
                f"{op['method']} {op['path']} should be owned by issue #4848"
            )

    assert count == 5, f"Expected 5 continuity-rules v1 operations in inventory, found {count}"


def test_continuity_rules_not_in_retired_python_handlers() -> None:
    """Continuity-rules handlers should not be in the retired Python handlers fixture."""
    root = Path(__file__).resolve().parents[1]
    retired = json.loads(
        (root / "tests/fixtures/retired-python-handlers.json").read_text()
    )

    for handler in retired:
        assert not handler["path"].startswith("/api/v1/continuity-rules"), (
            f"Continuity-rules {handler['path']} should not be in retired Python handlers"
        )


def test_continuity_rules_consumers_referenced() -> None:
    """Frontend clients should reference continuity-rules via the native v2 client."""
    root = Path(__file__).resolve().parents[1]
    native_client = (root / "frontend/src/generated/nativeV2Client.ts").read_text()

    # The native client should have continuity rules endpoints
    assert "continuity-rules" in native_client, (
        "Native v2 client should include continuity-rules endpoints"
    )


def test_continuity_rules_v2_runtime_openapi_contract() -> None:
    """Continuity-rules operations present in native v2 runtime OpenAPI contract."""
    root = Path(__file__).resolve().parents[1]
    runtime_contract = json.loads(
        (root / "native/contracts/same-path-runtime.openapi.json").read_text()
    )

    paths = runtime_contract.get("paths", {})
    for path in ["/api/v1/continuity-rules/", "/api/v1/continuity-rules/{rule_id}"]:
        assert path in paths, f"Path {path} should be in runtime OpenAPI contract"

        if path.endswith("/"):
            # GET and POST on collection path
            assert "get" in paths[path], f"GET {path} should be in contract"
            assert "post" in paths[path], f"POST {path} should be in contract"
        else:
            # GET, PUT, DELETE on individual resource path
            assert "get" in paths[path], f"GET {path} should be in contract"
            assert "put" in paths[path], f"PUT {path} should be in contract"
            assert "delete" in paths[path], f"DELETE {path} should be in contract"


def test_continuity_rules_python_openapi_consistent() -> None:
    """Continuity-rules should not appear in Python legacy OpenAPI (served by Rust)."""
    root = Path(__file__).resolve().parents[1]
    python_legacy = json.loads(
        (root / "native/contracts/python-legacy.openapi.json").read_text()
    )

    paths = python_legacy.get("paths", {})
    for method, path_list in CONTINUITY_RULES_PATHS.items():
        for path in path_list:
            assert method.lower() not in paths.get(path, {}), (
                f"Python should not expose {method.upper()} {path}"
            )


def test_continuity_rules_v2_client_contract_types() -> None:
    """Continuity-rules types are present in the frontend OpenAPI types."""
    root = Path(__file__).resolve().parents[1]
    openapi_types = (root / "frontend/src/generated/openapi.ts").read_text()

    # Check types are generated
    assert "ContinuityRule" in openapi_types or "ContinuityRuleResponse" in openapi_types, (
        "ContinuityRule types should be in OpenAPI types"
    )