"""Regression tests for the deterministic v2 route burndown generator.

The generator in ``scripts/generate_route_burndown.py`` derives one checked-in
inventory (``docs/api/v2-route-inventory.json``) and one compact generated
``AGENTS.md`` runtime section from deployed ingress in ``vercel.json``. These
tests pin the current burndown (all live v2 operations are Native Rust) and
the ``--check`` determinism contract.
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


IDENTITY_INBOX_OPERATIONS = {
    ("GET", "/api/v1/identity-inbox"),
    ("GET", "/api/v1/identity-inbox/search/issues"),
    ("GET", "/api/v1/identity-inbox/{mapping_id}"),
    ("POST", "/api/v1/identity-inbox/{mapping_id}/confirm"),
    ("POST", "/api/v1/identity-inbox/{mapping_id}/defer"),
    ("POST", "/api/v1/identity-inbox/{mapping_id}/reject"),
    ("POST", "/api/v1/identity-inbox/{mapping_id}/skip"),
}
RETAINED_NATIVE_UNVERSIONED = ("GET", "/api/auth/login")


def _assert_no_python_surface_operations(
    v1_ops: list[dict[str, object]],
    unversioned_ops: list[dict[str, object]],
    operations: set[tuple[str, str]],
) -> None:
    """Fail when a native-only operation reappears in the Python inventory."""
    present = {
        (str(item.get("method")), str(item.get("path")))
        for item in [*v1_ops, *unversioned_ops]
    } & operations
    assert not present, f"native-only operations reappeared in Python surface: {sorted(present)}"


def test_burndown_summary_matches_deployed_ingress() -> None:
    """Inventory burndown reports the current native and Python v2 surface."""
    inventory = load_json(INVENTORY_PATH)
    burndown = inventory.get("burndown")
    assert isinstance(burndown, dict)
    assert burndown.get("ingress_source") == "vercel.json"
    raw_operations = inventory.get("operations")
    assert isinstance(raw_operations, list)
    operations = [item for item in raw_operations if isinstance(item, dict)]
    assert operations, "v2 inventory must not be empty"
    assert len(operations) == burndown.get("total_live_operations")
    assert sum(item.get("runtime") == "native-rust" for item in operations) == burndown.get(
        "native_rust"
    )
    assert sum(item.get("runtime") == "python-fastapi" for item in operations) == burndown.get(
        "python_fastapi"
    )
    for status, count_field in (
        ("native Rust", "native_rust_status"),
        ("shadowed by Rust", "shadowed_by_rust"),
        ("live transitional Python with callers", "live_transitional_python_with_callers"),
        ("unreferenced/orphaned", "unreferenced_or_orphaned"),
    ):
        assert sum(item.get("burndown_status") == status for item in operations) == (
            burndown.get(count_field)
        )
    for operation in operations:
        assert operation.get("ingress_destination")
        assert operation.get("burndown_status")
        assert operation.get("verified_against") == "vercel.json"


def test_reading_boundaries_split_uses_deployed_ingress() -> None:
    """POST boundaries is native; the retired detail GET stays absent."""
    inventory = load_json(INVENTORY_PATH)
    raw_operations = inventory.get("operations")
    assert isinstance(raw_operations, list)
    operations = [item for item in raw_operations if isinstance(item, dict)]
    post = _operation(operations, "POST", "/api/v2/reading-boundaries")
    assert post.get("runtime") == "native-rust"
    assert post.get("ingress_destination") == "/api/native_roll.rs"
    assert post.get("burndown_status") == "native Rust"
    assert not any(
        item.get("method") == "GET"
        and item.get("path") == "/api/v2/reading-boundaries/{thread_id}"
        for item in operations
    )


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
    assert summary.get("orphan_method") is None
    assert summary.get("orphan_path") is None
    assert "orphan" not in full_surface
    catch_all = full_surface.get("catch_all")
    assert isinstance(catch_all, dict)
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
        and item.get("runtime") == "python-fastapi"
        for item in v1_ops
    )
    assert not any(item.get("path") == "/api/v1/threads/completed/threads" for item in v1_ops)
    assert not any(item.get("path") == "/api/v1/creators" for item in v1_ops)
    assert not any(item.get("path") == "/api/v1/creators/summaries" for item in v1_ops)
    for item in shadowed_v1:
        assert item.get("ingress_destination") == "/api/native_roll.rs"
    # The bug-report twins were cut over to same-path native Rust (#4852) and
    # their Python handler was retired (#5162), so the v1 bug-reports path is
    # excluded from the Python inventory surface entirely; native ingress is
    # pinned by test_bug_reports_fragment_routes_both_twins_to_native_rust.
    assert not any(
        str(item.get("path", "")).startswith("/api/v1/bug-reports")
        for item in v1_ops
    )
    assert not any(item.get("path") == "/api/v1/issues/{issue_id}" for item in v1_ops)
    assert not any(item.get("path") == "/api/v1/issues/{issue_id}/comicvine" for item in v1_ops)
    assert not any(item.get("path") == "/api/v1/issues/{issue_id}/dependencies" for item in v1_ops)
    assert not any(item.get("path") == "/api/v1/comicvine/series/{comicvine_volume_id}/import-status" for item in v1_ops)
    assert not any(item.get("path") == "/api/v1/threads/{thread_id}/issue-dependencies" for item in v1_ops)
    assert not any(item.get("path") == "/api/v1/roll/dismiss-pending" for item in v1_ops)
    assert not any(item.get("path") == "/api/v1/auth/login" for item in v1_ops)
    assert not any(item.get("path") == "/api/v1/taste/discoveries/{signal_id}/dismiss" for item in v1_ops)
    discoveries = _operation(v1_ops, "GET", "/api/v1/taste/discoveries")
    assert discoveries["burndown_status"] == "native Rust"
    assert discoveries["runtime"] == "native-rust"
    assert discoveries["ingress_destination"] == "/api/native_roll.rs"
    assert not any(
        item.get("method") == "GET" and item.get("path") == "/api/v1/threads/{thread_id}"
        for item in v1_ops
    )
    assert not any(item.get("path") == "/api/v1/threads/{thread_id}/dependencies" for item in v1_ops)
    shadowed_unversioned = [
        item
        for item in unversioned_ops
        if item.get("burndown_status") == "shadowed by Rust"
    ]
    assert len(shadowed_unversioned) == sum(
        item.get("ingress_destination") == "/api/native_roll.rs"
        and item.get("runtime") == "python-fastapi"
        for item in unversioned_ops
    )
    assert not any(item.get("path") == "/api/auth/login" for item in unversioned_ops)
    # Same retirement as the v1 twin: POST /api/bug-reports/ is native-only
    # (#4852, #5162) and no longer part of the Python inventory surface.
    assert not any(
        str(item.get("path", "")).startswith("/api/bug-reports")
        for item in unversioned_ops
    )
    assert not any(item.get("path") == "/api/threads/{thread_id}" for item in unversioned_ops)
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
    _assert_no_python_surface_operations(v1_ops, unversioned_ops, IDENTITY_INBOX_OPERATIONS)
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
    assert not any(item.get("path") == "/api/v1/users/me/preferences" for item in v1_ops)
    assert not any(item.get("path") == "/api/v1/users/me/preferences" for item in v1_ops)
    assert not any(item.get("path") == "/api/v1/users/me/taste-signals" for item in v1_ops)
    assert not any(item.get("path") == "/api/v1/users/me/taste-signals/{signal_type}/{external_key}/verdict" for item in v1_ops)
    assert not any(item.get("path") == "/api/v1/reading-mode" for item in v1_ops)
    assert not any(item.get("path") == "/api/v1/reading-mode" for item in v1_ops)
    assert not any(item.get("path") == "/api/v1/reading-mode/dismiss-suggestion" for item in v1_ops)
    assert not any(item.get("path") == "/api/v1/reading-mode/suggest" for item in v1_ops)
    # Thread lifecycle operations cut over to same-path native Rust (#4832);
    # the Python handler stays mounted until its separate removal PR.
    assert any(
        item.get("method") == "POST"
        and item.get("path") == "/api/v1/threads/groups:batch"
        and item.get("burndown_status") == "native Rust"
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
    for item in v1_ops:
        if item.get("burndown_status") == "shadowed by Rust":
            assert item.get("runtime") == "python-fastapi"


def test_identity_inbox_native_contract_covers_retired_operations() -> None:
    """All seven retired identity-inbox operations keep a native same-path contract."""
    native = load_json(ROOT / "native" / "contracts" / "same-path-runtime.openapi.json")
    paths = native["paths"]
    assert isinstance(paths, dict)
    for method, path in IDENTITY_INBOX_OPERATIONS:
        declaration = paths[path][method.lower()]
        assert declaration["operationId"]
        assert any(code.startswith("2") for code in declaration["responses"])


def test_python_surface_guard_rejects_deliberate_regressions() -> None:
    """The guard flags a reintroduced identity-inbox and unversioned native route."""
    with pytest.raises(AssertionError, match="reappeared"):
        _assert_no_python_surface_operations(
            [{"method": "GET", "path": "/api/v1/identity-inbox"}],
            [{"method": "GET", "path": "/api/auth/login"}],
            IDENTITY_INBOX_OPERATIONS | {RETAINED_NATIVE_UNVERSIONED},
        )


def test_dependencies_slice_routes_native_after_python_retirement() -> None:
    """Retired v1 dependency handlers stay absent; live v2 contracts stay native."""
    inventory = load_json(INVENTORY_PATH)
    full_surface = inventory["full_surface"]
    assert isinstance(full_surface, dict)
    operations = full_surface["v1_operations"]
    assert isinstance(operations, list)
    assert not any(
        isinstance(item, dict) and item["path"].startswith("/api/v1/dependencies")
        for item in operations
    )
    for method, path in (
        ("POST", "/api/v2/dependencies/"),
        ("DELETE", "/api/v2/dependencies/{dependency_id}"),
    ):
        operation = _operation(inventory["operations"], method, path)
        assert operation["runtime"] == "native-rust"
        assert operation["ingress_destination"] == "/api/native_roll.rs"


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


def test_custom_cbl_fragment_routes_every_v1_operation_to_native() -> None:
    """Issue #4844 cuts every migrated custom-cbl v1 operation over by source fragment.

    Generated ``vercel.json`` and the inventory are bot-owned and regenerated
    post-merge, so the source fragment is the reviewable proof that these
    same-path operations serve the native ingress rather than Python.
    """
    fragment = load_json(FRAGMENT_DIR / "custom-cbl.json")
    operations = fragment["operations"]
    assert isinstance(operations, list)
    v1_operations = [op for op in operations if op["bucket"] == "v1_operations"]
    assert len(v1_operations) == 11
    for operation in v1_operations:
        assert operation["dest"] == "/api/native_roll.rs", operation
        assert operation["runtime"] == "native-rust", operation
        assert operation["status"] == "target", operation
        assert operation["owning_issue"] == 4844, operation


def test_route_fragments_are_loaded_in_filename_order() -> None:
    """Family fragments have stable ordering independent of filesystem order."""
    fragments = _load_route_fragments(FRAGMENT_DIR)
    assert [fragment.name for fragment in fragments] == [
        "activity",
        "bug-reports",
        "catalog",
        "comicvine",
        "completed-threads",
        "continuity-plans",
        "continuity-rules",
        "creators",
        "custom-cbl",
        "demo",
        "dependencies",
        "issue-identity-cbl-catalog",
        "issue-identity",
        "issues",
        "metrics",
        "preferences",
        "reading-mode",
        "reading-orders",
        "reading-plan-sync",
        "releases",
        "roll",
        "sessions",
        "tags",
        "taste-discoveries",
        "threads",
        "undo",
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


def test_creator_fragment_covers_native_v2_and_creator_adjacent_metadata() -> None:
    """The creators pilot owns its native v2 routes plus creator-adjacent v1 metadata."""
    fragment = _fragment_named("creators")
    paths = {operation["path"] for operation in fragment.operations}
    assert "/api/v2/creators" in paths
    assert "/api/v2/creators/{creator_key}" in paths
    assert "/api/v2/creators/{creator_key}/series/{series_key}/issues" in paths
    assert "/api/v1/threads/{thread_id}/issues/creators" in paths


def test_creator_v2_operations_are_native_rust_in_source_fragment() -> None:
    """Issue #4836: every creator browser operation is declared Rust-served on v2.

    Generated ``vercel.json`` and the inventory are bot-owned and regenerated
    post-merge from fragments, so the source fragment is the reviewable proof
    that each ``/api/v2/creators`` operation serves the native ingress with the
    native-rust runtime, target status and owning issue (overriding the
    family's python-fastapi/transitional/null defaults). The legacy v1 creator
    declarations are retained here and retired by a later change.
    """
    fragment = _fragment_named("creators")
    v2_operations = [
        operation
        for operation in fragment.operations
        if str(operation.get("path", "")).startswith("/api/v2/creators")
    ]
    assert len(v2_operations) == 11
    assert len({(op["method"], op["path"]) for op in v2_operations}) == 11
    for operation in v2_operations:
        assert operation["bucket"] == "operations", operation
        assert operation["method"] == "GET", operation
        assert operation["dest"] == "/api/native_roll.rs", operation
        assert operation["runtime"] == "native-rust", operation
        assert operation["status"] == "target", operation
        assert operation["owning_issue"] == 4836, operation


def test_dependency_fragment_covers_native_and_python_metadata() -> None:
    """The dependencies pilot owns both API versions and legacy routes."""
    fragment = _fragment_named("dependencies")
    buckets = {operation["bucket"] for operation in fragment.operations}
    assert buckets == {"operations", "v1_operations"}
    assert any(
        operation["path"] == "/api/v2/dependencies/"
        for operation in fragment.operations
    )


def test_bug_reports_fragment_routes_both_twins_to_native_rust() -> None:
    """The bug-reports family owns both POST twins as native after #4852.

    The same-path Rust cutover (#4899, issue #4852) plus the Python handler
    retirement (#5162) exclude both operations from the Python inventory
    surface while keeping their exact method/path on native ingress.
    """
    fragment = _fragment_named("bug-reports")
    operations = {
        (operation["method"], operation["path"]): operation
        for operation in fragment.operations
    }
    assert set(operations) == {
        ("POST", "/api/bug-reports/"),
        ("POST", "/api/v1/bug-reports/"),
    }
    for operation in operations.values():
        assert operation["dest"] == "/api/native_roll.rs"
        assert operation["exclude_from_inventory"] is True
        assert operation["owning_issue"] == 4852
    inventory = load_json(INVENTORY_PATH)
    full_surface = inventory["full_surface"]
    assert isinstance(full_surface, dict)
    for bucket in ("v1_operations", "unversioned_operations"):
        raw_operations = full_surface[bucket]
        assert isinstance(raw_operations, list)
        assert not any(
            "bug-reports" in str(item.get("path", ""))
            for item in raw_operations
            if isinstance(item, dict)
        )


def test_sessions_undo_fragments_route_cutover_ops_to_native_rust() -> None:
    """The sessions and undo fragments cut the supported cutover ops to Rust.

    The owner's 2026-11-17 correction on #4839 retired the current-session and
    restore-session-start twins under #4343 instead of porting them: both
    routes and their Python handlers are deleted and have no fragment entry
    (see ``tests/test_retired_session_lifecycle_4343.py``). Only the read-only list/details/history and
    undo operations are cut over to native Rust. Unversioned paths have no
    TypeScript client or FastAPI registry operation; they stay in the fragment
    only for the Vercel rewrite. The no-runtime-caller session examples
    v1 endpoint is retired.
    """
    sessions = _fragment_named("sessions")
    undo = _fragment_named("undo")
    native_ops = {
        ("GET", "/api/sessions/"),
        ("GET", "/api/v1/sessions/"),
        ("GET", "/api/sessions/{session_id}/details"),
        ("GET", "/api/v1/sessions/{session_id}/details"),
        ("GET", "/api/undo/{session_id}/snapshots"),
        ("POST", "/api/undo/{session_id}/undo/{snapshot_id}"),
        ("GET", "/api/v1/undo/{session_id}/snapshots"),
        ("POST", "/api/v1/undo/{session_id}/undo/{snapshot_id}"),
    }
    python_ops: set[tuple[str, str]] = set()
    declared = {
        (operation["method"], operation["path"]): operation
        for fragment in (sessions, undo)
        for operation in fragment.operations
    }
    assert native_ops | python_ops <= set(declared)
    for key in native_ops:
        operation = declared[key]
        assert operation["dest"] == "/api/native_roll.rs", key
        # The v1 Python handlers stay mounted until their cleanup slice, so
        # those cutover operations remain on the Python inventory surface as
        # shadowed-by-Rust entries. Unversioned paths have no FastAPI registry
        # operation or TypeScript caller and stay in the fragment for the
        # Vercel rewrite only.
        if key[1].startswith("/api/v1/"):
            assert operation.get("exclude_from_inventory") is not True, key
        else:
            assert operation.get("exclude_from_inventory") is True, key
        assert operation["owning_issue"] == 4839, key
    for key in python_ops:
        operation = declared[key]
        assert operation["dest"] == "/api/index.py", key
        assert operation.get("exclude_from_inventory") is not True, key

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
    inventory = load_json(INVENTORY_PATH)
    burndown = inventory.get("burndown")
    assert isinstance(burndown, dict)
    total = burndown.get("total_live_operations")
    native = burndown.get("native_rust")
    python = burndown.get("python_fastapi")
    assert isinstance(total, int) and isinstance(native, int) and isinstance(python, int)
    assert "<!-- route-burndown:begin" in agents
    assert f"Live v2 operations: {total} ({native} native-rust + {python} python-fastapi)" in agents
    assert "`/api/native_roll.rs`, `/api/native_issue.rs`" in agents
    assert "`POST /api/v2/reading-boundaries -> native-rust`" in agents
    assert "`GET /api/v2/reading-boundaries/{thread_id} -> python-fastapi`" not in agents
    assert "see `docs/api/v2-route-inventory.json` (authoritative)" in agents
    assert "Full Python-handler surface:" in agents
    assert "v1 active" in agents
    assert "unversioned active" in agents
    assert "`/api(?:/.*)? -> /api/native_roll.rs`" in agents
    assert "`docs/api/v2-route-inventory.json` `full_surface` (authoritative)" in agents
    assert "Deployed runtime by cutover owner" in agents
    assert "- #4335 (9):" in agents
    assert "- #4684 (16):" in agents
    assert agents.count("<!-- route-burndown:end -->") == 1


def test_new_family_fragment_merges_without_touching_other_family() -> None:
    """One family's fragment merge never alters another family's routes."""
    inventory = load_json(INVENTORY_PATH)
    fragments = _load_route_fragments(FRAGMENT_DIR)
    undo = next(f for f in fragments if f.name == "undo")
    creators = next(f for f in fragments if f.name == "creators")

    merged_undo_only = _merge_route_fragments(inventory, [undo])
    merged_full = _merge_route_fragments(inventory, fragments)

    def _method_path_set(
        merged: dict[str, object], keys: set[tuple[str, str]]
    ) -> set[tuple[str, str]]:
        full = merged["full_surface"]
        assert isinstance(full, dict)
        found: set[tuple[str, str]] = set()
        # The v2 ``operations`` bucket lives at the top level; the full Python
        # surface buckets live under ``full_surface`` (see
        # ``_merge_route_fragments``). Check both so no family merge can alter
        # another family's route in any bucket.
        buckets = [merged["operations"], full["v1_operations"], full["unversioned_operations"]]
        for operations in buckets:
            assert isinstance(operations, list)
            for operation in operations:
                assert isinstance(operation, dict)
                key = (str(operation["method"]), str(operation["path"]))
                if key in keys:
                    found.add(key)
        return found

    creators_keys = {(str(op["method"]), str(op["path"])) for op in creators.operations if not op.get("exclude_from_inventory")}
    # Merging undo alone must not remove or alter any creators route.
    assert _method_path_set(merged_undo_only, creators_keys) == creators_keys
    assert _method_path_set(merged_full, creators_keys) == creators_keys
    undo_keys = {(str(op["method"]), str(op["path"])) for op in undo.operations if not op.get("exclude_from_inventory")}
    assert undo_keys
    assert undo_keys.isdisjoint(creators_keys)
    assert _method_path_set(merged_undo_only, undo_keys) == undo_keys


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


def test_hidden_cron_fragment_declares_native_rust() -> None:
    """The hidden cron release-sync family declares native ingress (#5276).

    The checked-in ingress is bot-owned and regenerated after the fragment
    lands, so this pins the source fragment's declaration and the cron
    schedule rather than a pre-regeneration destination.
    """
    fragment = _fragment_named("reading-plan-sync")
    operations = {
        (operation["method"], operation["path"]): operation
        for operation in fragment.operations
    }
    cron = operations[("GET", "/api/v1/cron/release-sync")]
    assert cron["dest"] == "/api/native_roll.rs"
    assert cron["exclude_from_inventory"] is True
    assert cron["owning_issue"] == 5276
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
