#!/usr/bin/env python3
"""Export ComicPile's OpenAPI schema deterministically for generated clients."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any, Final

DEFAULT_OUTPUT = Path("frontend/src/generated/openapi.json")

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
    return path == "/api/v1" or path.startswith("/api/v1/")


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

    from app.main import app

    rendered = render_openapi_schema(prune_legacy_bare_paths(app.openapi()))
    if write_schema(args.output, rendered, check=args.check):
        action = "Verified" if args.check else "Wrote"
        print(f"{action} deterministic OpenAPI schema: {args.output}")
        return 0

    print(
        f"Generated OpenAPI schema is stale: {args.output}\n"
        "Run `python scripts/export_openapi_schema.py` and commit the result."
    )
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
