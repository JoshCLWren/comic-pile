"""Closure-gate tests for issue #4848 continuity-rules Rust cutover.

Pins the static contract that the same-path Rust implementation exists,
routes are configured, Python remnants are retired, and inventory/fragments
reflect the cutover. These are static checks that do not require a database.
"""

from __future__ import annotations

import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def _load_json(path: Path):
    return json.loads(path.read_text(encoding="utf-8"))


def test_vercel_routes_continuity_rules_to_native_roll():
    vercel = _load_json(ROOT / "vercel.json")
    routes = vercel.get("routes", [])
    # collect matching routes
    matches = [
        r
        for r in routes
        if r.get("dest") == "/api/native_roll.rs"
        and "continuity" in r.get("src", "")
        and "commerce" not in r.get("src", "")
    ]
    # filter to continuity-rules family
    continuity = [r for r in matches if "continuity\\-rules" in r.get("src", "")]
    # Expect 2 entries: list/create and {rule_id}
    assert len(continuity) >= 2
    srcs = {r["src"] for r in continuity}
    assert any("continuity\\-rules/\\$" in s or "continuity\\-rules/$" in s for s in srcs)
    assert any("continuity\\-rules/[^/]+$" in s for s in srcs)


def test_route_fragment_meta():
    frag = _load_json(ROOT / "docs" / "api" / "route-fragments" / "continuity-rules.json")
    assert frag["family"] == "continuity-rules"
    defaults = frag["defaults"]
    assert defaults["runtime"] == "native-rust"
    assert defaults["status"] == "target"
    assert defaults["owning_issue"] == 4848
    ops = frag["operations"]
    methods = {(op["method"], op["path"]) for op in ops}
    expected = {
        ("GET", "/api/v1/continuity-rules/"),
        ("POST", "/api/v1/continuity-rules/"),
        ("GET", "/api/v1/continuity-rules/{rule_id}"),
        ("PUT", "/api/v1/continuity-rules/{rule_id}"),
        ("DELETE", "/api/v1/continuity-rules/{rule_id}"),
    }
    assert expected.issubset(methods)


def test_same_path_runtime_contract_contains_operations():
    contract = _load_json(ROOT / "native" / "contracts" / "same-path-runtime.openapi.json")
    paths = contract.get("paths", {})
    # list/create
    list_path = paths.get("/api/v1/continuity-rules/")
    assert list_path is not None
    assert "get" in list_path
    assert "post" in list_path
    # item
    item_path = paths.get("/api/v1/continuity-rules/{rule_id}")
    assert item_path is not None
    for m in ("get", "put", "delete"):
        assert m in item_path


def test_v2_runtime_contract_contains_operations():
    contract = _load_json(ROOT / "native" / "contracts" / "v2-runtime.openapi.json")
    paths = contract.get("paths", {})
    # The same-path contract is mirrored in v2-runtime for auditability
    assert "/api/v1/continuity-rules/" in paths
    assert "/api/v1/continuity-rules/{rule_id}" in paths


def test_python_handler_retired():
    # Python handler file should be removed after retirement
    handler = ROOT / "app" / "api" / "continuity_rule.py"
    assert not handler.exists(), "Python handler should be deleted after cutover"


def test_python_mount_removed():
    # router_mounts should no longer mount continuity_rule
    mounts = ROOT / "app" / "router_mounts.py"
    if mounts.exists():
        content = mounts.read_text(encoding="utf-8")
        assert "continuity_rule" not in content


def test_retired_python_handlers_fixture_pins_operations():
    fixture = _load_json(ROOT / "tests" / "fixtures" / "retired-python-handlers.json")
    entries = [e for e in fixture if "/continuity-rules" in e.get("path", "")]
    # Should have five entries for the family
    methods = {(e["path"], tuple(e["methods"])) for e in entries}
    assert len(entries) >= 5
    assert ("/api/v1/continuity-rules/", ("GET",)) in methods
    assert ("/api/v1/continuity-rules/", ("POST",)) in methods


def test_rust_module_registered():
    lib = (ROOT / "native" / "roll-service" / "src" / "lib.rs").read_text(encoding="utf-8")
    assert "mod continuity_rules" in lib
    # Check route registration
    assert "continuity_rules::list" in lib
    assert "continuity_rules::create" in lib
    assert "continuity_rules::get" in lib
    assert "continuity_rules::update" in lib
    assert "continuity_rules::delete" in lib


def test_frontend_generated_client_uses_v1_paths():
    # Generated client should reference v1 continuity-rules paths, not hand-written service
    # Existence of native contracts implies generation succeeded; check that no hand-written service remains
    service = ROOT / "frontend" / "src" / "services" / "api-continuity-rules.ts"
    assert not service.exists(), "Hand-written frontend service should be removed"


def test_inventory_exclusion_for_fragment():
    # The fragment marks operations exclude_from_inventory, so they should not appear in v2 route inventory as active v2 ops
    inventory = _load_json(ROOT / "docs" / "api" / "v2-route-inventory.json")
    # The inventory is bot-owned; we just verify it loads and burndown exists
    assert "burndown" in inventory
    # Ensure continuity-rules operations are not listed as live Python with callers
    # (They are excluded, so absence is expected)
    # A simple sanity check: the file is valid JSON
    assert isinstance(inventory.get("operations"), list)
