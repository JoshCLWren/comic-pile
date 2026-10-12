#!/usr/bin/env python3
"""Phase 0 strict-mypy inventory generator.

Runs strict mypy against the intended Python surface, parses the machine-readable
output, and emits a grouped inventory (module/package, error code, coherent
error family, approximate count, and whether the work is local typing cleanup
versus a real design/interface problem).

The inventory is the evidence artifact for generating bounded Phase 1+ migration
child issues. It is produced by running the same mypy invocation that the
repository gate uses, so the counts are reproducible.
"""

from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
from dataclasses import dataclass, field
from pathlib import Path

# Canonical strict-mypy invocation used by the repository gate and by this
# inventory generator. The gate runs the same command so the baseline is
# reproducible rather than drifting with tool versions.
MYPY_COMMAND = ["mypy", "--strict", "--no-error-summary", "--show-error-codes"]


@dataclass(frozen=True)
class MypyError:
    """One parsed mypy error line."""

    path: str
    line: int
    code: str
    message: str


# Coherent error families that map to reviewable semantic work. Each family
# groups one or more mypy error codes under a single migration theme so child
# issues are "reviewable semantic work" rather than one issue per checker
# complaint (issue #3250, required work item 4).
ERROR_FAMILIES: dict[str, frozenset[str]] = {
    "missing-annotations": frozenset(
        {
            "no-untyped-def",
            "no-untyped-call",
            "var-annotated",
            "type-arg",
        }
    ),
    "any-escapes": frozenset(
        {
            "no-any-return",
            "no-any-explicit",
            "no-any-expr",
        }
    ),
    "narrowing-compatibility": frozenset(
        {
            "arg-type",
            "call-arg",
            "assignment",
            "index",
            "operator",
            "list-item",
            "comparison-overlap",
            "return-value",
            "bool",
            "str",
            "int",
            "object",
            "misc",
        }
    ),
    "attribute-and-name-resolution": frozenset(
        {
            "attr-defined",
            "union-attr",
            "name-defined",
            "module-attr",
        }
    ),
    "import-and-stub-boundary": frozenset(
        {
            "import-not-found",
            "import-untyped",
            "import",
            "no-redef",
            "type-var",
        }
    ),
    "overload-and-call-signature": frozenset({"call-overload", "overload-overlap"}),
}


def error_family(code: str) -> str:
    """Return the coherent error family for a mypy error code.

    Args:
        code: Mypy error code (e.g. ``arg-type``).

    Returns:
        The family name, or ``other`` when no family is registered.
    """
    for family, codes in ERROR_FAMILIES.items():
        if code in codes:
            return family
    return "other"


# Codes that point at a genuine interface or design problem rather than a
# local typing cleanup. These become dependency issues rather than migration
# tickets (issue #3250, required work item 4).
DESIGN_PROBLEM_CODES: frozenset[str] = frozenset(
    {
        "call-overload",
        "assignment",
        "arg-type",
        "call-arg",
        "comparison-overlap",
        "overload-overlap",
    }
)


def is_design_problem(code: str, message: str) -> bool:
    """Return whether an error reflects a design/interface problem.

    Args:
        code: Mypy error code.
        message: Mypy error message text.

    Returns:
        True when the error indicates a real interface mismatch rather than a
        local typing cleanup.
    """
    if code in DESIGN_PROBLEM_CODES:
        return True
    return "incompatible" in message.lower() and code in {
        "assignment",
        "arg-type",
        "call-arg",
    }


ERROR_LINE_RE = re.compile(
    r"^(?P<path>.+?):(?P<line>\d+):?\s*error:\s*(?P<message>.*?)(?:\s*\[(?P<code>[a-z-]+)\])?$"
)


def parse_mypy_output(text: str) -> list[MypyError]:
    """Parse mypy's default text output into structured errors.

    Args:
        text: Raw mypy stdout/stderr text.

    Returns:
        Parsed errors in the order mypy emitted them.
    """
    errors: list[MypyError] = []
    for raw_line in text.splitlines():
        line = raw_line.rstrip()
        if not line or line.startswith("Found ") or line.startswith("Success"):
            continue
        match = ERROR_LINE_RE.match(line)
        if not match:
            continue
        errors.append(
            MypyError(
                path=match.group("path"),
                line=int(match.group("line")),
                code=match.group("code") or "no-code",
                message=match.group("message").strip(),
            )
        )
    return errors


def run_mypy(targets: list[str]) -> list[MypyError]:
    """Run strict mypy against ``targets`` and parse the output.

    Args:
        targets: Filesystem paths passed to mypy.

    Returns:
        Parsed errors. The mypy exit code is ignored so the inventory reflects
        the full error surface even when it is non-zero.
    """
    completed = subprocess.run(
        [*MYPY_COMMAND, *targets],
        check=False,
        capture_output=True,
        text=True,
    )
    return parse_mypy_output(completed.stdout + "\n" + completed.stderr)


def package_of(path: str) -> str:
    """Return the package scope for a source path.

    Args:
        path: Repository-relative source path.

    Returns:
        The nearest package directory (``app`` or ``app/services``), or the
        bare top-level directory when the file lives directly under it.
    """
    parts = Path(path).parts
    if len(parts) >= 2 and parts[0] in {"app", "comic_pile", "tests", "scripts"}:
        return ".".join(parts[:2])
    return parts[0] if parts else path


@dataclass
class InventoryRow:
    """One aggregated inventory cell."""

    module: str
    code: str
    family: str
    count: int
    design_problem: bool


def build_inventory(errors: list[MypyError]) -> list[InventoryRow]:
    """Aggregate parsed errors into grouped inventory rows.

    Args:
        errors: Parsed mypy errors.

    Returns:
        Inventory rows sorted by module, then error code.
    """
    counts: dict[tuple[str, str, bool], int] = {}
    for error in errors:
        design = is_design_problem(error.code, error.message)
        key = (package_of(error.path), error.code, design)
        counts[key] = counts.get(key, 0) + 1

    rows = [
        InventoryRow(
            module=module,
            code=code,
            family=error_family(code),
            count=count,
            design_problem=design,
        )
        for (module, code, design), count in sorted(counts.items())
    ]
    return rows


def render_markdown(rows: list[InventoryRow]) -> str:
    """Render inventory rows as a Markdown table.

    Args:
        rows: Aggregated inventory rows.

    Returns:
        Markdown document body.
    """
    lines = [
        "# Strict mypy Phase 0 baseline inventory",
        "",
        f"Generated by `scripts/generate_mypy_inventory.py` running "
        f"`{' '.join(MYPY_COMMAND)}`.",
        "",
        "Each row is one (module/package, error code) cell. `Design problem` "
        "marks errors that reflect a real interface mismatch and should become "
        "a dependency issue rather than a local typing cleanup ticket.",
        "",
        "| Module/package | Error code | Error family | Count | Design problem |",
        "| --- | --- | --- | --- | --- |",
    ]
    for row in rows:
        design = "yes" if row.design_problem else "no"
        lines.append(
            f"| `{row.module}` | `{row.code}` | `{row.family}` | "
            f"{row.count} | {design} |"
        )
    lines.append("")
    return "\n".join(lines)


def main() -> int:
    """Entry point: run mypy, aggregate, and write the inventory."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--target",
        action="append",
        default=[],
        help="Mypy target path (repeatable). Defaults to the production surface.",
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=Path("docs/MYPHASE0_INVENTORY.md"),
        help="Where to write the Markdown inventory.",
    )
    parser.add_argument(
        "--json",
        type=Path,
        default=None,
        help="Optional path to also write a machine-readable JSON inventory.",
    )
    args = parser.parse_args()

    targets = args.target or ["app", "comic_pile"]
    errors = run_mypy(targets)
    rows = build_inventory(errors)

    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(render_markdown(rows), encoding="utf-8")

    if args.json is not None:
        payload = {
            "command": MYPY_COMMAND,
            "targets": targets,
            "total_errors": len(errors),
            "rows": [
                {
                    "module": row.module,
                    "code": row.code,
                    "family": row.family,
                    "count": row.count,
                    "design_problem": row.design_problem,
                }
                for row in rows
            ],
        }
        args.json.parent.mkdir(parents=True, exist_ok=True)
        args.json.write_text(
            json.dumps(payload, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )

    print(f"Wrote {len(errors)} errors across {len(rows)} cells to {args.output}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
