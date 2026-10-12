"""Select Chromium regression specs from the canonical E2E behavior inventory.

The canonical inventory (``docs/e2e-behavior-inventory.yaml``) is the coverage
source of truth for scheduled and manually dispatched Chromium regression runs
(issue #1483). This module maps a priority scope (``p0``, ``p1-p2``, ``all``)
to the spec files listed on covered behaviors, fails closed when a covered
behavior references a missing spec file, and emits a JSON selection manifest
that ``frontend/playwright.regression.config.ts`` consumes.

The selector never creates GitHub issues or labels; defect triage stays a
human/factory reconciliation step documented in
``docs/E2E_CHROMIUM_REGRESSION.md``.
"""

from __future__ import annotations

import argparse
import json
import sys
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

import yaml

REPO_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_INVENTORY = REPO_ROOT / "docs" / "e2e-behavior-inventory.yaml"
DEFAULT_SPEC_DIR = REPO_ROOT / "frontend" / "src" / "test"

MANIFEST_SCHEMA = "comic-pile.e2e-regression-selection.v1"

SCOPES: dict[str, frozenset[str]] = {
    "p0": frozenset({"P0"}),
    "p1-p2": frozenset({"P1", "P2"}),
    "all": frozenset({"P0", "P1", "P2"}),
}

VALID_PRIORITIES = frozenset({"P0", "P1", "P2"})
VALID_STATUSES = frozenset({"uncovered", "covered", "blocked"})


class InventoryError(RuntimeError):
    """Raised when the canonical inventory violates its own contract."""


@dataclass(frozen=True)
class Behavior:
    """One behavior entry from the canonical inventory."""

    scenario_id: str
    area: str
    description: str
    priority: str
    status: str
    specs: tuple[str, ...]


def _require_str(value: object, context: str) -> str:
    """Return ``value`` as a non-empty string or raise ``InventoryError``.

    Args:
        value: Raw YAML value expected to be a string.
        context: Human-readable location used in error messages.

    Returns:
        The validated string.

    Raises:
        InventoryError: If the value is not a non-empty string.
    """
    if not isinstance(value, str) or not value.strip():
        raise InventoryError(f"{context} must be a non-empty string")
    return value


def _parse_specs(value: object, context: str) -> tuple[str, ...]:
    """Parse an optional ``specs`` list from the inventory.

    Args:
        value: Raw YAML value for the ``specs`` field.
        context: Human-readable location used in error messages.

    Returns:
        The spec basenames as a tuple.

    Raises:
        InventoryError: If the value is not a list of non-empty strings.
    """
    if value is None:
        return ()
    if not isinstance(value, list):
        raise InventoryError(f"{context} must be a list of spec filenames")
    specs: list[str] = []
    for index, item in enumerate(value):
        specs.append(_require_str(item, f"{context}[{index}]"))
    return tuple(specs)


def load_inventory(path: Path) -> list[Behavior]:
    """Load and validate behaviors from the canonical inventory.

    Args:
        path: Path to the inventory YAML file.

    Returns:
        The parsed behaviors in file order.

    Raises:
        InventoryError: If the file is missing, malformed, or violates the
            documented field contract (including a ``covered`` behavior that
            does not list at least one spec file).
    """
    if not path.exists():
        raise InventoryError(f"inventory not found: {path}")
    loaded: object = yaml.safe_load(path.read_text(encoding="utf-8"))
    if not isinstance(loaded, dict):
        raise InventoryError(f"{path} must contain a YAML mapping at the top level")
    raw_behaviors = loaded.get("behaviors")
    if not isinstance(raw_behaviors, list) or not raw_behaviors:
        raise InventoryError(f"{path} must define a non-empty 'behaviors' list")

    behaviors: list[Behavior] = []
    seen_ids: set[str] = set()
    for index, entry in enumerate(raw_behaviors):
        context = f"{path} behaviors[{index}]"
        if not isinstance(entry, dict):
            raise InventoryError(f"{context} must be a mapping")
        scenario_id = _require_str(entry.get("id"), f"{context}.id")
        if scenario_id in seen_ids:
            raise InventoryError(f"duplicate scenario id {scenario_id}")
        seen_ids.add(scenario_id)
        priority = _require_str(entry.get("priority"), f"{context}.priority")
        if priority not in VALID_PRIORITIES:
            raise InventoryError(f"{context}.priority must be one of {sorted(VALID_PRIORITIES)}")
        status = _require_str(entry.get("status"), f"{context}.status")
        if status not in VALID_STATUSES:
            raise InventoryError(f"{context}.status must be one of {sorted(VALID_STATUSES)}")
        specs = _parse_specs(entry.get("specs"), f"{context}.specs")
        if status == "covered" and not specs:
            raise InventoryError(
                f"{context} is covered but lists no specs; coverage must name its owning spec files"
            )
        behaviors.append(
            Behavior(
                scenario_id=scenario_id,
                area=_require_str(entry.get("area"), f"{context}.area"),
                description=_require_str(entry.get("behavior"), f"{context}.behavior"),
                priority=priority,
                status=status,
                specs=specs,
            )
        )
    return behaviors


def _skip_reason(behavior: Behavior) -> str | None:
    """Return why a behavior is not selectable, or ``None`` when it is.

    Args:
        behavior: The inventory entry to classify.

    Returns:
        A skip reason for non-covered behaviors, otherwise ``None``.
    """
    if behavior.status == "covered":
        return None
    return f"status is {behavior.status}"


def select_scope(
    behaviors: list[Behavior],
    scope: str,
    spec_dir: Path,
) -> tuple[list[Behavior], list[dict[str, str]], list[str], list[str]]:
    """Resolve a priority scope to covered behaviors and spec files.

    Args:
        behaviors: All behaviors parsed from the inventory.
        scope: One of ``p0``, ``p1-p2``, or ``all``.
        spec_dir: Directory that must contain every selected spec file.

    Returns:
        A tuple of (selected behaviors, skipped entries, selected spec
        basenames, spec files present on disk but referenced by no inventory
        behavior).

    Raises:
        InventoryError: If the scope is unknown or a selected spec file is
            missing from ``spec_dir``.
    """
    if scope not in SCOPES:
        raise InventoryError(f"unknown scope {scope!r}; expected one of {sorted(SCOPES)}")
    priorities = SCOPES[scope]

    selected: list[Behavior] = []
    skipped: list[dict[str, str]] = []
    for behavior in behaviors:
        if behavior.priority not in priorities:
            continue
        reason = _skip_reason(behavior)
        if reason is not None:
            skipped.append(
                {
                    "id": behavior.scenario_id,
                    "priority": behavior.priority,
                    "status": behavior.status,
                    "reason": reason,
                }
            )
            continue
        selected.append(behavior)

    ordered_specs: list[str] = []
    seen: set[str] = set()
    for behavior in selected:
        for spec in behavior.specs:
            if spec not in seen:
                seen.add(spec)
                ordered_specs.append(spec)
            spec_path = spec_dir / spec
            if not spec_path.is_file():
                raise InventoryError(
                    f"covered behavior {behavior.scenario_id} references missing spec "
                    f"{spec} (expected {spec_path}); update the inventory or restore the spec"
                )

    referenced_by_inventory = {
        spec for behavior in behaviors for spec in behavior.specs
    }
    unmapped = sorted(
        path.name
        for path in sorted(spec_dir.glob("*.spec.ts"))
        if path.name not in referenced_by_inventory
    )
    return selected, skipped, ordered_specs, unmapped


def _display_path(path: Path) -> str:
    """Return a repo-relative path string when possible, else the full path.

    Args:
        path: Path to render for the manifest.

    Returns:
        The relative path under the repository root, or the absolute path.
    """
    try:
        return str(path.relative_to(REPO_ROOT))
    except ValueError:
        return str(path)


def build_manifest(
    scope: str,
    inventory_path: Path,
    spec_dir: Path,
    selected: list[Behavior],
    skipped: list[dict[str, str]],
    ordered_specs: list[str],
    unmapped: list[str],
) -> dict[str, object]:
    """Build the JSON selection manifest consumed by the Playwright config.

    Args:
        scope: The selected priority scope.
        inventory_path: Inventory path recorded for provenance.
        spec_dir: Spec directory the basenames resolve against.
        selected: Behaviors selected for the scope.
        skipped: In-scope behaviors excluded with a reason.
        ordered_specs: Deduplicated spec basenames to execute.
        unmapped: Spec files referenced by no inventory behavior.

    Returns:
        A JSON-serializable manifest dictionary.
    """
    return {
        "schema": MANIFEST_SCHEMA,
        "scope": scope,
        "generated_at": datetime.now(UTC).isoformat(),
        "inventory": _display_path(inventory_path),
        "spec_dir": _display_path(spec_dir),
        "behaviors": [
            {
                "id": behavior.scenario_id,
                "area": behavior.area,
                "behavior": behavior.description,
                "priority": behavior.priority,
                "status": behavior.status,
                "specs": list(behavior.specs),
            }
            for behavior in selected
        ],
        "specs": ordered_specs,
        "skipped_behaviors": skipped,
        "unmapped_specs": unmapped,
    }


def _build_parser() -> argparse.ArgumentParser:
    """Build the command-line argument parser.

    Returns:
        The configured parser.
    """
    parser = argparse.ArgumentParser(
        description="Select Chromium regression specs from the canonical E2E behavior inventory."
    )
    parser.add_argument(
        "--scope",
        default="p1-p2",
        choices=sorted(SCOPES),
        help="Priority scope to select (default: p1-p2).",
    )
    parser.add_argument(
        "--inventory",
        type=Path,
        default=DEFAULT_INVENTORY,
        help="Path to the canonical inventory YAML.",
    )
    parser.add_argument(
        "--spec-dir",
        type=Path,
        default=DEFAULT_SPEC_DIR,
        help="Directory containing Playwright spec files.",
    )
    parser.add_argument(
        "--output",
        type=Path,
        help="Write the manifest JSON to this path instead of stdout.",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    """Run the selector CLI.

    Args:
        argv: Argument list to parse; defaults to ``sys.argv[1:]``.

    Returns:
        Process exit code (0 on success, 2 on inventory errors).
    """
    args = _build_parser().parse_args(argv)
    try:
        behaviors = load_inventory(args.inventory)
        selected, skipped, ordered_specs, unmapped = select_scope(
            behaviors, args.scope, args.spec_dir
        )
        manifest = build_manifest(
            args.scope,
            args.inventory,
            args.spec_dir,
            selected,
            skipped,
            ordered_specs,
            unmapped,
        )
    except InventoryError as error:
        print(f"error: {error}", file=sys.stderr)
        return 2
    rendered = json.dumps(manifest, indent=2, sort_keys=True) + "\n"
    if args.output is not None:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(rendered, encoding="utf-8")
        print(f"selected {len(ordered_specs)} spec files for scope {args.scope} -> {args.output}")
    else:
        print(rendered, end="")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
