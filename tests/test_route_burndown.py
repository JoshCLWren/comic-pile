"""Regression tests for the deterministic v2 route burndown generator.

The generator in ``scripts/generate_route_burndown.py`` derives one checked-in
inventory (``docs/api/v2-route-inventory.json``) and one compact generated
``AGENTS.md`` runtime section from deployed ingress in ``vercel.json``. These
tests pin the current burndown (41 live operations: 40 Native Rust + the one
transitional Python operation) and the ``--check`` determinism contract.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from scripts.generate_route_burndown import (
    BurndownGenerationError,
    FRAGMENT_DIR,
    RouteFragment,
    _classify_burndown,
    _fragment_vercel_groups,
    _generate_vercel_document,
    _load_route_fragments,
    _load_routes,
    _merge_route_fragments,
    _render_agents_block,
    _render_agents_text,
    _render_inventory,
    _render_rewrite_fragment,
    _render_vercel_text,
    _resolve_destination,
    _routes_from_document,
    load_json,
)


ROOT = Path(__file__).resolve().parents[1]
INVENTORY_PATH = ROOT / "docs" / "api" / "v2-route-inventory.json"
VERCEL_PATH = ROOT / "vercel.json"
AGENTS_PATH = ROOT / "AGENTS.md"
REWRITE_FRAGMENT_PATH = FRAGMENT_DIR / "vercel-rewrites.json"


def _operation(
    operations: list[dict[str, object]], method: str, path: str
) -> dict[str, object]:
    """Find one inventory operation by method and path.

    Args:
        operations: Inventory operation dicts.
        method: HTTP method.
        path: Path template.

    Returns:
        The matching operation dict.

    Raises:
        AssertionError: When no operation matches.
    """
    for operation in operations:
        if operation.get("method") == method and operation.get("path") == path:
            return operation
    raise AssertionError(f"missing operation {method} {path}")


def test_burndown_summary_matches_deployed_ingress() -> None:
    """Inventory burndown reports the current native and Python v2 surface."""
    inventory = load_json(INVENTORY_PATH)
    burndown = inventory.get("burndown")
    assert isinstance(burndown, dict)
    assert burndown.get("total_live_operations") == 41
    assert burndown.get("native_rust") == 40
    assert burndown.get("python_fastapi") == 1
    assert burndown.get("native_rust_status") == 40
    assert burndown.get("unreferenced_or_orphaned") == 1
    assert burndown.get("ingress_source") == "vercel.json"
    raw_operations = inventory.get("operations")
    assert isinstance(raw_operations, list)
    operations = [item for item in raw_operations if isinstance(item, dict)]
    assert len(operations) == 41
    for operation in operations:
        assert operation.get("ingress_destination")
        assert operation.get("burndown_status")
        assert operation.get("verified_against") == "vercel.json"


def test_reading_boundaries_split_uses_deployed_ingress() -> None:
    """POST boundaries is Native Rust; GET detail is Python transitional."""
    inventory = load_json(INVENTORY_PATH)
    raw_operations = inventory.get("operations")
    assert isinstance(raw_operations, list)
    operations = [item for item in raw_operations if isinstance(item, dict)]
    post = _operation(operations, "POST", "/api/v2/reading-boundaries")
    assert post.get("runtime") == "native-rust"
    assert post.get("ingress_destination") == "/api/native_roll.rs"
    assert post.get("burndown_status") == "native Rust"
    get_detail = _operation(operations, "GET", "/api/v2/reading-boundaries/{thread_id}")
    assert get_detail.get("runtime") == "python-fastapi"
    assert get_detail.get("ingress_destination") == "/api/index.py"
    assert get_detail.get("burndown_status") == "unreferenced/orphaned"
    assert get_detail.get("owning_issue") == 4335


def test_classify_distinguishes_all_burndown_statuses() -> None:
    """Each issue status has a distinct classification rule."""
    assert _classify_burndown("native-rust", [], "/api/native_roll.rs") == "native Rust"
    assert (
        _classify_burndown("native-rust", ["x"], "/api/native_issue.rs")
        == "native Rust"
    )
    assert (
        _classify_burndown("python-fastapi", [], "/api/native_roll.rs")
        == "shadowed by Rust"
    )
    assert (
        _classify_burndown("python-fastapi", ["caller.ts"], "/api/index.py")
        == "live transitional Python with callers"
    )
    assert (
        _classify_burndown("python-fastapi", [], "/api/index.py")
        == "unreferenced/orphaned"
    )


def test_native_declaration_contradicting_ingress_fails() -> None:
    """A native declaration that ingresses to Python is a hard error."""
    with pytest.raises(BurndownGenerationError):
        _classify_burndown("native-rust", [], "/api/index.py")


def test_full_surface_matches_deployed_ingress() -> None:
    """Full-surface inventory pins v1/unversioned counts and shadowed set."""
    inventory = load_json(INVENTORY_PATH)
    full_surface = inventory.get("full_surface")
    assert isinstance(full_surface, dict)
    summary = full_surface.get("summary")
    assert isinstance(summary, dict)
    assert isinstance(summary.get("v1_total"), int)
    assert isinstance(summary.get("unversioned_total"), int)
    assert summary["total_python_surface"] == (
        summary["v1_total"] + summary["unversioned_total"]
    )
    assert summary["total_shadowed_by_rust"] == (
        summary["v1_shadowed_by_rust"] + summary["unversioned_shadowed_by_rust"]
    )
    assert summary["total_live_python"] == (
        summary["v1_live_python"] + summary["unversioned_live_python"]
    )
    assert summary.get("catch_all_src") == "/api(?:/.*)?"
    assert summary.get("catch_all_dest") == "/api/native_roll.rs"
    assert summary.get("orphan_method") == "GET"
    assert (
        summary.get("orphan_path")
        == "/api/v2/reading-boundaries/{thread_id}"
    )
    catch_all = full_surface.get("catch_all")
    assert isinstance(catch_all, dict)
    orphan = full_surface.get("orphan")
    assert isinstance(orphan, dict)
    raw_v1 = full_surface.get("v1_operations")
    raw_unversioned = full_surface.get("unversioned_operations")
    assert isinstance(raw_v1, list)
    assert isinstance(raw_unversioned, list)
    v1_ops = [item for item in raw_v1 if isinstance(item, dict)]
    unversioned_ops = [item for item in raw_unversioned if isinstance(item, dict)]
    assert len(v1_ops) == summary["v1_total"]
    assert len(unversioned_ops) == summary["unversioned_total"]
    shadowed_v1 = [
        item for item in v1_ops if item.get("burndown_status") == "shadowed by Rust"
    ]
    assert len(shadowed_v1) == sum(
        item.get("ingress_destination") == "/api/native_roll.rs"
        for item in v1_ops
    )
    assert any(
        item.get("method") == "GET"
        and item.get("path") == "/api/v1/creators"
        and item.get("burndown_status") == "shadowed by Rust"
        for item in v1_ops
    )
    assert any(
        item.get("method") == "GET"
        and item.get("path") == "/api/v1/creators/summaries"
        and item.get("burndown_status") == "shadowed by Rust"
        for item in v1_ops
    )
    assert any(
        item.get("method") == "POST"
        and item.get("path") == "/api/v1/catalog/series-mappings/commit"
        and item.get("burndown_status") == "shadowed by Rust"
        for item in v1_ops
    )
    for item in shadowed_v1:
        assert item.get("ingress_destination") == "/api/native_roll.rs"
    assert any(
        item.get("method") == "POST"
        and item.get("path") == "/api/v1/bug-reports/"
        and item.get("burndown_status") == "shadowed by Rust"
        for item in v1_ops
    )
    assert any(
        item.get("method") == "GET"
        and item.get("path") == "/api/v1/issues/{issue_id}"
        and item.get("burndown_status") == "shadowed by Rust"
        for item in v1_ops
    )
    assert any(
        item.get("method") == "GET"
        and item.get("path") == "/api/v1/issues/{issue_id}/comicvine"
        and item.get("burndown_status") == "shadowed by Rust"
        for item in v1_ops
    )
    assert any(
        item.get("method") == "GET"
        and item.get("path") == "/api/v1/issues/{issue_id}/dependencies"
        and item.get("burndown_status") == "shadowed by Rust"
        for item in v1_ops
    )
    assert any(
        item.get("method") == "GET"
        and item.get("path")
        == "/api/v1/comicvine/series/{comicvine_volume_id}/import-status"
        and item.get("burndown_status") == "shadowed by Rust"
        for item in v1_ops
    )
    assert any(
        item.get("method") == "GET"
        and item.get("path") == "/api/v1/threads/{thread_id}/issue-dependencies"
        and item.get("burndown_status") == "shadowed by Rust"
        for item in v1_ops
    )
    assert any(
        item.get("method") == "POST"
        and item.get("path") == "/api/v1/roll/dismiss-pending"
        and item.get("burndown_status") == "shadowed by Rust"
        for item in v1_ops
    )
    assert any(
        item.get("method") == "POST"
        and item.get("path") == "/api/v1/auth/login"
        and item.get("burndown_status") == "shadowed by Rust"
        for item in v1_ops
    )
    assert any(
        item.get("method") == "POST"
        and item.get("path") == "/api/v1/taste/discoveries/{signal_id}/dismiss"
        and item.get("burndown_status") == "shadowed by Rust"
        for item in v1_ops
    )
    assert any(
        item.get("method") == "GET"
        and item.get("path") == "/api/v1/taste/discoveries"
        and item.get("burndown_status") == "live transitional Python with callers"
        for item in v1_ops
    )
    assert any(
        item.get("method") == "GET"
        and item.get("path") == "/api/v1/threads/{thread_id}"
        and item.get("burndown_status") == "shadowed by Rust"
        for item in v1_ops
    )
    shadowed_unversioned = [
        item
        for item in unversioned_ops
        if item.get("burndown_status") == "shadowed by Rust"
    ]
    assert len(shadowed_unversioned) == 13
    assert any(
        item.get("path") == "/api/auth/login"
        and item.get("burndown_status") == "shadowed by Rust"
        for item in unversioned_ops
    )
    assert any(
        item.get("method") == "POST"
        and item.get("path") == "/api/bug-reports/"
        and item.get("burndown_status") == "shadowed by Rust"
        for item in unversioned_ops
    )
    assert any(
        item.get("method") == "GET"
        and item.get("path") == "/api/threads/{thread_id}"
        and item.get("burndown_status") == "shadowed by Rust"
        for item in unversioned_ops
    )
    live_v1 = [
        item
        for item in v1_ops
        if item.get("burndown_status")
        == "live transitional Python with callers"
    ]
    assert len(live_v1) == summary["v1_live_python"]
    for item in live_v1:
        assert item.get("ingress_destination") == "/api/index.py"
        assert item.get("consumers")
    assert all(
        item.get("burndown_status") == "shadowed by Rust"
        for item in v1_ops
        if str(item.get("path", "")).startswith("/api/v1/identity-inbox")
    )
    assert all(
        item.get("burndown_status") == "shadowed by Rust"
        for item in v1_ops
        if str(item.get("path", "")).startswith("/api/v1/continuity-rules")
    )
    assert all(
        item.get("burndown_status") == "shadowed by Rust"
        for item in v1_ops
        if str(item.get("path", "")).startswith("/api/v1/releases")
    )
    assert all(
        item.get("burndown_status") == "shadowed by Rust"
        for item in v1_ops
        if str(item.get("path", "")).startswith("/api/v1/tags")
    )
    assert any(
        item.get("method") == "GET"
        and item.get("path") == "/api/v1/users/me/preferences"
        and item.get("burndown_status") == "shadowed by Rust"
        and item.get("owning_issue") == 4834
        for item in v1_ops
    )
    assert any(
        item.get("method") == "PATCH"
        and item.get("path") == "/api/v1/users/me/preferences"
        and item.get("burndown_status") == "shadowed by Rust"
        and item.get("owning_issue") == 4834
        for item in v1_ops
    )
    assert any(
        item.get("method") == "GET"
        and item.get("path") == "/api/v1/users/me/taste-signals"
        and item.get("burndown_status") == "shadowed by Rust"
        and item.get("owning_issue") == 4834
        for item in v1_ops
    )
    assert any(
        item.get("method") == "PUT"
        and item.get("path")
        == "/api/v1/users/me/taste-signals/{signal_type}/{external_key}/verdict"
        and item.get("burndown_status") == "shadowed by Rust"
        and item.get("owning_issue") == 4834
        for item in v1_ops
    )
    assert any(
        item.get("method") == "GET"
        and item.get("path") == "/api/v1/reading-mode"
        and item.get("burndown_status") == "shadowed by Rust"
        for item in v1_ops
    )
    assert any(
        item.get("method") == "POST"
        and item.get("path") == "/api/v1/reading-mode"
        and item.get("burndown_status") == "shadowed by Rust"
        for item in v1_ops
    )
    assert any(
        item.get("method") == "POST"
        and item.get("path") == "/api/v1/reading-mode/dismiss-suggestion"
        and item.get("burndown_status") == "shadowed by Rust"
        for item in v1_ops
    )
    assert any(
        item.get("method") == "POST"
        and item.get("path") == "/api/v1/reading-mode/suggest"
        and item.get("burndown_status") == "shadowed by Rust"
        for item in v1_ops
    )
    assert any(
        item.get("method") == "POST"
        and item.get("path") == "/api/v1/threads/groups:batch"
        and item.get("burndown_status")
        == "live transitional Python with callers"
        for item in v1_ops
    )
    assert any(
        item.get("method") == "GET"
        and item.get("path") == "/api/v1/sessions/current/"
        and item.get("burndown_status")
        == "live transitional Python with callers"
        for item in v1_ops
    )
    assert all(
        item.get("ingress_destination") == "/api/native_roll.rs"
        and item.get("burndown_status") == "shadowed by Rust"
        for item in v1_ops
        if item.get("path")
        in {
            "/api/v1/sessions/{session_id}",
            "/api/v1/sessions/{session_id}/snapshots",
        }
    )
    assert all(
        item.get("ingress_destination") == "/api/native_roll.rs"
        and item.get("burndown_status") == "shadowed by Rust"
        for item in unversioned_ops
        if item.get("path")
        in {
            "/api/sessions/{session_id}",
            "/api/sessions/{session_id}/snapshots",
        }
    )
    assert any(
        item.get("method") == "GET"
        and item.get("path") == "/api/v1/sessions/correction-examples"
        and item.get("burndown_status")
        == "live transitional Python with callers"
        for item in v1_ops
    )
    for item in v1_ops:
        if item.get("burndown_status") == "shadowed by Rust":
            assert item.get("runtime") == "python-fastapi"


def test_dependencies_slice_routes_native_while_python_remains_declared() -> None:
    """All browser dependency paths use native ingress without deleting Python."""
    inventory = load_json(INVENTORY_PATH)
    full_surface = inventory["full_surface"]
    assert isinstance(full_surface, dict)
    operations = full_surface["v1_operations"]
    assert isinstance(operations, list)
    expected = {
        ("POST", "/api/v1/dependencies/"),
        ("GET", "/api/v1/dependencies/blocked"),
        ("DELETE", "/api/v1/dependencies/{dependency_id}"),
        ("GET", "/api/v1/dependencies/{dependency_id}"),
        ("PATCH", "/api/v1/dependencies/{dependency_id}"),
    }
    actual = {
        (item["method"], item["path"])
        for item in operations
        if isinstance(item, dict) and item["path"].startswith("/api/v1/dependencies")
    }
    assert actual == expected
    for item in operations:
        if isinstance(item, dict) and (item["method"], item["path"]) in expected:
            assert item["runtime"] == "python-fastapi"
            assert item["ingress_destination"] == "/api/native_roll.rs"
            assert item["burndown_status"] == "shadowed by Rust"


def test_rendered_outputs_match_checked_in_files() -> None:
    """Re-rendered inventory and agents section equal the checked-in bytes."""
    inventory = load_json(INVENTORY_PATH)
    routes = _load_routes(VERCEL_PATH)
    fragments = _load_route_fragments(FRAGMENT_DIR)
    payload, inventory_text = _render_inventory(inventory, routes, fragments)
    assert INVENTORY_PATH.read_text(encoding="utf-8") == inventory_text
    inventory_from_file = json.loads(INVENTORY_PATH.read_text(encoding="utf-8"))
    assert isinstance(inventory_from_file, dict)
    raw_operations = inventory_from_file.get("operations")
    assert isinstance(raw_operations, list)
    operations = [item for item in raw_operations if isinstance(item, dict)]
    full_surface = payload.get("full_surface")
    assert isinstance(full_surface, dict)
    raw_summary = full_surface.get("summary")
    assert isinstance(raw_summary, dict)
    full_summary = {str(key): item for key, item in raw_summary.items()}
    block = _render_agents_block(operations, full_summary)
    agents_original = AGENTS_PATH.read_text(encoding="utf-8")
    assert _render_agents_text(agents_original, block) == agents_original


def test_route_fragments_are_loaded_in_filename_order() -> None:
    """Family fragments have stable ordering independent of filesystem order."""
    fragments = _load_route_fragments(FRAGMENT_DIR)
    assert [fragment.name for fragment in fragments] == [
        "bug-reports",
        "catalog",
        "comicvine",
        "completed-threads",
        "continuity-rules",
        "creators",
        "custom-cbl",
        "dependencies",
        "issues",
        "preferences",
        "reading-mode",
        "releases",
        "sessions",
        "tags",
        "taste-discoveries",
        "threads",
    ]


def _fragment_named(name: str) -> RouteFragment:
    """Find one family fragment by name.

    Args:
        name: Family name to find.

    Returns:
        The matching fragment.

    Raises:
        AssertionError: When no fragment matches.
    """
    for fragment in _load_route_fragments(FRAGMENT_DIR):
        if fragment.name == name:
            return fragment
    raise AssertionError(f"missing fragment {name}")


def test_creator_fragment_covers_creator_and_creator_adjacent_metadata() -> None:
    """The creators pilot owns all of its v1 route declarations."""
    fragment = _fragment_named("creators")
    paths = {operation["path"] for operation in fragment.operations}
    assert "/api/v1/creators" in paths
    assert "/api/v1/threads/{thread_id}/issues/creators" in paths


def test_dependency_fragment_covers_native_and_python_metadata() -> None:
    """The dependencies pilot owns both API versions and legacy routes."""
    fragment = _fragment_named("dependencies")
    buckets = {operation["bucket"] for operation in fragment.operations}
    assert buckets == {"operations", "v1_operations"}
    assert any(
        operation["path"] == "/api/v2/dependencies/"
        for operation in fragment.operations
    )


def test_release_fragment_covers_every_browser_called_release_route() -> None:
    """The releases family owns all five browser-called operations."""
    release_fragment = _fragment_named("releases")
    methods_paths = {
        (operation["method"], operation["path"])
        for operation in release_fragment.operations
    }
    assert methods_paths == {
        ("GET", "/api/v1/releases/"),
        ("PUT", "/api/v1/releases/"),
        ("GET", "/api/v1/releases/source"),
        ("GET", "/api/v1/releases/{release_id}"),
        ("POST", "/api/v1/releases/{release_id}/retract"),
    }


def test_fragment_merge_preserves_inventory_operation_counts() -> None:
    """Merging source fragments is idempotent over the generated inventory."""
    inventory = load_json(INVENTORY_PATH)
    merged = _merge_route_fragments(inventory, _load_route_fragments(FRAGMENT_DIR))
    full = merged["full_surface"]
    assert isinstance(full, dict)
    inventory_full = inventory["full_surface"]
    assert isinstance(inventory_full, dict)
    assert len(merged["operations"]) == len(inventory["operations"])
    assert len(full["v1_operations"]) == len(inventory_full["v1_operations"])


def test_fragment_ownership_removes_stale_deleted_family_routes() -> None:
    """Removing a route from a family source cannot leave a generated ghost."""
    inventory = load_json(INVENTORY_PATH)
    creators = RouteFragment(
        name="creators",
        owned_path_patterns=(r"^/api/v1/creators(?:/.*)?$",),
        operations=(),
    )
    merged = _merge_route_fragments(inventory, [creators])
    full = merged["full_surface"]
    assert isinstance(full, dict)
    assert all(
        not str(operation["path"]).startswith("/api/v1/creators")
        for operation in full["v1_operations"]
    )


def test_generated_rewrite_fragment_matches_checked_in_file() -> None:
    """The checked-in rewrite artifact is deterministic."""
    routes = _load_routes(VERCEL_PATH)
    expected = _render_rewrite_fragment(_load_route_fragments(FRAGMENT_DIR), routes)
    assert REWRITE_FRAGMENT_PATH.read_text(encoding="utf-8") == expected


def test_generated_rewrite_fragment_places_native_routes_first() -> None:
    """Native rewrites precede every Python family rewrite."""
    artifact = json.loads(REWRITE_FRAGMENT_PATH.read_text(encoding="utf-8"))
    destinations = [route["dest"] for route in artifact["routes"]]
    first_python = next(
        (index for index, destination in enumerate(destinations) if destination == "/api/index.py"),
        len(destinations),
    )
    assert all(destination != "/api/index.py" for destination in destinations[:first_python])
    assert all(destination == "/api/index.py" for destination in destinations[first_python:])


def test_generated_rewrite_fragment_excludes_global_catch_all() -> None:
    """The family artifact contains only family rewrites, not global ingress."""
    artifact = json.loads(REWRITE_FRAGMENT_PATH.read_text(encoding="utf-8"))
    assert all(route["src"] != "/api(?:/.*)?" for route in artifact["routes"])


def test_agents_table_uses_deployed_ingress_not_url_version() -> None:
    """AGENTS.md generated section reflects vercel.json destinations."""
    agents = AGENTS_PATH.read_text(encoding="utf-8")
    assert "<!-- route-burndown:begin" in agents
    assert "Live v2 operations: 41 (40 native-rust + 1 python orphan)" in agents
    assert "`/api/native_roll.rs`, `/api/native_issue.rs`" in agents
    assert (
        "Python orphan: `GET /api/v2/reading-boundaries/{thread_id} "
        "-> python-fastapi` via `/api/index.py`" in agents
    )
    assert "`POST /api/v2/reading-boundaries -> native-rust`" in agents
    assert "`GET /api/v2/reading-boundaries/{thread_id} -> python-fastapi`" in agents
    assert "see `docs/api/v2-route-inventory.json` (authoritative)" in agents
    assert "Full Python-handler surface:" in agents
    assert "v1 active" in agents
    assert "unversioned active" in agents
    assert "`/api(?:/.*)? -> /api/native_roll.rs`" in agents
    assert "`docs/api/v2-route-inventory.json` `full_surface` (authoritative)" in agents
    assert "Deployed runtime by cutover owner" in agents
    assert "- #4335 (10):" in agents
    assert "- #4684 (16):" in agents
    assert agents.count("<!-- route-burndown:end -->") == 1


def test_new_family_fragment_merges_without_touching_other_family() -> None:
    """One family's fragment merge never alters another family's routes."""
    inventory = load_json(INVENTORY_PATH)
    fragments = _load_route_fragments(FRAGMENT_DIR)
    tags = next(f for f in fragments if f.name == "tags")
    creators = next(f for f in fragments if f.name == "creators")

    merged_tags_only = _merge_route_fragments(inventory, [tags])
    merged_full = _merge_route_fragments(inventory, fragments)

    def _method_path_set(
        merged: dict[str, object], keys: set[tuple[str, str]]
    ) -> set[tuple[str, str]]:
        full = merged["full_surface"]
        assert isinstance(full, dict)
        v1 = full["v1_operations"]
        assert isinstance(v1, list)
        found: set[tuple[str, str]] = set()
        for operation in v1:
            assert isinstance(operation, dict)
            key = (str(operation["method"]), str(operation["path"]))
            if key in keys:
                found.add(key)
        return found

    creators_keys = {(str(op["method"]), str(op["path"])) for op in creators.operations}
    # Merging tags alone must not remove or alter any creators route.
    assert _method_path_set(merged_tags_only, creators_keys) == creators_keys
    assert _method_path_set(merged_full, creators_keys) == creators_keys
    tags_keys = {(str(op["method"]), str(op["path"])) for op in tags.operations}
    assert tags_keys
    assert tags_keys.isdisjoint(creators_keys)
    assert _method_path_set(merged_tags_only, tags_keys) == tags_keys


def test_generators_are_idempotent() -> None:
    """Re-rendering inventory and vercel from fragments yields identical bytes."""
    fragments = _load_route_fragments(FRAGMENT_DIR)
    previous = load_json(VERCEL_PATH)
    first_doc = _generate_vercel_document(previous, fragments)
    first_text = _render_vercel_text(first_doc)
    first_inventory = load_json(INVENTORY_PATH)
    _, first_inventory_text = _render_inventory(
        first_inventory, _routes_from_document(first_doc), fragments
    )
    second_doc = _generate_vercel_document(first_doc, fragments)
    second_text = _render_vercel_text(second_doc)
    assert first_text == second_text
    second_inventory = json.loads(first_inventory_text)
    assert isinstance(second_inventory, dict)
    _, second_inventory_text = _render_inventory(
        second_inventory, _routes_from_document(second_doc), fragments
    )
    assert first_inventory_text == second_inventory_text
    assert VERCEL_PATH.read_text(encoding="utf-8") == first_text


def test_vercel_is_fully_derived_from_fragments() -> None:
    """Checked-in vercel matches fragment derivation in native-before-Python order."""
    fragments = _load_route_fragments(FRAGMENT_DIR)
    previous = load_json(VERCEL_PATH)
    generated = _generate_vercel_document(previous, fragments)
    assert _render_vercel_text(generated) == VERCEL_PATH.read_text(encoding="utf-8")
    routes = _routes_from_document(generated)
    native_indices = [
        index
        for index, route in enumerate(routes)
        if route.dest in {"/api/native_roll.rs", "/api/native_issue.rs"}
        and route.src != "/api(?:/.*)?"
    ]
    python_indices = [
        index for index, route in enumerate(routes) if route.dest == "/api/index.py"
    ]
    assert native_indices and python_indices
    assert max(native_indices) < min(python_indices)
    # Every fragment operation resolves to its declared dest.
    for fragment in fragments:
        for operation in fragment.operations:
            method = str(operation["method"])
            path = str(operation["path"])
            dest = _resolve_destination(method, path, routes)
            assert dest == operation["dest"]


def test_hidden_cron_exception_is_preserved() -> None:
    """The hidden cron release-sync route stays on Python after derivation."""
    routes = _load_routes(VERCEL_PATH)
    assert _resolve_destination("GET", "/api/v1/cron/release-sync", routes) == "/api/index.py"
    document = load_json(VERCEL_PATH)
    crons = document.get("crons")
    assert isinstance(crons, list)
    assert any(
        isinstance(cron, dict) and cron.get("path") == "/api/v1/cron/release-sync"
        for cron in crons
    )
    assert any(
        isinstance(cron, dict)
        and cron.get("path") == "/api/v2/maintenance/comicvine-metadata-repairs"
        for cron in crons
    )


def test_fragment_groups_preserve_exact_dest_and_methods() -> None:
    """Fragment Vercel groups group methods per src/dest without losing OPTIONS."""
    fragments = _load_route_fragments(FRAGMENT_DIR)
    previous = load_json(VERCEL_PATH)
    previous_routes = _routes_from_document(previous)
    groups = _fragment_vercel_groups(fragments, previous_routes)
    for route in groups:
        dest = str(route["dest"])
        raw_methods = route["methods"]
        assert isinstance(raw_methods, list)
        methods = [str(item) for item in raw_methods if isinstance(item, str)]
        assert methods
        if dest == "/api/index.py":
            assert "OPTIONS" in methods
        else:
            assert "OPTIONS" not in methods
