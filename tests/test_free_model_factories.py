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


def test_second_kilo_lane_shares_free_route_and_offsets_schedule() -> None:
    """The Kilo duplicate is another slot on the existing anonymous free route."""
    rows = {
        fields[0]: fields
        for line in Path('.github/free-model-factories.tsv').read_text().splitlines()
        if line and not line.startswith('#')
        for fields in [line.split('\t')]
    }
    original, duplicate = rows['46'], rows['98']
    assert duplicate[1:3] == original[1:3] == ['kilo-auto', 'kilo-auto/free']
    assert (int(duplicate[3]) - int(original[3])) % 60 == 30
    lock = json.loads(Path('.github/factory-expected-workers.json').read_text())
    assert 98 in lock['expected_workers'] and 98 not in lock['retired_workers']
    workflow = Path('.github/workflows/free-model-factory-run.yml').read_text()
    smoke = workflow.split('- name: Smoke Kilo Auto Free through Kilo CLI')[1].split('\n      - name:')[0]
    assert smoke.index("grep -q '^provider_quota'") < smoke.index("if grep -q 'KILO_AUTO_FREE_OK'")


def test_current_free_openrouter_coding_candidates_replace_retired_inkling_workers() -> None:
    """New worker identities use explicit zero-price pins and retire stale catalog IDs."""
    rows = {
        fields[0]: fields
        for line in Path(".github/free-model-factories.tsv").read_text().splitlines()
        if line and not line.startswith("#")
        for fields in [line.split("\t")]
    }
    expected = {
        "108": "thinkingmachines/inkling-2-small:free",
        "109": "baidu/ernie-5.5-flash-preview:free",
        "110": "inclusionai/ling-3.2-flash:free",
    }
    for worker, model in expected.items():
        assert rows[worker][1:3] == ["openrouter-free", model]
    assert {"52", "53"}.isdisjoint(rows)
    lock = json.loads(Path(".github/factory-expected-workers.json").read_text())
    assert {108, 109, 110}.issubset(lock["expected_workers"])
    assert {52, 53}.issubset(lock["retired_workers"])
    assert {
        "thinkingmachines/inkling:free",
        "thinkingmachines/inkling-small:free",
    }.issubset(lock["retired_models"])
