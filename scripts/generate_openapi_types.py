#!/usr/bin/env python3
"""Generate deterministic TypeScript API types from ComicPile's OpenAPI schema."""

from __future__ import annotations

import argparse
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import Final

SCHEMA_OUTPUT: Final = Path("frontend/src/generated/openapi.json")
TYPES_OUTPUT: Final = Path("frontend/src/generated/openapi.ts")
GENERATOR_PACKAGE: Final = "openapi-typescript@7.10.1"


def generator_command(schema: Path, output: Path) -> list[str]:
    """Build the exact pinned generator command.

    Args:
        schema: OpenAPI JSON input path.
        output: Generated TypeScript output path.

    Returns:
        Command arguments suitable for ``subprocess.run``.
    """
    return [
        "pnpm",
        "dlx",
        GENERATOR_PACKAGE,
        str(schema),
        "--output",
        str(output),
    ]


def generate_types(schema: Path, output: Path) -> None:
    """Run the pinned maintained OpenAPI TypeScript generator.

    Args:
        schema: OpenAPI JSON input path.
        output: Generated TypeScript output path.
    """
    output.parent.mkdir(parents=True, exist_ok=True)
    subprocess.run(generator_command(schema, output), check=True)


def outputs_match(expected: Path, generated: Path) -> bool:
    """Compare checked-in and freshly generated TypeScript output.

    Args:
        expected: Checked-in generated TypeScript path.
        generated: Fresh temporary generated TypeScript path.

    Returns:
        True when both files exist and contain identical bytes.
    """
    return expected.exists() and expected.read_bytes() == generated.read_bytes()


def _export_schema(*, check: bool) -> None:
    command = [sys.executable, "scripts/export_openapi_schema.py"]
    if check:
        command.append("--check")
    subprocess.run(command, check=True)


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--schema", type=Path, default=SCHEMA_OUTPUT)
    parser.add_argument("--output", type=Path, default=TYPES_OUTPUT)
    parser.add_argument(
        "--check",
        action="store_true",
        help="fail when the checked-in schema or TypeScript output is stale",
    )
    return parser.parse_args()


def main() -> int:
    """Generate checked-in API artifacts or verify that both remain current."""
    args = _parse_args()
    using_default_schema = args.schema == SCHEMA_OUTPUT

    if using_default_schema:
        _export_schema(check=args.check)

    if not args.check:
        generate_types(args.schema, args.output)
        print(
            f"Generated TypeScript API types with {GENERATOR_PACKAGE}: {args.output}"
        )
        return 0

    with tempfile.TemporaryDirectory(prefix="comic-pile-openapi-") as temp_dir:
        generated = Path(temp_dir) / args.output.name
        generate_types(args.schema, generated)
        if outputs_match(args.output, generated):
            print(f"Verified generated TypeScript API types: {args.output}")
            return 0

    print(
        f"Generated TypeScript API types are stale: {args.output}\n"
        "Run `python scripts/generate_openapi_types.py` and commit both generated artifacts."
    )
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
