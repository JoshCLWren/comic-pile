"""Validation tests for the canonical E2E behavior inventory."""

import os

import yaml


def test_behavior_inventory_file_exists() -> None:
    """The canonical behavior inventory YAML file must exist in docs/."""
    path = os.path.join("docs", "e2e-behavior-inventory.yaml")
    assert os.path.isfile(path), "behavior inventory file missing"


def test_behavior_inventory_structure() -> None:
    """Every inventory entry must have a stable ID, area, description, priority, and status."""
    with open(os.path.join("docs", "e2e-behavior-inventory.yaml"), encoding="utf-8") as f:
        data = yaml.safe_load(f)
    assert isinstance(data, list), "inventory should be a list"
    required_keys = {"id", "area", "description", "priority", "status"}
    for entry in data:
        assert isinstance(entry, dict), "each entry must be a dict"
        assert required_keys.issubset(entry.keys()), f"entry missing keys: {entry}"
        assert entry["status"] in {"uncovered", "covered", "blocked"}, (
            f"invalid status {entry['status']}"
        )
        assert entry["priority"] in {"P0", "P1", "P2"}, (
            f"invalid priority {entry['priority']}"
        )
    assert len(data) >= 8, "inventory should contain at least 8 entries"
