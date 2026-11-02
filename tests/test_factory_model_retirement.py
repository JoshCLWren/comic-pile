"""Regression tests for retired fixed models and catalog fail-closed behavior."""

from __future__ import annotations

import importlib.util
import sys
from datetime import UTC, datetime
from pathlib import Path
from types import ModuleType


ROOT = Path(__file__).resolve().parents[1]
ROSTER = ROOT / ".github" / "free-model-factories.tsv"
HEALTH_SCRIPT = ROOT / ".github" / "scripts" / "factory_candidate_health.py"
ROSTER_SCRIPT = ROOT / ".github" / "scripts" / "factory_roster.py"


def _load_roster_lock_module() -> ModuleType:
    """Load the generated roster lock helper."""
    sys.path.insert(0, str(ROSTER_SCRIPT.parent))
    spec = importlib.util.spec_from_file_location("factory_roster_retirement_test", ROSTER_SCRIPT)
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


_ROSTER_MODULE = _load_roster_lock_module()
_ROSTER_LOCK = _ROSTER_MODULE.load_roster_lock()
RETIRED_FIXED_MODELS = set(_ROSTER_LOCK["retired_models"])
REMOVED_WORKERS = {str(worker) for worker in _ROSTER_LOCK["retired_workers"]}
CATALOG_SOURCES = {"opencode-free", "openrouter-free"}
NOW = 2_000_000


def _rows() -> list[tuple[str, ...]]:
    """Read the configured factory roster rows."""
    return [
        tuple(line.split("\t"))
        for line in ROSTER.read_text(encoding="utf-8").splitlines()
        if line and not line.startswith("#")
    ]


def _load_health() -> ModuleType:
    """Load the health selector without packaging .github."""
    sys.path.insert(0, str(HEALTH_SCRIPT.parent))
    spec = importlib.util.spec_from_file_location(
        "factory_candidate_health_retirement_test",
        HEALTH_SCRIPT,
    )
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


HEALTH = _load_health()


def _throttle_evidence(provider: str, model: str) -> dict[str, str]:
    """Build trusted provider-throttle evidence at the fixed test clock."""
    updated = datetime.fromtimestamp(NOW, tz=UTC)
    return {
        "author_association": "OWNER",
        "body": (
            "<!-- factory-attempt-outcome:v1 -->\n"
            f"Model: {model}\n"
            f"Source: {provider}\n"
            "Attempt outcome: provider_throttle\n"
            f"Updated: {updated.isoformat().replace('+00:00', 'Z')}\n"
        ),
    }


def test_retired_fixed_models_are_replaced_by_catalog_free_slots() -> None:
    """Permanently retired models cannot keep consuming fixed factory lanes."""
    rows = _rows()
    # Router lanes (orcarouter, requesty) use source-scoped retirement keys so
    # a retired upstream id elsewhere does not retire the router lane.
    configured_models = {_ROSTER_MODULE.retirement_key(row[1], row[2]) for row in rows}
    assert RETIRED_FIXED_MODELS.isdisjoint(configured_models)
    assert REMOVED_WORKERS.isdisjoint({row[0] for row in rows})

    rows_by_worker = {row[0]: row for row in rows}
    catalog_free_workers = [
        worker for worker, row in rows_by_worker.items() if row[1] in CATALOG_SOURCES
    ]
    assert catalog_free_workers, "at least one catalog-free replacement lane must remain"
    # Worker 29 was retired by Factory Model Discovery once its
    # qwen/qwen3.8-27b:free pin left OpenRouter; the slot stays unused.
    assert "29" in REMOVED_WORKERS
    assert "29" not in rows_by_worker
    # Workers 68/69 retired before OpenRouter Laguna :free access ends 2026-10-31.
    assert "68" in REMOVED_WORKERS
    assert "69" in REMOVED_WORKERS
    assert "68" not in rows_by_worker
    assert "69" not in rows_by_worker
    assert "poolside/laguna-s-2.1:free" in RETIRED_FIXED_MODELS
    assert "poolside/laguna-xs-2.1:free" in RETIRED_FIXED_MODELS
    assert rows_by_worker["11"][1] == "nvidia"
    assert rows_by_worker["11"][2] == "poolside/laguna-xs-2.1"
    assert rows_by_worker["46"][1] == "kilo-auto"
    # Ghost lanes whose models left the free catalogs: OpenRouter Nemotron 3
    # Super / MiniMax M3.1 Flash, plus OpenCode Space Bunny, Muse Spark 1.3,
    # LongCat 2.5 Preview, and Cat Jam.
    for worker in ("49", "58", "63", "73", "83", "94"):
        assert worker in REMOVED_WORKERS
        assert worker not in rows_by_worker
    assert "space-bunny-free" in RETIRED_FIXED_MODELS
    assert "muse-spark-1.3-contributor-free" in RETIRED_FIXED_MODELS
    assert "nvidia/nemotron-3-super-120b-a12b:free" in RETIRED_FIXED_MODELS
    assert "longcat-2.5-preview-free" in RETIRED_FIXED_MODELS
    assert "cat-jam-free" in RETIRED_FIXED_MODELS
    assert "minimax/minimax-m3.1-flash:free" in RETIRED_FIXED_MODELS
    assert rows_by_worker["42"][1] == "opencode-free"
    assert rows_by_worker["42"][2] == "nemotron-3-ultra-free"
    assert rows_by_worker["46"][1] == "kilo-auto"
    assert rows_by_worker["46"][2] == "kilo-auto/free"


def test_catalog_selection_fails_closed_when_every_candidate_is_cooling() -> None:
    """A throttled free catalog must not dispatch an unhealthy candidate."""
    candidates = [
        {
            "provider": "opencode-free",
            "model": "big-pickle",
            "runtime_model": "opencode/big-pickle",
            "discovered_by": "opencode_models",
        },
        {
            "provider": "openrouter-free",
            "model": "stealth/ox-alpha",
            "runtime_model": "openrouter/stealth/ox-alpha",
            "discovered_by": "provider_catalog",
        },
    ]
    evidence = [
        _throttle_evidence(candidate["provider"], candidate["model"])
        for candidate in candidates
    ]

    result = HEALTH.select_candidate(
        candidates,
        evidence,
        worker=23,
        now_epoch=NOW,
    )

    assert result.selected is None
    assert result.failure_outcome == "provider_throttle"
    assert {candidate.health_state for candidate in result.candidates} == {"cooling"}
