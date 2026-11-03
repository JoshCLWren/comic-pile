#!/usr/bin/env python3
"""Export ComicPile's OpenAPI schema deterministically for generated clients."""

from __future__ import annotations

import argparse
import copy
import difflib
import itertools
import json
from pathlib import Path
import sys
from typing import Any, Final

ROOT: Final = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

DEFAULT_OUTPUT = Path("frontend/src/generated/openapi.json")

# Canonical native Rust contract for every deployed ``/api/v2`` operation.
# ``scripts/generate_openapi_types.py`` regenerates it from the Rust router as a
# separate checked-in artifact; this exporter merges it into the single client
# document so the generated TypeScript types cover the real deployed runtime.
NATIVE_RUNTIME_CONTRACT: Final = ROOT / "native" / "contracts" / "v2-runtime.openapi.json"
SCHEMA_REF_PREFIX: Final = "#/components/schemas/"

# Bare ``/api`` domain paths retained in the client-facing schema. Everything
# else under bare ``/api`` is a legacy compatibility alias or non-client
# tooling that must not appear in the generated frontend client.
CLIENT_EXEMPT_BARE_PATHS: Final[frozenset[str]] = frozenset({"/api/ping"})


def is_client_schema_path(path: str) -> bool:
    """Decide whether one schema path belongs in the generated client surface.

    Args:
        path: OpenAPI path key such as ``/api/v1/threads/``.

    Returns:
        True for infrastructure paths outside ``/api``, the exempt bare ping
        path, and every canonical ``/api/v1`` route; False for all other bare
        ``/api`` legacy aliases and tooling routes.
    """
    if not path.startswith("/api/"):
        return True
    if path in CLIENT_EXEMPT_BARE_PATHS:
        return True
    return (
        path in {"/api/v1", "/api/v2"}
        or path.startswith(("/api/v1/", "/api/v2/"))
    )


def prune_legacy_bare_paths(schema: dict[str, Any]) -> dict[str, Any]:
    """Drop legacy unversioned ``/api`` domain paths from the client schema.

    Args:
        schema: OpenAPI document returned by FastAPI.

    Returns:
        The original document when every path already qualifies; otherwise a
        copy whose ``paths`` mapping keeps only client-facing paths.
    """
    paths = schema.get("paths")
    if not isinstance(paths, dict):
        return schema

    pruned_paths = {
        path: operations
        for path, operations in paths.items()
        if is_client_schema_path(path)
    }
    if len(pruned_paths) == len(paths):
        return schema

    return {**schema, "paths": pruned_paths}


def _rewrite_schema_refs(value: object, renames: dict[str, str]) -> object:
    """Return ``value`` with local schema references renamed.

    Args:
        value: Any JSON value from an OpenAPI document.
        renames: Mapping from the native schema name to its merged name.

    Returns:
        A deep-copied value where ``$ref`` entries under
        ``#/components/schemas/`` use the renamed schema where applicable.
    """
    if isinstance(value, dict):
        ref = value.get("$ref")
        rewritten = {
            key: _rewrite_schema_refs(item, renames)
            for key, item in value.items()
        }
        if (
            isinstance(ref, str)
            and ref.startswith(SCHEMA_REF_PREFIX)
            and ref[len(SCHEMA_REF_PREFIX) :] in renames
        ):
            rewritten["$ref"] = SCHEMA_REF_PREFIX + renames[ref[len(SCHEMA_REF_PREFIX) :]]
        return rewritten
    if isinstance(value, list):
        return [_rewrite_schema_refs(item, renames) for item in value]
    return copy.deepcopy(value)


def _unique_native_schema_name(
    name: str,
    python_names: set[str],
    native_names: set[str],
    assigned: set[str],
) -> str:
    """Choose a collision-free merged component name for one native schema."""
    candidate = f"Native{name}"
    suffix = 2
    while candidate in python_names or candidate in native_names or candidate in assigned:
        candidate = f"Native{name}{suffix}"
        suffix += 1
    return candidate


def native_schema_renames(
    python_schemas: dict[str, Any],
    native_schemas: dict[str, Any],
) -> dict[str, str]:
    """Determine which native component names must be disambiguated.

    A name is renamed only when the Python document already publishes a
    component with that name and the native declaration is not byte-identical.
    Schemas that merely reference a renamed schema are renamed too, so the
    native subtree never mixes a renamed component with a same-named Python
    component.

    Args:
        python_schemas: Component schemas from ``app.openapi()``.
        native_schemas: Component schemas from the native runtime contract.

    Returns:
        Mapping from native component name to its collision-free merged name.
    """
    renames: dict[str, str] = {}
    native_names = set(native_schemas)
    changed = True
    while changed:
        changed = False
        for name in sorted(native_schemas):
            if name in renames or name not in python_schemas:
                continue
            rewritten = _rewrite_schema_refs(native_schemas[name], renames)
            if rewritten == python_schemas[name]:
                continue
            renames[name] = _unique_native_schema_name(
                name,
                set(python_schemas),
                native_names,
                set(renames.values()),
            )
            changed = True
    return renames


def merge_native_runtime_contract(
    schema: dict[str, Any],
    native: dict[str, Any],
) -> dict[str, Any]:
    """Merge the native Rust v2 contract into the FastAPI document.

    The native operation replaces the FastAPI operation for the same
    ``(path, method)`` because ingress routes that request to Rust. Native
    component schemas are added when new, reused when byte-identical, and
    renamed with a ``Native`` prefix when a different Python schema already
    owns the name. References inside the native subtree are rewritten to the
    merged names so no operation silently points at a foreign schema.

    Args:
        schema: Document returned by ``app.openapi()``.
        native: Checked-in native runtime contract.

    Returns:
        A new document containing both the Python and native operations.

    Raises:
        ValueError: If a merged component name still conflicts with a
            different existing schema, which would indicate contract drift.
    """
    python_schemas = dict(schema.get("components", {}).get("schemas", {}))
    native_schemas = native.get("components", {}).get("schemas", {})
    renames = native_schema_renames(python_schemas, native_schemas)

    merged_schemas = dict(python_schemas)
    for name in sorted(native_schemas):
        merged_name = renames.get(name, name)
        rewritten = _rewrite_schema_refs(native_schemas[name], renames)
        existing = merged_schemas.get(merged_name)
        if existing is None:
            merged_schemas[merged_name] = rewritten
        elif existing != rewritten:
            raise ValueError(
                f"native schema {name!r} would overwrite Python schema "
                f"{merged_name!r} with different content"
            )

    merged_paths = copy.deepcopy(schema.get("paths", {}))
    for path, operations in native.get("paths", {}).items():
        target_operations = merged_paths.setdefault(path, {})
        for method, operation in operations.items():
            target_operations[method] = _rewrite_schema_refs(operation, renames)

    components = copy.deepcopy(schema.get("components", {}))
    components["schemas"] = merged_schemas
    native_security = native.get("components", {}).get("securitySchemes", {})
    security_schemes = components.setdefault("securitySchemes", {})
    for scheme_name, scheme in native_security.items():
        security_schemes.setdefault(scheme_name, copy.deepcopy(scheme))

    return {**schema, "paths": merged_paths, "components": components}


def load_native_runtime_contract(path: Path = NATIVE_RUNTIME_CONTRACT) -> dict[str, Any]:
    """Load the checked-in native Rust v2 OpenAPI contract."""
    return json.loads(path.read_text(encoding="utf-8"))


def client_openapi_schema() -> dict[str, Any]:
    """Build the single client-facing schema from Python plus native runtime."""
    from app.main import app

    return prune_legacy_bare_paths(
        merge_native_runtime_contract(app.openapi(), load_native_runtime_contract())
    )


def render_openapi_schema(schema: dict[str, Any]) -> str:
    """Render an OpenAPI document with stable ordering and formatting.

    Args:
        schema: OpenAPI document returned by FastAPI.

    Returns:
        Deterministic JSON text ending in one newline.
    """
    return json.dumps(schema, indent=2, sort_keys=True, ensure_ascii=False) + "\n"


def write_schema(output: Path, rendered: str, *, check: bool) -> bool:
    """Write generated schema text or verify that checked-in output is current.

    Args:
        output: Generated schema destination.
        rendered: Deterministically rendered schema text.
        check: Whether to compare without modifying the file.

    Returns:
        True when the destination is current or was written successfully.
    """
    if check:
        return output.exists() and output.read_text(encoding="utf-8") == rendered

    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(rendered, encoding="utf-8")
    return True


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument(
        "--check",
        action="store_true",
        help="fail when the checked-in schema differs instead of rewriting it",
    )
    return parser.parse_args()


def main() -> int:
    """Export the client-facing OpenAPI schema or verify generated output."""
    args = _parse_args()

    rendered = render_openapi_schema(client_openapi_schema())
    if write_schema(args.output, rendered, check=args.check):
        action = "Verified" if args.check else "Wrote"
        print(f"{action} deterministic OpenAPI schema: {args.output}")
        return 0

    if args.check and args.output.exists():
        existing = args.output.read_text(encoding="utf-8")
        diff = difflib.unified_diff(
            existing.splitlines(keepends=True),
            rendered.splitlines(keepends=True),
            fromfile="checked-in OpenAPI",
            tofile="generated OpenAPI",
        )
        print("".join(itertools.islice(diff, 90)))
    print(
        f"Generated OpenAPI schema is stale: {args.output}\n"
        "Run `python scripts/export_openapi_schema.py` and commit the result."
    )
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
