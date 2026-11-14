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

    # Test the live roster as data; historical worker numbers are not contracts.
    catalog_free_rows = [row for row in rows if row[1] in CATALOG_SOURCES]
    assert catalog_free_rows, "at least one catalog-free lane must remain"
    assert all(row[3].isdigit() for row in catalog_free_rows)
    assert all(
        _ROSTER_MODULE.openrouter_model_is_free(row[2])
        for row in catalog_free_rows if row[1] == "openrouter-free"
    )
    assert all(
        _ROSTER_MODULE.opencode_model_is_free(row[2])
        for row in catalog_free_rows if row[1] == "opencode-free"
    )
    assert all(row[2] == "kilo-auto/free" for row in rows if row[1] == "kilo-auto")

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
