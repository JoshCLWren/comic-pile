"""Focused validation for the canonical E2E behavior inventory.

This test guards the contract of ``docs/e2e-behavior-inventory.yaml`` without
adding any Playwright/Chromium coverage (that work belongs to #1480). It
ensures the inventory stays a valid, unique, and complete source of truth.

Since issue #1483 the inventory is also the coverage source of truth for the
scheduled Chromium regression selector, so covered behaviors must name the
spec files that actually own them.
"""

from pathlib import Path

import yaml

INVENTORY_PATH = Path("docs/e2e-behavior-inventory.yaml")
SPEC_DIR = Path("frontend/src/test")

VALID_PRIORITIES = {"P0", "P1", "P2"}
VALID_STATUSES = {"uncovered", "covered", "blocked"}

# Areas that must have at least one P0 behavior per the #1479 acceptance contract.
REQUIRED_P0_AREAS = {
    "auth",
    "queue",
    "roll",
    "rate",
    "snooze",
    "thread",
    "dep",
    "order",
    "mobile",
}


def _load_inventory() -> dict:
    """Load and parse the canonical behavior inventory YAML."""
    raw = INVENTORY_PATH.read_text(encoding="utf-8")
    return yaml.safe_load(raw)


def test_inventory_file_exists_and_parses() -> None:
    """The canonical inventory must exist and be valid YAML."""
    assert INVENTORY_PATH.exists()
    data = _load_inventory()
    assert isinstance(data, dict)
    assert "behaviors" in data
    assert isinstance(data["behaviors"], list)
    assert data["behaviors"]


def test_every_behavior_has_required_fields() -> None:
    """Each entry must carry id, area, behavior, priority, and status."""
    data = _load_inventory()
    for entry in data["behaviors"]:
        assert isinstance(entry, dict)
        for field in ("id", "area", "behavior", "priority", "status"):
            assert field in entry, f"missing {field} in {entry.get('id', '?')}"
        assert entry["behavior"].strip()


def test_ids_are_unique_and_stable_formatted() -> None:
    """Scenario IDs are the ownership boundary, so they must be unique."""
    data = _load_inventory()
    seen: set[str] = set()
    for entry in data["behaviors"]:
        scenario_id = entry["id"]
        assert scenario_id not in seen, f"duplicate scenario id {scenario_id}"
        seen.add(scenario_id)
        assert "-" in scenario_id, f"id {scenario_id} is not area-scoped"


def test_priority_and_status_values_are_valid() -> None:
    """Priority and status enums must stay within the documented contract."""
    data = _load_inventory()
    for entry in data["behaviors"]:
        assert entry["priority"] in VALID_PRIORITIES
        assert entry["status"] in VALID_STATUSES


def test_required_p0_areas_are_represented() -> None:
    """All core P0 user journeys must be represented without obvious gaps."""
    data = _load_inventory()
    p0_areas: set[str] = set()
    for entry in data["behaviors"]:
        if entry["priority"] == "P0":
            p0_areas.add(entry["area"])
    missing = REQUIRED_P0_AREAS - p0_areas
    assert not missing, f"missing P0 coverage for areas: {sorted(missing)}"


def test_covered_behaviors_declare_owning_specs() -> None:
    """Every covered behavior must name at least one owning spec file."""
    data = _load_inventory()
    for entry in data["behaviors"]:
        if entry["status"] != "covered":
            continue
        specs = entry.get("specs")
        assert isinstance(specs, list) and specs, (
            f"{entry['id']} is covered but declares no specs; "
            "regression selection cannot run coverage it cannot resolve"
        )


def test_declared_specs_exist_as_playwright_spec_files() -> None:
    """Declared spec files must be well-formed basenames that exist on disk."""
    data = _load_inventory()
    for entry in data["behaviors"]:
        specs = entry.get("specs")
        if not specs:
            continue
        assert isinstance(specs, list)
        for spec in specs:
            assert isinstance(spec, str), f"{entry['id']} has a non-string spec entry"
            assert "/" not in spec and "\\" not in spec, (
                f"{entry['id']} spec {spec} must be a basename under {SPEC_DIR}"
            )
            assert spec.endswith(".spec.ts"), f"{entry['id']} spec {spec} is not a .spec.ts file"
            assert (SPEC_DIR / spec).exists(), (
                f"{entry['id']} references missing spec file {SPEC_DIR / spec}"
            )
