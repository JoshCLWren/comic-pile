"""Closure-gate contract for the #4848 continuity-rules Rust cutover.

Issue #4848 moves the five browser-called ``/api/v1/continuity-rules``
operations to the native Rust ingress behind the unchanged same-path wire
contract. The same-path implementation merged in PR #4891; the generated
route inventory now records the operations as shadowed by Rust.

The issue contract explicitly orders the Python cleanup *after* an
authenticated production request is proven to execute in the Rust binary.
Until that proof exists, the transitional Python handler must remain mounted
as the rollback path, and the ingress must keep targeting the native binary.
This module pins that contract with static repository checks only (no
network or database access):

* every browser-called METHOD/path pair in ``vercel.json`` rewrites to
  ``/api/native_roll.rs`` (never the Python catch-all, never a redirect to
  ``/api/v2``);
* the generated route inventory records the five operations as shadowed by
  Rust with the native ingress destination and the live frontend caller;
* the checked-in native runtime OpenAPI contract declares all five
  operations with bearer security;
* the frontend continuity-rules service still targets the unchanged
  ``/v1/continuity-rules`` paths; and
* the transitional Python handler stays mounted, and the Rust module stays
  registered, until the authenticated-production-proof gate is satisfied.
  The post-proof cleanup PR is expected to invert the final assertion with
  an explicit proof reference.
"""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Final

REPO_ROOT: Final = Path(__file__).resolve().parents[1]

CONTINUITY_RULES_OPERATIONS: Final = (
    ("GET", "/api/v1/continuity-rules/"),
    ("POST", "/api/v1/continuity-rules/"),
    ("DELETE", "/api/v1/continuity-rules/{rule_id}"),
    ("GET", "/api/v1/continuity-rules/{rule_id}"),
    ("PUT", "/api/v1/continuity-rules/{rule_id}"),
)

NATIVE_INGRESS: Final = "/api/native_roll.rs"
BEARER_SECURITY: Final = [{"HTTPBearer": []}]


def _load_json(relative_path: str) -> dict[str, object]:
    """Parse one repository JSON file into a string-keyed mapping.

    Args:
        relative_path: Path relative to the repository root.

    Returns:
        The parsed JSON object.
    """
    path = REPO_ROOT / relative_path
    document = json.loads(path.read_text(encoding="utf-8"))
    assert isinstance(document, dict), f"{relative_path} must contain a JSON object"
    return {str(key): value for key, value in document.items()}


def _as_object(value: object, label: str) -> dict[str, object]:
    """Narrow ``value`` to a string-keyed mapping.

    Args:
        value: JSON value to narrow.
        label: Human-readable location for the assertion message.

    Returns:
        The value as a string-keyed mapping.
    """
    assert isinstance(value, dict), f"{label} must be a JSON object"
    return {str(key): item for key, item in value.items()}


def _as_list(value: object, label: str) -> list[object]:
    """Narrow ``value`` to a list.

    Args:
        value: JSON value to narrow.
        label: Human-readable location for the assertion message.

    Returns:
        The value as a list.
    """
    assert isinstance(value, list), f"{label} must be a JSON array"
    return list(value)


def _probe_path(path_template: str) -> str:
    """Replace OpenAPI path parameters with a concrete single-segment value.

    Args:
        path_template: Path template such as ``/api/v1/continuity-rules/{rule_id}``.

    Returns:
        A concrete path that the Vercel ``[^/]+`` rewrites match.
    """
    return re.sub(r"\{[^}]+\}", "123", path_template)


def test_vercel_ingress_rewrites_every_operation_to_native_rust() -> None:
    """Every browser-called METHOD/path pair rewrites to the Rust binary."""
    vercel = _load_json("vercel.json")
    routes = _as_list(vercel.get("routes"), "vercel.json routes")
    for method, path_template in CONTINUITY_RULES_OPERATIONS:
        probe = _probe_path(path_template)
        matches = []
        for raw_route in routes:
            route = _as_object(raw_route, "vercel.json route")
            src = route.get("src")
            dest = route.get("dest")
            methods = route.get("methods")
            if not isinstance(src, str) or not isinstance(dest, str):
                continue
            method_list = methods if isinstance(methods, list) else []
            if method not in method_list:
                continue
            if re.fullmatch(src, probe):
                matches.append(dest)
        assert matches, f"no vercel.json route matches {method} {probe}"
        assert NATIVE_INGRESS in matches, (
            f"{method} {probe} does not rewrite to {NATIVE_INGRESS}; got {matches}"
        )


def test_route_inventory_records_operations_shadowed_by_rust() -> None:
    """The generated inventory keeps the five operations shadowed by Rust."""
    inventory = _load_json("docs/api/v2-route-inventory.json")
    full_surface = _as_object(inventory.get("full_surface"), "inventory full_surface")
    v1_operations = _as_list(full_surface.get("v1_operations"), "inventory v1_operations")
    entries = [_as_object(raw, "v1 operation") for raw in v1_operations]
    for method, path_template in CONTINUITY_RULES_OPERATIONS:
        matches = [
            entry
            for entry in entries
            if entry.get("method") == method and entry.get("path") == path_template
        ]
        assert len(matches) == 1, f"expected one inventory entry for {method} {path_template}"
        entry = matches[0]
        assert entry.get("burndown_status") == "shadowed by Rust"
        assert entry.get("ingress_destination") == NATIVE_INGRESS
        consumers = entry.get("consumers")
        assert isinstance(consumers, list) and "frontend/src/services/api-continuity-rules.ts" in (
            str(consumer) for consumer in consumers
        )


def test_native_runtime_contract_declares_five_authenticated_operations() -> None:
    """The checked-in native runtime OpenAPI contract covers the five operations."""
    contract = _load_json("native/contracts/v2-runtime.openapi.json")
    paths = _as_object(contract.get("paths"), "native runtime contract paths")
    for method, path_template in CONTINUITY_RULES_OPERATIONS:
        operations = _as_object(paths.get(path_template), f"contract path {path_template}")
        operation = _as_object(
            operations.get(method.lower()),
            f"contract operation {method} {path_template}",
        )
        operation_id = operation.get("operationId")
        assert isinstance(operation_id, str) and operation_id
        assert operation.get("security") == BEARER_SECURITY


def test_frontend_service_keeps_unchanged_v1_paths() -> None:
    """The live frontend caller still uses the unchanged same-path URLs."""
    source = (REPO_ROOT / "frontend/src/services/api-continuity-rules.ts").read_text(
        encoding="utf-8",
    )
    assert source.count("/v1/continuity-rules") >= 3
    assert "/v2/continuity-rules" not in source


def test_transitional_python_handler_remains_until_production_proof() -> None:
    """The rollback path stays mounted while proof is outstanding.

    Issue #4848 authorizes deleting the Python handler only after an
    authenticated production request is shown to execute in the Rust binary.
    The post-proof cleanup PR must invert this assertion and reference the
    recorded production evidence.
    """
    assert (REPO_ROOT / "app/api/continuity_rule.py").is_file()
    mounts = (REPO_ROOT / "app/router_mounts.py").read_text(encoding="utf-8")
    assert "continuity-rules" in mounts
    rust_module = REPO_ROOT / "native/roll-service/src/continuity_rules.rs"
    assert rust_module.is_file()
    lib_source = (REPO_ROOT / "native/roll-service/src/lib.rs").read_text(encoding="utf-8")
    assert "continuity_rules" in lib_source
