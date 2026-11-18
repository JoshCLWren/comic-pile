"""Closure-gate contract for the #4848 continuity-rules Rust cutover.

Issue #4848 moves the five browser-called ``/api/v1/continuity-rules``
operations to the native Rust ingress behind the unchanged same-path wire
contract. The same-path Rust implementation merged in #4891; the Python
handler, its mount wiring and its exclusive helpers were retired in #5162 and
#5443. This module pins the post-cutover closure contract with static
repository checks only (no network or database access):

* ``vercel.json`` rewrites every browser-called METHOD/path pair to
  ``/api/native_roll.rs`` (never the Python catch-all, never a redirect to
  ``/api/v2``);
* both checked-in native OpenAPI contracts declare the five operations with
  bearer security and stable operationIds;
* the route fragment records the native Rust runtime, the ``target`` status
  and owning issue #4848;
* the retired Python handler, its router mount, its response DTO and the
  hand-written frontend service stay deleted, and the retirement fixture
  records the five operations;
* the generated frontend client keeps the unchanged same-path URLs;
* the Rust module stays registered in the native service; and
* the Python full-surface inventory no longer carries the retired operations
  (the post-#5162 retirement invariant enforced by the burndown generator).

The remaining acceptance gate — an authenticated production request per
operation executed by the Rust binary (or an explicit reviewer-approved
representative-sibling rationale) — cannot be produced by a static test and
must be recorded on issue #4848 before the issue is closed. This module
intentionally does not claim that proof.
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

OPERATION_IDS: Final = {
    ("GET", "/api/v1/continuity-rules/"): "continuity_rules_list",
    ("POST", "/api/v1/continuity-rules/"): "continuity_rules_create",
    ("DELETE", "/api/v1/continuity-rules/{rule_id}"): "continuity_rules_delete",
    ("GET", "/api/v1/continuity-rules/{rule_id}"): "continuity_rules_get",
    ("PUT", "/api/v1/continuity-rules/{rule_id}"): "continuity_rules_update",
}

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


def _contract_operations(contract_path: str) -> dict[tuple[str, str], dict[str, object]]:
    """Collect the five continuity-rules operations from one native contract.

    Args:
        contract_path: Path to the OpenAPI contract relative to the repository root.

    Returns:
        Mapping of (method, path) to the operation object.
    """
    contract = _load_json(contract_path)
    paths = _as_object(contract.get("paths"), f"{contract_path} paths")
    operations: dict[tuple[str, str], dict[str, object]] = {}
    for method, path_template in CONTINUITY_RULES_OPERATIONS:
        path_item = _as_object(paths.get(path_template), f"{contract_path} path {path_template}")
        operations[(method, path_template)] = _as_object(
            path_item.get(method.lower()),
            f"{contract_path} operation {method} {path_template}",
        )
    return operations


def test_vercel_ingress_rewrites_every_operation_to_native_rust() -> None:
    """Every browser-called METHOD/path pair rewrites to the Rust binary."""
    vercel = _load_json("vercel.json")
    routes = _as_list(vercel.get("routes"), "vercel.json routes")
    for method, path_template in CONTINUITY_RULES_OPERATIONS:
        probe = _probe_path(path_template)
        destinations = []
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
                destinations.append(dest)
        assert destinations, f"no vercel.json route matches {method} {probe}"
        assert set(destinations) == {NATIVE_INGRESS}, (
            f"{method} {probe} rewrites to {destinations}; expected only {NATIVE_INGRESS}"
        )


def test_route_fragment_records_native_rust_runtime_and_issue() -> None:
    """The fragment keeps the native Rust runtime declaration for #4848."""
    fragment = _load_json("docs/api/route-fragments/continuity-rules.json")
    defaults = _as_object(fragment.get("defaults"), "fragment defaults")
    assert defaults.get("runtime") == "native-rust"
    assert defaults.get("status") == "target"
    assert defaults.get("owning_issue") == 4848
    operations = _as_list(fragment.get("operations"), "fragment operations")
    by_key = {}
    for raw in operations:
        operation = _as_object(raw, "fragment operation")
        by_key[(operation.get("method"), operation.get("path"))] = operation
    assert set(by_key) == set(CONTINUITY_RULES_OPERATIONS)
    for key, operation in by_key.items():
        assert operation.get("bucket") == "v1_operations", key
        assert operation.get("dest") == NATIVE_INGRESS, key
        assert operation.get("exclude_from_inventory") is True, key


def test_native_runtime_contract_declares_five_authenticated_operations() -> None:
    """The checked-in native runtime OpenAPI contract covers the operations."""
    for (method, path_template), operation in _contract_operations(
        "native/contracts/v2-runtime.openapi.json"
    ).items():
        assert operation.get("operationId") == OPERATION_IDS[(method, path_template)]
        assert operation.get("security") == BEARER_SECURITY


def test_same_path_runtime_contract_declares_five_authenticated_operations() -> None:
    """The same-path runtime contract matches the native runtime contract."""
    for (method, path_template), operation in _contract_operations(
        "native/contracts/same-path-runtime.openapi.json"
    ).items():
        assert operation.get("operationId") == OPERATION_IDS[(method, path_template)]
        assert operation.get("security") == BEARER_SECURITY


def test_python_handler_mount_and_frontend_service_stay_deleted() -> None:
    """The retired Python surface must not be resurrected."""
    assert not (REPO_ROOT / "app/api/continuity_rule.py").exists()
    for relative_path in ("app/router_mounts.py", "app/api/dependency.py"):
        source = (REPO_ROOT / relative_path).read_text(encoding="utf-8")
        assert "continuity_rule" not in source, relative_path
        assert "continuity-rules" not in source, relative_path
    assert not (REPO_ROOT / "frontend/src/services/api-continuity-rules.ts").exists()


def test_response_dto_and_conversion_helpers_stay_deleted() -> None:
    """The Python response contract for the five operations stays retired."""
    schema_source = (REPO_ROOT / "app/schemas/continuity_rule.py").read_text(encoding="utf-8")
    assert "ContinuityRuleResponse" not in schema_source
    services_source = (REPO_ROOT / "app/services/continuity.py").read_text(encoding="utf-8")
    assert "ContinuityRuleResponse" not in services_source


def test_retired_handler_fixture_records_five_operations() -> None:
    """The canonical retirement guard pins the five retired operations."""
    fixture = _as_list(
        json.loads((REPO_ROOT / "tests/fixtures/retired-python-handlers.json").read_text()),
        "retired-python-handlers fixture",
    )
    retired = {
        (method, _as_object(entry, "fixture entry").get("path"))
        for entry in fixture
        for method in _as_list(_as_object(entry, "fixture entry").get("methods"), "methods")
        if _as_object(entry, "fixture entry").get("module") == "app.api.continuity_rule"
    }
    assert retired == set(CONTINUITY_RULES_OPERATIONS)


def test_generated_frontend_client_keeps_same_path_urls() -> None:
    """The generated client keeps the unchanged ``/v1/continuity-rules`` paths."""
    client = (REPO_ROOT / "frontend/src/generated/nativeV2Client.ts").read_text(encoding="utf-8")
    assert client.count("/v1/continuity-rules/") >= 5
    assert "/v2/continuity-rules" not in client
    openapi_ts = (REPO_ROOT / "frontend/src/generated/openapi.ts").read_text(encoding="utf-8")
    assert '"/api/v1/continuity-rules/"' in openapi_ts
    assert '"/api/v1/continuity-rules/{rule_id}"' in openapi_ts


def test_rust_module_registered_in_native_service() -> None:
    """The native service registers every operation on the same paths."""
    assert (REPO_ROOT / "native/roll-service/src/continuity_rules.rs").is_file()
    lib_source = (REPO_ROOT / "native/roll-service/src/lib.rs").read_text(encoding="utf-8")
    assert "pub mod continuity_rules;" in lib_source
    for handler in ("list", "create", "get", "update", "delete"):
        assert f"continuity_rules::{handler}" in lib_source, handler


def test_python_surface_inventory_excludes_retired_operations() -> None:
    """The generated full-surface inventory carries no continuity-rules ops."""
    inventory = _load_json("docs/api/v2-route-inventory.json")
    full_surface = _as_object(inventory.get("full_surface"), "inventory full_surface")
    for bucket in ("v1_operations", "unversioned_operations"):
        operations = _as_list(full_surface.get(bucket), f"inventory {bucket}")
        for raw in operations:
            operation = _as_object(raw, "inventory operation")
            path = str(operation.get("path", ""))
            assert not path.startswith("/api/v1/continuity-rules"), (bucket, path)
