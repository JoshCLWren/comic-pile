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
RETIRED_FIXED_MODELS = {
    "nvidia/nvidia-nemotron-nano-9b-v2",
    "thinkingmachines/inkling",
}
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
    configured_models = {row[2] for row in rows}
    assert RETIRED_FIXED_MODELS.isdisjoint(configured_models)

    rows_by_worker = {row[0]: row for row in rows}
    assert rows_by_worker["23"][1] in CATALOG_SOURCES
    assert rows_by_worker["29"][1] in CATALOG_SOURCES


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
