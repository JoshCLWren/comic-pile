"""Drift guard for the live ``/api/v2`` method/path/runtime/caller inventory.

The inventory in ``docs/api/v2-route-inventory.json`` is the human-readable
authority for *where* each deployed v2 operation actually runs. This guard keeps
it synchronised with four independent sources:

* the canonical native Rust contract (``native/contracts/v2-runtime.openapi.json``),
* the single generated client schema (``frontend/src/generated/openapi.json``),
* production ingress (``vercel.json``),
* the declared frontend service callers.

API version is not implementation language: a v1 or v2 URL may be served by
either runtime. Update this inventory in the same PR that verifiably changes a
route's runtime, never by changing a client URL to find another implementation.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from scripts.generate_native_client import _method_name


ROOT = Path(__file__).resolve().parents[1]
INVENTORY_PATH = ROOT / "docs" / "api" / "v2-route-inventory.json"
NATIVE_CONTRACT_PATH = ROOT / "native" / "contracts" / "v2-runtime.openapi.json"
GENERATED_SCHEMA_PATH = ROOT / "frontend" / "src" / "generated" / "openapi.json"
VERCEL_CONFIG_PATH = ROOT / "vercel.json"
FRONTEND_SERVICES = ROOT / "frontend" / "src" / "services"

NATIVE_RUNTIME = "native-rust"
PYTHON_RUNTIME = "python-fastapi"
RUNTIMES = frozenset({NATIVE_RUNTIME, PYTHON_RUNTIME})
STATUSES = frozenset({"target", "transitional"})
NATIVE_DESTINATIONS = frozenset({"/api/native_roll.rs", "/api/native_issue.rs"})


@dataclass(frozen=True)
class _VercelRoute:
    """One validated entry from the ``routes`` array in ``vercel.json``."""

    src: str | None
    dest: str | None
    methods: tuple[str, ...]


def _load_json(path: Path) -> dict[str, Any]:
    """Load a JSON object from ``path``."""
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise AssertionError(f"{path} must contain a JSON object")
    return value


def _openapi_operations(document: dict[str, Any]) -> set[tuple[str, str]]:
    """Return every lowercase ``(method, path)`` in an OpenAPI document."""
    paths = document.get("paths")
    if not isinstance(paths, dict):
        raise AssertionError("OpenAPI document must define a paths object")
    operations: set[tuple[str, str]] = set()
    for path, item in paths.items():
        if not isinstance(path, str) or not isinstance(item, dict):
            raise AssertionError("OpenAPI paths must map strings to path items")
        for method in item:
            operations.add((method.lower(), path))
    return operations


def _inventory_operations() -> list[dict[str, Any]]:
    """Load and validate the inventory operations."""
    inventory = _load_json(INVENTORY_PATH)
    operations = inventory.get("operations")
    if not isinstance(operations, list):
        raise AssertionError("inventory must define an operations array")
    for index, operation in enumerate(operations):
        if not isinstance(operation, dict):
            raise AssertionError(f"operations[{index}] must be an object")
        if not isinstance(operation.get("method"), str):
            raise AssertionError(f"operations[{index}].method must be a string")
        if not isinstance(operation.get("path"), str):
            raise AssertionError(f"operations[{index}].path must be a string")
        if operation.get("runtime") not in RUNTIMES:
            raise AssertionError(
                f"operations[{index}].runtime must be one of {sorted(RUNTIMES)}"
            )
        if operation.get("status") not in STATUSES:
            raise AssertionError(
                f"operations[{index}].status must be one of {sorted(STATUSES)}"
            )
        owning_issue = operation.get("owning_issue")
        if owning_issue is not None and not isinstance(owning_issue, int):
            raise AssertionError(
                f"operations[{index}].owning_issue must be an integer or null"
            )
        consumers = operation.get("consumers")
        if not isinstance(consumers, list) or not all(
            isinstance(consumer, str) for consumer in consumers
        ):
            raise AssertionError(
                f"operations[{index}].consumers must be an array of strings"
            )
    return operations


def _inventory_set(operations: list[dict[str, Any]]) -> set[tuple[str, str]]:
    """Return lowercase ``(method, path)`` pairs from inventory entries."""
    return {(operation["method"].lower(), operation["path"]) for operation in operations}


def _runtime_set(operations: list[dict[str, Any]], runtime: str) -> set[tuple[str, str]]:
    """Return inventory operations declared for one runtime."""
    return {
        (operation["method"].lower(), operation["path"])
        for operation in operations
        if operation["runtime"] == runtime
    }


def _load_routes() -> list[_VercelRoute]:
    """Decode and validate ``vercel.json`` routing."""
    document = _load_json(VERCEL_CONFIG_PATH)
    raw_routes = document.get("routes")
    if not isinstance(raw_routes, list):
        raise AssertionError("vercel.json must define a routes array")
    routes: list[_VercelRoute] = []
    for raw_route in raw_routes:
        if not isinstance(raw_route, dict):
            raise AssertionError("vercel.json routes must be objects")
        src = raw_route.get("src")
        dest = raw_route.get("dest")
        raw_methods = raw_route.get("methods")
        methods: tuple[str, ...] = ()
        if raw_methods is not None:
            if not isinstance(raw_methods, list) or not all(
                isinstance(method, str) for method in raw_methods
            ):
                raise AssertionError("vercel.json route methods must be strings")
            methods = tuple(raw_methods)
        routes.append(
            _VercelRoute(
                src=src if isinstance(src, str) else None,
                dest=dest if isinstance(dest, str) else None,
                methods=methods,
            )
        )
    return routes


def _route_destination(method: str, path: str) -> str | None:
    """Resolve the first matching Vercel route, respecting HTTP method."""
    concrete = re.sub(r"\{[^}]+\}", "1", path)
    for route in _load_routes():
        if route.src is None or re.fullmatch(route.src, concrete) is None:
            continue
        if route.methods and method.upper() not in route.methods:
            continue
        return route.dest
    return None


def _call_pattern(path: str) -> re.Pattern[str]:
    """Return the full template-literal URL pattern for one API path.

    ``/api/v2/issues/{issue_id}/comicvine`` matches
    ``/v2/issues/${...}/comicvine`` but not the sibling ``/v2/issues/${...}``
    call. Matching the complete path, not just the prefix before the first
    parameter, keeps a caller of one operation from being attributed to
    another operation that shares that prefix.
    """
    tail = path.removeprefix("/api")
    parts: list[str] = []
    for segment in re.split(r"(\{[^}]+\})", tail):
        if not segment:
            continue
        if segment.startswith("{") and segment.endswith("}"):
            parts.append(r"\$\{[^}]+\}")
        else:
            parts.append(re.escape(segment))
    return re.compile("".join(parts) + r"(?![\w/])")


def _service_callers(path: str, method_name: str | None) -> set[str]:
    """Find frontend services that call one operation.

    A service either uses the literal template-literal URL or calls the
    generated ``nativeV2Client`` method by name (the generated SDK owns the URL).
    """
    path_marker = _call_pattern(path)
    method_marker = f".{method_name}(" if method_name is not None else ""
    callers: set[str] = set()
    for service in sorted(FRONTEND_SERVICES.glob("*.ts")):
        source = service.read_text(encoding="utf-8")
        if path_marker.search(source) or (method_marker and method_marker in source):
            callers.add(service.relative_to(ROOT).as_posix())
    return callers


def _native_method_names() -> dict[tuple[str, str], str]:
    """Map each native operation to its generated client method name."""
    document = _load_json(NATIVE_CONTRACT_PATH)
    paths = document.get("paths")
    if not isinstance(paths, dict):
        raise AssertionError("native contract must define paths")
    names: dict[tuple[str, str], str] = {}
    for path, raw_item in paths.items():
        if not isinstance(path, str) or not isinstance(raw_item, dict):
            raise AssertionError("native contract paths must map strings to objects")
        for method, raw_operation in raw_item.items():
            if not isinstance(raw_operation, dict):
                raise AssertionError(f"{method} {path} must be an object")
            operation_id = raw_operation.get("operationId")
            if not isinstance(operation_id, str):
                raise AssertionError(f"{method} {path} has no operationId")
            names[(method.lower(), path)] = _method_name(operation_id)
    return names


def test_inventory_covers_every_live_v2_operation() -> None:
    """The inventory, generated client schema and native contract agree."""
    operations = _inventory_operations()
    assert all(operation["path"].startswith("/api/v2/") for operation in operations)

    generated = {
        operation
        for operation in _openapi_operations(_load_json(GENERATED_SCHEMA_PATH))
        if operation[1].startswith("/api/v2/")
    }
    assert _inventory_set(operations) == generated, (
        "docs/api/v2-route-inventory.json is stale; regenerate "
        "frontend/src/generated/openapi.json and update the inventory together"
    )

    native = {
        operation
        for operation in _openapi_operations(_load_json(NATIVE_CONTRACT_PATH))
        if operation[1].startswith("/api/v2/")
    }
    assert _runtime_set(operations, NATIVE_RUNTIME) == native


def test_declared_runtime_matches_production_ingress() -> None:
    """Every native operation reaches a native ingress destination."""
    operations = _inventory_operations()
    for operation in operations:
        method = operation["method"]
        path = operation["path"]
        destination = _route_destination(method, path)
        if operation["runtime"] == NATIVE_RUNTIME:
            assert destination in NATIVE_DESTINATIONS, (
                f"{method} {path} is declared {NATIVE_RUNTIME} but vercel.json "
                f"routes it to {destination!r}"
            )
        else:
            assert destination not in NATIVE_DESTINATIONS, (
                f"{method} {path} is declared {PYTHON_RUNTIME} but vercel.json "
                f"routes it to native {destination!r}"
            )


def test_declared_consumers_are_the_real_service_callers() -> None:
    """The caller inventory exactly matches frontend service URL usage."""
    method_names = _native_method_names()
    for operation in _inventory_operations():
        declared = set(operation["consumers"])
        method_name = method_names.get((operation["method"].lower(), operation["path"]))
        actual = _service_callers(operation["path"], method_name)
        assert declared == actual, (
            f"consumer drift for {operation['method']} {operation['path']}: "
            f"declared {sorted(declared)}, found {sorted(actual)}"
        )


def test_python_transitional_operations_are_explicit() -> None:
    """A v2 path served by Python stays visible as transitional, not silently absent."""
    operations = _inventory_operations()
    python_paths = _runtime_set(operations, PYTHON_RUNTIME)
    assert ("get", "/api/v2/reading-boundaries/{thread_id}") in python_paths
    for operation in operations:
        if operation["runtime"] == PYTHON_RUNTIME:
            assert operation["status"] == "transitional"


def test_published_transitional_operations_are_not_marked_final() -> None:
    """Keep the #4335 removal queue explicit: Bootstrap and legacy Roll commands."""
    operations = _inventory_operations()
    transitional = {
        (operation["method"].lower(), operation["path"])
        for operation in operations
        if operation["status"] == "transitional"
    }
    assert transitional == {
        ("get", "/api/v2/reading-boundaries/{thread_id}"),
        ("get", "/api/v2/roll/bootstrap"),
        ("post", "/api/v2/reading-sessions"),
        ("post", "/api/v2/roll/dice-command"),
        ("post", "/api/v2/roll/offer"),
        ("post", "/api/v2/roll/reset"),
    }, (
        "The deployed transitional v2 operations changed. Update this set and "
        "the owning cutover evidence together; do not silently mark a legacy "
        "operation as final."
    )
