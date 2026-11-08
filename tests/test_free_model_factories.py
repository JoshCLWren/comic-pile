"""Tests for the free-model factory's explicit retirement policy."""

import json
from pathlib import Path


def test_unusable_models_are_locked_out_of_the_factory_roster() -> None:
    """Retirement removes scheduling capacity without erasing historical evidence."""
    roster = Path(".github/free-model-factories.tsv").read_text()
    lock = json.loads(Path(".github/factory-expected-workers.json").read_text())
    retired = {48, 55, 74, 87, 88, 89, 90}
    assert retired.isdisjoint(lock["expected_workers"])
    assert retired.issubset(lock["retired_workers"])
    retired_models = {
        "codestral-latest",
        "nemotron-3-nano:30b",
        "deepseek-v4.1-flash-free",
    }
    assert retired_models.issubset(lock["retired_models"])
    active = {
        int(line.split("\t", 1)[0])
        for line in roster.splitlines()
        if line and not line.startswith("#")
    }
    assert retired.isdisjoint(active)
    assert "mistral-small" not in roster


def test_second_glm_lane_reuses_free_pin_with_half_hour_offset() -> None:
    """New capacity uses a fresh identity and the existing free provider/key."""
    rows = {
        fields[0]: fields
        for line in Path('.github/free-model-factories.tsv').read_text().splitlines()
        if line and not line.startswith('#')
        for fields in [line.split('\t')]
    }
    original, duplicate = rows['54'], rows['97']
    assert duplicate[1:3] == original[1:3] == ['z-ai', 'glm-4.5-flash']
    assert (int(duplicate[3]) - int(original[3])) % 60 == 30
    lock = json.loads(Path('.github/factory-expected-workers.json').read_text())
    assert 97 in lock['expected_workers'] and 97 not in lock['retired_workers']
