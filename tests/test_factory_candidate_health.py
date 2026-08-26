"""Tests for health-aware provider candidate selection."""

from __future__ import annotations

import importlib.util
import sys
from datetime import UTC, datetime
from pathlib import Path
from types import ModuleType


SCRIPT = (
    Path(__file__).resolve().parents[1]
    / ".github"
    / "scripts"
    / "factory_candidate_health.py"
)
sys.path.insert(0, str(SCRIPT.parent))


def load_module() -> ModuleType:
    """Load the health selector without packaging .github."""
    spec = importlib.util.spec_from_file_location("factory_candidate_health", SCRIPT)
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


HEALTH = load_module()
NOW = 2_000_000
CANDIDATES = [
    {
        "provider": "openrouter-free",
        "model": "vendor/a:free",
        "runtime_model": "openrouter/vendor/a:free",
        "discovered_by": "provider_catalog",
    },
    {
        "provider": "openrouter-free",
        "model": "vendor/b:free",
        "runtime_model": "openrouter/vendor/b:free",
        "discovered_by": "provider_catalog",
    },
]


def evidence(
    model: str,
    outcome: str,
    age: int = 0,
    *,
    provider: str = "openrouter-free",
    trusted: bool = True,
) -> dict[str, object]:
    """Build evidence relative to the fixed test clock."""
    timestamp = datetime.fromtimestamp(NOW - age, tz=UTC)
    return {
        "author_association": "OWNER" if trusted else "NONE",
        "body": (
            "<!-- factory-attempt-outcome:v1 -->\n"
            f"Model: {model}\n"
            f"Source: {provider}\n"
            f"Attempt outcome: {outcome}\n"
            f"Updated: {timestamp.isoformat().replace('+00:00', 'Z')}\n"
        ),
    }


def test_successful_execution_is_preferred_to_unknown_candidate() -> None:
    """Actual successful execution outweighs catalog-only discovery."""
    result = HEALTH.select_candidate(
        CANDIDATES,
        [evidence("vendor/b:free", "success")],
        worker=1,
        now_epoch=NOW,
    )

    assert result.selected is not None
    assert result.selected.model == "vendor/b:free"
    assert result.selected.health_state == "healthy"


def test_permanently_unavailable_model_is_excluded() -> None:
    """Explicit model retirement never remains executable capacity."""
    result = HEALTH.select_candidate(
        CANDIDATES,
        [
            evidence("vendor/a:free", "model_unavailable"),
            evidence("vendor/b:free", "success"),
        ],
        worker=1,
        now_epoch=NOW,
    )

    states = {candidate.model: candidate.health_state for candidate in result.candidates}
    assert states["vendor/a:free"] == "unavailable"
    assert result.selected is not None
    assert result.selected.model == "vendor/b:free"


def test_provider_outage_cools_every_provider_candidate() -> None:
    """Recent provider-wide evidence prevents dispatch to another model."""
    result = HEALTH.select_candidate(
        CANDIDATES,
        [evidence("vendor/a:free", "provider_unavailable")],
        worker=1,
        now_epoch=NOW,
    )

    assert result.selected is None
    assert result.failure_outcome == "provider_unavailable"
    assert {candidate.health_state for candidate in result.candidates} == {"cooling"}


def test_later_success_recovers_provider() -> None:
    """A newer actual success clears older provider outage evidence."""
    result = HEALTH.select_candidate(
        CANDIDATES,
        [
            evidence("vendor/a:free", "provider_unavailable", age=60),
            evidence("vendor/b:free", "success"),
        ],
        worker=1,
        now_epoch=NOW,
    )

    assert result.selected is not None
    assert result.selected.model == "vendor/b:free"


def test_model_interruption_cools_then_degrades() -> None:
    """Transient model failures recover after the existing cooldown."""
    recent = HEALTH.select_candidate(
        [CANDIDATES[0]],
        [evidence("vendor/a:free", "model_interruption")],
        worker=1,
        now_epoch=NOW,
    )
    old = HEALTH.select_candidate(
        [CANDIDATES[0]],
        [
            evidence(
                "vendor/a:free",
                "model_interruption",
                age=HEALTH.FAILURE_COOLDOWN_SECONDS + 1,
            )
        ],
        worker=1,
        now_epoch=NOW,
    )

    assert recent.selected is None
    assert recent.failure_outcome == "model_interruption"
    assert old.selected is not None
    assert old.selected.health_state == "degraded"


def test_unknown_failure_fails_closed_then_degrades() -> None:
    """Unknown failures cool first and recover only after the shared cooldown."""
    recent = HEALTH.select_candidate(
        [CANDIDATES[0]],
        [evidence("vendor/a:free", "unknown_failure")],
        worker=1,
        now_epoch=NOW,
    )
    old = HEALTH.select_candidate(
        [CANDIDATES[0]],
        [
            evidence(
                "vendor/a:free",
                "unknown_failure",
                age=HEALTH.FAILURE_COOLDOWN_SECONDS + 1,
            )
        ],
        worker=1,
        now_epoch=NOW,
    )

    assert recent.selected is None
    assert recent.failure_outcome == "unknown_failure"
    assert old.selected is not None
    assert old.selected.health_state == "degraded"


def test_control_plane_failure_does_not_poison_model() -> None:
    """Controller faults do not replace prior executor health evidence."""
    result = HEALTH.select_candidate(
        [CANDIDATES[0]],
        [
            evidence("vendor/a:free", "success", age=60),
            evidence("vendor/a:free", "control_plane_failure"),
        ],
        worker=1,
        now_epoch=NOW,
    )

    assert result.selected is not None
    assert result.selected.health_state == "healthy"


def test_untrusted_attempt_evidence_is_ignored() -> None:
    """User-authored marker text cannot suppress executable capacity."""
    result = HEALTH.select_candidate(
        [CANDIDATES[0]],
        [evidence("vendor/a:free", "model_unavailable", trusted=False)],
        worker=1,
        now_epoch=NOW,
    )

    assert result.selected is not None
    assert result.selected.health_state == "unknown"
