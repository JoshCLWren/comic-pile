"""Closure-critical validation for continuity-rules Rust cutover (issue #4848).

All five browser-called continuity-rules operations now route to native Rust.
Python handlers retired in #5162, remnant cleanup in #5443.

This test pins the verified state and ensures the cutover contract stays true.
"""

import json
from pathlib import Path

from app.main import app


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


def test_python_does_not_exclude_continuity_rules_routes() -> None:
    """Python should not have continuity-rules routes (they're served by Rust via catch-all)."""
    paths = app.openapi()["paths"]
    for method, path_list in CONTINUITY_RULES_PATHS.items():
        for path in path_list:
            assert method.lower() not in paths.get(path, {}), (
                f"Python should not expose {method.upper()} {path}"
            )


def test_continuity_rules_route_to_native_rust() -> None:
    """All continuity-rules operations route to native Rust via catch-all."""
    config = json.loads((Path(__file__).resolve().parents[1] / "vercel.json").read_text())
    routes = config["routes"]

    # The catch-all route sends all /api paths to native_roll.rs
    # This covers all continuity-rules paths
    catch_all = [r for r in routes if r.get("src") == "/api(?:/.*)?"]
    assert catch_all == [
        {
            "src": "/api(?:/.*)?",
            "dest": "/api/native_roll.rs",
        }
    ], "Continuity-rules routes are served via catch-all to native Rust"


def test_continuity_rules_registered_in_native_rust() -> None:
    """Continuity-rules handlers are registered in the Rust lib.rs router."""
    native_lib = (Path(__file__).resolve().parents[1] / "native/roll-service/src/lib.rs").read_text()

    # Check that continuity_rules module is imported
    assert "pub mod continuity_rules;" in native_lib, "continuity_rules module should be declared"

    # Check routes are registered
    assert '"/api/v1/continuity-rules/"' in native_lib, "list/create routes should be registered"
    assert '"/api/v1/continuity-rules/{rule_id}"' in native_lib, "get/update/delete routes should be registered"


def test_continuity_rules_v2_inventory_status() -> None:
    """Continuity-rules operations are marked as native-rust in v2-route-inventory.json."""
    inventory = json.loads(
        (Path(__file__).resolve().parents[1] / "docs/api/v2-route-inventory.json").read_text()
    )

    for op in inventory["operations"]:
        if op.get("path", "").startswith("/api/v1/continuity-rules"):
            assert op.get("runtime") == "native-rust", (
                f"{op['method']} {op['path']} should be native-rust"
            )
            assert op.get("status") == "target", (
                f"{op['method']} {op['path']} should be target status"
            )
            assert op.get("owning_issue") == 4848, (
                f"{op['method']} {op['path']} should be owned by issue #4848"
            )


def test_continuity_rules_not_in_retired_python_handlers() -> None:
    """Continuity-rules handlers should not be in the retired Python handlers fixture."""
    retired = json.loads(
        (Path(__file__).resolve().parents[1] / "tests/fixtures/retired-python-handlers.json").read_text()
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
    assert "ContinuityRules" in native_client or "continuity-rules" in native_client, (
        "Native v2 client should include continuity-rules endpoints"
    )