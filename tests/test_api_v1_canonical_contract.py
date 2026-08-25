"""Canonical /api/v1 contract verification for retained client APIs.

Part of issue #638 (Developer experience and frontend simplification) and the
#642 ``/api/v1`` normalization audit (#954). This test enforces the durable
acceptance criteria that the generated OpenAPI document:

* exposes every retained first-party client family under a canonical
  ``/api/v1`` route;
* contains no supported Collections surface (routes, schemas, or operations);
* has no duplicate operation IDs; and
* retains only an explicit, documented set of legacy ``/api`` aliases.

The check reads the committed generated schema rather than importing the
application, so it stays in the lightweight schema-validation tier and matches
exactly what the frontend client consumes. ``scripts/generate_openapi_types.py``
keeps this artifact current in CI.
"""

from __future__ import annotations

import json
from pathlib import Path

GENERATED_SCHEMA = (
    Path(__file__).resolve().parent.parent / "frontend/src/generated/openapi.json"
)


def _schema_candidates() -> list[Path]:
    """Candidate locations for the generated OpenAPI schema.

    Resolving relative to this test file works under normal pytest invocation,
    while the repository-root fallback supports atypical working directories.
    """
    return [
        GENERATED_SCHEMA,
        Path("frontend/src/generated/openapi.json"),
    ]

# Families intentionally exposed ONLY under bare ``/api`` because they are
# non-client tooling or administrative surfaces, never versioned client
# resources. Every other bare ``/api`` path must be a compatibility alias for a
# family that also has a canonical ``/api/v1`` route.
LEGACY_ONLY_TOOLING = frozenset({"ping"})

# Retained first-party client families that must expose a canonical
# ``/api/v1`` route. These are the durable product APIs, not tooling.
REQUIRED_V1_FAMILIES = frozenset(
    {
        "admin",
        "analytics",
        "auth",
        "bug-reports",
        "continuity",
        "continuity-plans",
        "continuity-rules",
        "debug",
        "dependencies",
        "issues",
        "metrics",
        "queue",
        "rate",
        "reading-order-groups",
        "releases",
        "roll",
        "sessions",
        "snooze",
        "threads",
        "undo",
    }
)


def _load_schema() -> dict:
    """Load the committed generated OpenAPI schema.

    Raises:
        FileNotFoundError: If the generated artifact is missing.
    """
    tried: list[Path] = []
    for candidate in _schema_candidates():
        tried.append(candidate)
        if candidate.exists():
            return json.loads(candidate.read_text(encoding="utf-8"))

    raise FileNotFoundError(
        "Generated OpenAPI schema missing. Tried: "
        f"{[str(p) for p in tried]}. "
        "Run `python scripts/generate_openapi_types.py`."
    )


def test_openapi_has_no_duplicate_operation_ids() -> None:
    """Every operation must expose a unique operationId."""
    schema = _load_schema()
    operation_ids: list[str] = []
    for methods in schema.get("paths", {}).values():
        for operation in methods.values():
            if isinstance(operation, dict) and "operationId" in operation:
                operation_ids.append(operation["operationId"])

    duplicates = {oid for oid in operation_ids if operation_ids.count(oid) > 1}
    assert not duplicates, f"Duplicate operationIds found: {sorted(duplicates)}"


def test_openapi_has_no_supported_collections_surface() -> None:
    """Collections were removed; no Collections route, schema, or operation."""
    schema = _load_schema()
    violations: list[str] = []

    for path in schema.get("paths", {}):
        if "collection" in path.lower():
            violations.append(f"path:{path}")

    for name in schema.get("components", {}).get("schemas", {}):
        if "collection" in name.lower():
            violations.append(f"schema:{name}")

    for methods in schema.get("paths", {}).values():
        for operation in methods.values():
            if isinstance(operation, dict):
                operation_id = operation.get("operationId", "")
                if "collection" in operation_id.lower():
                    violations.append(f"operation:{operation_id}")

    assert not violations, f"Collections surface detected: {violations}"


def test_retained_families_expose_canonical_v1_routes() -> None:
    """Each retained client family must have at least one /api/v1 path."""
    schema = _load_schema()
    v1_families: set[str] = set()
    for path in schema.get("paths", {}):
        if path.startswith("/api/v1/"):
            v1_families.add(path[len("/api/v1/") :].split("/")[0])

    missing = REQUIRED_V1_FAMILIES - v1_families
    assert not missing, (
        f"Retained families missing canonical /api/v1 routes: {sorted(missing)}"
    )


def test_legacy_api_aliases_are_explicit_allowlist() -> None:
    """Every bare /api alias must be a known compatibility or tooling route."""
    schema = _load_schema()
    v1_families: set[str] = set()
    for path in schema.get("paths", {}):
        if path.startswith("/api/v1/"):
            v1_families.add(path[len("/api/v1/") :].split("/")[0])

    allowed_legacy = v1_families | LEGACY_ONLY_TOOLING
    unexpected: list[str] = []
    for path in schema.get("paths", {}):
        if not path.startswith("/api/"):
            continue
        if path.startswith("/api/v1/"):
            continue
        segment = path[len("/api/") :].split("/")[0]
        if segment not in allowed_legacy:
            unexpected.append(path)

    assert not unexpected, (
        "Bare /api routes outside the documented legacy allowlist: "
        f"{unexpected}. Add a canonical /api/v1 route or extend "
        "LEGACY_ONLY_TOOLING."
    )
