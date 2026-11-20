"""Tests for the inventory-driven Chromium regression selector (issue #1483).

The selector is the bridge between the canonical behavior inventory and the
scheduled Chromium regression run, so these tests pin its scope filtering,
fail-closed behavior on inventory drift, manifest shape, and CLI contract.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest
import yaml

from scripts.e2e_regression_select import (
    DEFAULT_INVENTORY,
    MANIFEST_SCHEMA,
    InventoryError,
    load_inventory,
    main,
    select_scope,
)

REPO_ROOT = Path(__file__).resolve().parents[1]
SPEC_DIR = REPO_ROOT / "frontend" / "src" / "test"


def _entry(
    scenario_id: str,
    priority: str,
    status: str = "covered",
    specs: list[str] | None = None,
    area: str = "roll",
    description: str = "A behavior",
) -> dict[str, Any]:
    """Build one inventory behavior mapping for fixture files."""
    entry: dict[str, Any] = {
        "id": scenario_id,
        "area": area,
        "behavior": description,
        "priority": priority,
        "status": status,
    }
    if specs is not None:
        entry["specs"] = specs
    return entry


def _write_inventory(path: Path, behaviors: list[dict[str, Any]]) -> Path:
    """Write a fixture inventory YAML file and return its path."""
    path.write_text(
        yaml.safe_dump({"behaviors": behaviors}, sort_keys=False),
        encoding="utf-8",
    )
    return path


def _touch_specs(spec_dir: Path, *names: str) -> None:
    """Create empty spec files inside ``spec_dir``."""
    spec_dir.mkdir(parents=True, exist_ok=True)
    for name in names:
        (spec_dir / name).write_text("export {}\n", encoding="utf-8")


def test_real_inventory_loads_and_selects_default_scope() -> None:
    """The shipped inventory must load and yield an executable p1-p2 selection."""
    behaviors = load_inventory(DEFAULT_INVENTORY)
    assert behaviors
    selected, skipped, specs, unmapped = select_scope(behaviors, "p1-p2", SPEC_DIR)
    assert selected
    assert all(behavior.priority in {"P1", "P2"} for behavior in selected)
    assert all(behavior.status == "covered" for behavior in selected)
    assert skipped == []
    assert specs
    assert all((SPEC_DIR / spec).is_file() for spec in specs)
    # production-performance.spec.ts runs under its own perf config, not here.
    assert "production-performance.spec.ts" not in specs
    assert "production-performance.spec.ts" in unmapped


@pytest.mark.parametrize(
    ("scope", "expected_ids"),
    [
        ("p0", {"P0-ONLY"}),
        ("p1-p2", {"P1-ONE", "P2-TWO"}),
        ("all", {"P0-ONLY", "P1-ONE", "P2-TWO"}),
    ],
)
def test_scope_filters_priorities(
    tmp_path: Path,
    scope: str,
    expected_ids: set[str],
) -> None:
    """Each scope selects exactly the covered behaviors at its priorities."""
    _touch_specs(tmp_path / "specs", "a.spec.ts", "b.spec.ts", "c.spec.ts")
    inventory = _write_inventory(
        tmp_path / "inventory.yaml",
        [
            _entry("P0-ONLY", "P0", specs=["a.spec.ts"]),
            _entry("P1-ONE", "P1", specs=["b.spec.ts"]),
            _entry("P2-TWO", "P2", specs=["c.spec.ts"]),
        ],
    )
    behaviors = load_inventory(inventory)
    selected, _skipped, specs, _unmapped = select_scope(behaviors, scope, tmp_path / "specs")
    assert {behavior.scenario_id for behavior in selected} == expected_ids
    assert len(specs) == len(expected_ids)


def test_missing_spec_file_fails_selection(tmp_path: Path) -> None:
    """A covered behavior referencing a missing spec must fail closed."""
    inventory = _write_inventory(
        tmp_path / "inventory.yaml",
        [_entry("ROLL-001", "P1", specs=["ghost.spec.ts"])],
    )
    behaviors = load_inventory(inventory)
    with pytest.raises(InventoryError, match="missing spec ghost.spec.ts"):
        select_scope(behaviors, "p1-p2", tmp_path / "specs")


def test_covered_behavior_without_specs_fails_load(tmp_path: Path) -> None:
    """Covered status without owning specs violates the inventory contract."""
    inventory = _write_inventory(
        tmp_path / "inventory.yaml",
        [_entry("ROLL-001", "P1", status="covered", specs=None)],
    )
    with pytest.raises(InventoryError, match="lists no specs"):
        load_inventory(inventory)


def test_duplicate_scenario_ids_fail_load(tmp_path: Path) -> None:
    """Scenario IDs are ownership boundaries and must stay unique."""
    inventory = _write_inventory(
        tmp_path / "inventory.yaml",
        [
            _entry("ROLL-001", "P1", specs=["a.spec.ts"]),
            _entry("ROLL-001", "P1", specs=["a.spec.ts"]),
        ],
    )
    with pytest.raises(InventoryError, match="duplicate scenario id"):
        load_inventory(inventory)


def test_unknown_scope_fails_selection(tmp_path: Path) -> None:
    """Unknown scopes are rejected instead of silently selecting nothing."""
    _touch_specs(tmp_path / "specs", "a.spec.ts")
    inventory = _write_inventory(
        tmp_path / "inventory.yaml",
        [_entry("ROLL-001", "P1", specs=["a.spec.ts"])],
    )
    behaviors = load_inventory(inventory)
    with pytest.raises(InventoryError, match="unknown scope"):
        select_scope(behaviors, "p2", tmp_path / "specs")


def test_non_covered_behaviors_are_reported_as_skipped(tmp_path: Path) -> None:
    """Uncovered and blocked in-scope behaviors surface with an explicit reason."""
    _touch_specs(tmp_path / "specs", "a.spec.ts")
    inventory = _write_inventory(
        tmp_path / "inventory.yaml",
        [
            _entry("P1-COVERED", "P1", specs=["a.spec.ts"]),
            _entry("P1-OPEN", "P1", status="uncovered", specs=None),
            _entry("P1-BLOCKED", "P1", status="blocked", specs=None),
        ],
    )
    behaviors = load_inventory(inventory)
    _selected, skipped, _specs, _unmapped = select_scope(behaviors, "p1-p2", tmp_path / "specs")
    assert [(entry["id"], entry["status"]) for entry in skipped] == [
        ("P1-OPEN", "uncovered"),
        ("P1-BLOCKED", "blocked"),
    ]


def test_unreferenced_spec_files_are_reported_unmapped(tmp_path: Path) -> None:
    """Spec files absent from the inventory stay visible for currency work."""
    _touch_specs(tmp_path / "specs", "mapped.spec.ts", "orphan.spec.ts")
    inventory = _write_inventory(
        tmp_path / "inventory.yaml",
        [_entry("ROLL-001", "P1", specs=["mapped.spec.ts"])],
    )
    behaviors = load_inventory(inventory)
    _selected, _skipped, specs, unmapped = select_scope(
        behaviors, "p1-p2", tmp_path / "specs"
    )
    assert specs == ["mapped.spec.ts"]
    assert unmapped == ["orphan.spec.ts"]


def test_cli_writes_manifest(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    """The CLI writes a schema-tagged manifest file and exits 0."""
    _touch_specs(tmp_path / "specs", "a.spec.ts")
    inventory = _write_inventory(
        tmp_path / "inventory.yaml",
        [_entry("ROLL-001", "P1", specs=["a.spec.ts"])],
    )
    output = tmp_path / "out" / "selection.json"
    exit_code = main(
        [
            "--scope",
            "p1-p2",
            "--inventory",
            str(inventory),
            "--spec-dir",
            str(tmp_path / "specs"),
            "--output",
            str(output),
        ]
    )
    assert exit_code == 0
    manifest = json.loads(output.read_text(encoding="utf-8"))
    assert manifest["schema"] == MANIFEST_SCHEMA
    assert manifest["scope"] == "p1-p2"
    assert manifest["specs"] == ["a.spec.ts"]
    assert manifest["behaviors"][0]["id"] == "ROLL-001"
    assert "selected 1 spec files" in capsys.readouterr().out


def test_cli_returns_2_on_inventory_error(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    """Inventory contract violations exit 2 with a readable error."""
    inventory = _write_inventory(
        tmp_path / "inventory.yaml",
        [_entry("ROLL-001", "P1", status="covered", specs=None)],
    )
    exit_code = main(
        [
            "--inventory",
            str(inventory),
            "--spec-dir",
            str(tmp_path / "specs"),
        ]
    )
    assert exit_code == 2
    assert "lists no specs" in capsys.readouterr().err
