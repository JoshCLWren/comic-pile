"""Validate the checked-in Rust-derived ``/api/v2`` contract artifacts.

``native/contracts/*-v2.openapi.json`` is the canonical, machine-generated
representation of one native Rust v2 *target resource* surface. A checked-in
target contract must fail closed on the legacy shapes #4457 forbids:
colon-method / slash-action paths, unauthenticated operations, and missing
generated metadata.

``native/contracts/v2-runtime.openapi.json`` is the aggregate contract for every
*currently deployed* native v2 operation, including the public auth and Roll
command endpoints. Those deployed operations are compatibility-preserved as
they are, so the aggregate is checked for baseline validity, generated
operation ids, 2xx responses and explicit security declarations rather than the
future target-resource shape rule.

Reconciling the *live* route table, ``vercel.json`` ingress rewrites and Python
transitional handlers is the separate route-inventory step in
``tests/test_api_v2_contract_inventory.py``.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Final

REPO_ROOT: Final = Path(__file__).resolve().parents[1]
NATIVE_CONTRACTS: Final = REPO_ROOT / "native" / "contracts"
CONTRACT_GLOB: Final = "*-v2.openapi.json"
RUNTIME_CONTRACT: Final = NATIVE_CONTRACTS / "v2-runtime.openapi.json"
V2_PREFIX: Final = "/api/v2/"
# These browser-called operations intentionally retain their approved v1 wire
# paths while moving the implementation behind the same native Rust ingress.
_RUNTIME_LEGACY_PATHS: Final = frozenset(
    {
        "/api/metrics",
        "/api/v1/metrics",
        "/api/v1/identity-inbox",
        "/api/v1/identity-inbox/search/issues",
        "/api/v1/identity-inbox/{mapping_id}",
        "/api/v1/identity-inbox/{mapping_id}/confirm",
        "/api/v1/identity-inbox/{mapping_id}/defer",
        "/api/v1/identity-inbox/{mapping_id}/reject",
        "/api/v1/identity-inbox/{mapping_id}/skip",
        "/api/v1/continuity-rules/",
        "/api/v1/continuity-rules/{rule_id}",
        "/api/v1/dependencies/",
        "/api/v1/dependencies/blocked",
        "/api/v1/dependencies/{dependency_id}",
        "/api/v1/releases/",
        "/api/v1/releases/source",
        "/api/v1/releases/{release_id}",
        "/api/v1/releases/{release_id}/retract",
        "/api/v1/comicvine/series/{comicvine_volume_id}/import-status",
        "/api/v1/threads/{thread_id}/dependencies",
        "/api/v1/threads/{thread_id}/issue-dependencies",
        "/api/v1/threads/completed/threads",
        "/api/v1/catalog/series-mappings/commit",
    }
)

# Path segments that describe a verb-shaped action rather than a resource. The
# final v2 surface models these as resources (see #4335 Q1-Q44). Segments are
# compared after splitting hyphenated path tokens, so `bulk-mark-read` fails.
_ACTION_SEGMENTS: Final = frozenset(
    {
        "attach",
        "bulk",
        "confirm",
        "correct",
        "create",
        "delete",
        "fetch",
        "get",
        "import",
        "list",
        "mark",
        "migrate",
        "move",
        "offer",
        "rate",
        "refresh",
        "remove",
        "reorder",
        "replace",
        "reset",
        "revert",
        "search",
        "set",
        "skip",
        "undo",
        "update",
        "validate",
    }
)
_SUPPORTED_METHODS: Final = frozenset({"get", "post", "put", "patch", "delete"})
_BEARER_SECURITY: Final = [{"HTTPBearer": []}]

# Reviewed, compatibility-preserved command paths on the *deployed* v2 surface.
# A new verb-shaped v2 path must be either modeled as a resource or added here
# only after an explicit owner review; the exception set is also checked for
# stale entries.
_RUNTIME_COMMAND_PATHS: Final = frozenset(
    {
        "/api/v2/auth/refresh",
        "/api/v2/auth/reset-password",
        "/api/v2/roll/offer",
        "/api/v2/roll/reset",
        "/api/v1/identity-inbox/search/issues",
        "/api/v1/identity-inbox/{mapping_id}/confirm",
        "/api/v1/identity-inbox/{mapping_id}/defer",
        "/api/v1/identity-inbox/{mapping_id}/reject",
        "/api/v1/identity-inbox/{mapping_id}/skip",
        "/api/v1/comicvine/series/{comicvine_volume_id}/import-status",
    }
)


def _contract_paths() -> list[Path]:
    """Return the checked-in Rust v2 target contract files.

    Returns:
        Sorted contract paths; the guard fails rather than passing vacuously when
        none exist.
    """
    paths = sorted(NATIVE_CONTRACTS.glob(CONTRACT_GLOB))
    assert paths, f"no checked-in native v2 contracts matched {NATIVE_CONTRACTS}/{CONTRACT_GLOB}"
    return paths


def _load_document(path: Path) -> dict[str, object]:
    """Read one contract document.

    Args:
        path: Contract file to read.

    Returns:
        The parsed OpenAPI document as a string-keyed mapping.
    """
    document: dict[str, object] = json.loads(path.read_text(encoding="utf-8"))
    return document


def _object_mapping(value: object, *, label: str) -> dict[str, object]:
    """Narrow a JSON value to a string-keyed mapping.

    Args:
        value: JSON value to narrow.
        label: Human-readable location for the assertion message.

    Returns:
        The value as a mapping.
    """
    assert isinstance(value, dict), f"{label} must be a JSON object"
    return {str(key): item for key, item in value.items()}


def _action_segments(path: str) -> list[str]:
    """List the verb-shaped tokens in one OpenAPI path.

    Args:
        path: OpenAPI path template such as ``/api/v2/issues/{issue_id}``.

    Returns:
        Offending tokens, empty when the path is resource-shaped.
    """
    offending: list[str] = []
    for segment in path.split("/"):
        if not segment or segment.startswith("{"):
            continue
        if segment.startswith(":"):
            offending.append(segment)
            continue
        offending.extend(
            token
            for token in segment.split("-")
            if token.lower() in _ACTION_SEGMENTS
        )
    return offending


def _assert_baseline_contract(path: Path, document: dict[str, object]) -> dict[str, object]:
    """Assert OpenAPI 3.1 identity, component schemas and V2 paths."""
    version = document.get("openapi")
    assert isinstance(version, str) and version.startswith("3.1"), (
        f"{path.name}: expected an OpenAPI 3.1 document, found {version!r}"
    )
    info = _object_mapping(document.get("info"), label=f"{path.name} info")
    title = info.get("title")
    assert isinstance(title, str) and title, f"{path.name}: info.title is required"
    components = _object_mapping(
        document.get("components"),
        label=f"{path.name} components",
    )
    schemas = _object_mapping(
        components.get("schemas"),
        label=f"{path.name} components.schemas",
    )
    assert schemas, f"{path.name}: generated contract must declare component schemas"
    paths = _object_mapping(document.get("paths"), label=f"{path.name} paths")
    assert paths, f"{path.name}: contract must declare at least one operation"
    for raw_path in paths:
        assert raw_path.startswith(V2_PREFIX) or (
            (path == RUNTIME_CONTRACT and raw_path in _RUNTIME_LEGACY_PATHS)
            or (
                path.name == "threads-v2.openapi.json"
                and raw_path == "/api/v1/threads/completed/threads"
            )
        ), (
            f"{path.name}: {raw_path} is not under {V2_PREFIX}"
        )
    return paths


def _assert_generated_operation(
    path: Path,
    raw_path: str,
    method: str,
    raw_operation: object,
) -> dict[str, object]:
    """Assert one operation carries generated metadata and a 2xx response."""
    assert method in _SUPPORTED_METHODS, (
        f"{path.name}: {raw_path} declares unsupported method {method}"
    )
    operation = _object_mapping(
        raw_operation,
        label=f"{path.name} {method.upper()} {raw_path}",
    )
    operation_id = operation.get("operationId")
    assert isinstance(operation_id, str) and operation_id, (
        f"{path.name}: {method.upper()} {raw_path} needs a generated operationId"
    )
    responses = _object_mapping(
        operation.get("responses"),
        label=f"{path.name} {method.upper()} {raw_path} responses",
    )
    success = sorted(code for code in responses if code.startswith("2"))
    assert success, (
        f"{path.name}: {method.upper()} {raw_path} has no 2xx response"
    )
    return operation


def test_checked_in_native_v2_contracts_are_valid_openapi_documents() -> None:
    """Every checked-in Rust contract is OpenAPI 3.1 with component schemas."""
    for path in _contract_paths():
        _assert_baseline_contract(path, _load_document(path))
    _assert_baseline_contract(RUNTIME_CONTRACT, _load_document(RUNTIME_CONTRACT))


def test_native_dependency_response_preserves_python_schema_contract() -> None:
    """The same-path thread dependency response keeps Python field semantics."""
    native_document = _load_document(RUNTIME_CONTRACT)
    client_document = _load_document(REPO_ROOT / "frontend/src/generated/openapi.json")
    native_components = _object_mapping(native_document.get("components"), label="native components")
    client_components = _object_mapping(client_document.get("components"), label="client components")
    native_schemas = _object_mapping(native_components.get("schemas"), label="native schemas")
    client_schemas = _object_mapping(client_components.get("schemas"), label="client schemas")
    native = _object_mapping(native_schemas.get("DependencyResponse"), label="native dependency")
    python = _object_mapping(client_schemas.get("DependencyResponse"), label="Python dependency")
    native_fields = _object_mapping(native.get("properties"), label="native dependency fields")
    python_fields = _object_mapping(python.get("properties"), label="Python dependency fields")

    assert native_fields.keys() == python_fields.keys()
    assert native.get("required") == python.get("required") == ["id", "created_at"]
    native_created_at = _object_mapping(native_fields.get("created_at"), label="native created_at")
    python_created_at = _object_mapping(python_fields.get("created_at"), label="Python created_at")
    assert native_created_at.get("type") == python_created_at.get("type") == "string"
    assert native_created_at.get("format") == python_created_at.get("format") == "date-time"
    native_issue_level = _object_mapping(
        native_fields.get("is_issue_level"), label="native is_issue_level"
    )
    python_issue_level = _object_mapping(
        python_fields.get("is_issue_level"), label="Python is_issue_level"
    )
    assert native_issue_level.get("default") == python_issue_level.get("default") is True


def test_checked_in_native_v2_target_paths_are_resource_shaped_and_authenticated() -> None:
    """Future target resources stay resource-shaped and bearer-protected."""
    for path in _contract_paths():
        document = _load_document(path)
        paths = _assert_baseline_contract(path, document)
        for raw_path, raw_operations in sorted(paths.items()):
            offending = _action_segments(raw_path)
            assert offending == [], (
                f"{path.name}: {raw_path} uses action-shaped segment(s) {offending}; "
                "model the final v2 surface as resources (GET/POST collection, "
                "PATCH/DELETE resource)"
            )
            operations = _object_mapping(
                raw_operations,
                label=f"{path.name} {raw_path}",
            )
            for method, raw_operation in sorted(operations.items()):
                operation = _assert_generated_operation(
                    path, raw_path, method, raw_operation
                )
                assert operation.get("security") == _BEARER_SECURITY, (
                    f"{path.name}: {method.upper()} {raw_path} must require bearer auth"
                )


def test_runtime_contract_declares_every_deployed_operation_explicitly() -> None:
    """The aggregate preserves deployed public/authenticated security choices."""
    path = RUNTIME_CONTRACT
    document = _load_document(path)
    paths = _assert_baseline_contract(path, document)
    components = _object_mapping(
        document.get("components"), label=f"{path.name} components"
    )
    security_schemes = _object_mapping(
        components.get("securitySchemes", {}),
        label=f"{path.name} components.securitySchemes",
    )
    assert security_schemes.get("HTTPBearer") == {
        "type": "http",
        "scheme": "bearer",
    }, f"{path.name}: HTTPBearer security scheme is required"

    authenticated = 0
    public = 0
    for raw_path, raw_operations in sorted(paths.items()):
        offending = _action_segments(raw_path)
        if offending:
            assert raw_path in _RUNTIME_COMMAND_PATHS, (
                f"{path.name}: {raw_path} uses unreviewed action-shaped "
                f"segment(s) {offending}; model it as a resource or add an "
                "explicit reviewed command exception"
            )
        operations = _object_mapping(
            raw_operations,
            label=f"{path.name} {raw_path}",
        )
        for method, raw_operation in sorted(operations.items()):
            operation = _assert_generated_operation(
                path, raw_path, method, raw_operation
            )
            security = operation.get("security")
            if security is None:
                public += 1
            else:
                assert security == _BEARER_SECURITY, (
                    f"{path.name}: {method.upper()} {raw_path} must declare either "
                    "bearer security or no security at all"
                )
                authenticated += 1

    stale_exceptions = _RUNTIME_COMMAND_PATHS - set(paths)
    assert stale_exceptions == set(), (
        f"{path.name}: stale reviewed command path exceptions {sorted(stale_exceptions)}"
    )

    # The deployed v2 surface deliberately contains both public auth entry
    # points and bearer-protected resources; neither may become implicit.
    assert public > 0, f"{path.name}: expected public auth operations to stay public"
    assert authenticated > 0, (
        f"{path.name}: expected authenticated operations to stay bearer-protected"
    )
