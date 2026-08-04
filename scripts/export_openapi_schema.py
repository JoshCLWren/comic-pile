#!/usr/bin/env python3
"""Export ComicPile's OpenAPI schema deterministically for generated clients."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

DEFAULT_OUTPUT = Path("frontend/src/generated/openapi.json")


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
    """Export the application OpenAPI schema or verify generated output."""
    args = _parse_args()

    from app.main import app

    rendered = render_openapi_schema(app.openapi())
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
