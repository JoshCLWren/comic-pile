"""OpenCode free models are selected from live catalog, not permanent worker pins."""

from __future__ import annotations

import importlib
import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / ".github" / "scripts"))
selector = importlib.import_module("factory_live_opencode")


def catalog(*entries: tuple[str, int, int]) -> str:
    return json.dumps({
        "models": [
            {"id": model, "cost": {"input": inbound, "output": outbound}}
            for model, inbound, outbound in entries
        ],
    })


def roster(tmp_path: Path) -> Path:
    file = tmp_path / "factory.tsv"
    file.write_text(
        "# worker\tsource\tmodel\tminute\tscheduler\tdisplay_name\n"
        "41\topencode-free\told-free\t5\tdispatcher\tOld\n"
        "42\topencode-free\tother-free\t10\tdispatcher\tOther\n"
        "50\tnvidia\tsome-model\t15\tdispatcher\tNVIDIA\n",
        encoding="utf-8",
    )
    return file


def test_big_pickle_is_one_pool_candidate_not_many_fixed_workers(tmp_path: Path) -> None:
    raw = catalog(("big-pickle", 0, 0), ("model-a-free", 0, 0))
    assert selector.free_models(raw) == ["big-pickle", "model-a-free"]
    assert selector.select_model(raw, 41, 0, roster(tmp_path))["model"] == "big-pickle"
    assert selector.select_model(raw, 42, 0, roster(tmp_path))["model"] == "model-a-free"


def test_new_catalog_models_rotate_without_roster_pr(tmp_path: Path) -> None:
    raw = catalog(
        ("big-pickle", 0, 0),
        ("beam-free", 0, 0),
        ("model-cost-only", 0, 0),
    )
    selected = {
        selector.select_model(raw, 41, turn, roster(tmp_path))["model"]
        for turn in range(3)
    }
    assert selected == set(selector.free_models(raw))


def test_paid_names_do_not_bypass_free_cost_policy() -> None:
    raw = catalog(
        ("premium-free", 0, 1),
        ("paid", 1, 1),
        ("eligible-by-cost", 0, 0),
        ("big-pickle", 0, 0),
    )
    assert selector.free_models(raw) == ["big-pickle", "eligible-by-cost"]


def test_empty_catalog_and_non_opencode_worker_fail_closed(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="no provably free"):
        selector.select_model(catalog(("paid", 1, 1)), 41, 0, roster(tmp_path))
    with pytest.raises(ValueError, match="no OpenCode free slot"):
        selector.select_model(catalog(("big-pickle", 0, 0)), 50, 0, roster(tmp_path))
