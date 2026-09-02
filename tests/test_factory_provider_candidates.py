"""Tests for centralized factory provider candidate adapters."""

from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path
from types import ModuleType


SCRIPT = (
    Path(__file__).resolve().parents[1]
    / ".github"
    / "scripts"
    / "factory_provider_candidates.py"
)


def load_module() -> ModuleType:
    """Load the script module without requiring .github to be a package."""
    spec = importlib.util.spec_from_file_location("factory_provider_candidates", SCRIPT)
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


CANDIDATES = load_module()


def test_nvidia_requires_runtime_evidence_without_account_catalog() -> None:
    """NVIDIA candidates are not guessed without reliable enumeration."""
    result = CANDIDATES.discover(
        "nvidia",
        json.dumps({"data": [{"id": "vendor/new-code-model"}]}),
        ["vendor/new-code-model"],
    )

    assert result.mode == "runtime_only"
    assert result.status == "indeterminate"
    assert result.candidates == ()


def test_openrouter_requires_catalog_evidence_of_free_cost() -> None:
    """Paid OpenRouter models never enter the free candidate pool."""
    result = CANDIDATES.discover(
        "openrouter-free",
        json.dumps(
            {
                "data": [
                    {
                        "id": "vendor/free-by-price",
                        "pricing": {"prompt": "0", "completion": "0.000"},
                    },
                    {
                        "id": "vendor/free-suffix:free",
                        "pricing": {"prompt": "1", "completion": "1"},
                    },
                    {
                        "id": "vendor/paid",
                        "pricing": {"prompt": "0.1", "completion": "0.2"},
                    },
                ]
            }
        ),
    )

    assert [candidate.model for candidate in result.candidates] == [
        "vendor/free-by-price",
        "vendor/free-suffix:free",
    ]
    assert all(
        candidate.runtime_model.startswith("openrouter/")
        for candidate in result.candidates
    )


def test_opencode_uses_project_available_cli_catalog() -> None:
    """Only OpenCode selectors exposed to the current project are candidates."""
    result = CANDIDATES.discover(
        "opencode-free",
        "opencode/new-free\nopenrouter/not-this-provider\ninvalid\n",
        ["new-free", "missing-free"],
    )

    assert result.status == "available"
    assert [candidate.model for candidate in result.candidates] == ["new-free"]
    assert result.candidates[0].discovered_by == "opencode_models"


def test_omniroute_exposes_only_validated_free_cascade() -> None:
    """OmniRoute contributes the validated free cascade."""
    result = CANDIDATES.discover(
        "omniroute-free",
        json.dumps(
            {
                "data": [
                    {"id": "free-cascade-small"},
                    {"id": "auto/best-coding"},
                    {"id": "provider/backing-model"},
                ]
            }
        ),
    )

    assert result.status == "available"
    assert [candidate.model for candidate in result.candidates] == [
        "free-cascade-small"
    ]
    assert result.candidates[0].runtime_model == "omniroute/free-cascade-small"



def test_invalid_catalog_fails_closed() -> None:
    """Malformed catalog responses produce no executable candidates."""
    result = CANDIDATES.discover("openrouter-free", "service unavailable")

    assert result.status == "invalid"
    assert result.candidates == ()


def test_empty_catalog_is_not_capacity() -> None:
    """A valid catalog with no eligible entries contributes no capacity."""
    result = CANDIDATES.discover(
        "openrouter-free",
        json.dumps(
            {
                "data": [
                    {
                        "id": "vendor/paid",
                        "pricing": {"prompt": "1", "completion": "1"},
                    }
                ]
            }
        ),
    )

    assert result.status == "empty"
    assert result.candidates == ()


def test_kilo_auto_encapsulates_non_enumerating_route() -> None:
    """Kilo Auto waits for real runtime evidence instead of guessing models."""
    result = CANDIDATES.discover("kilo-auto", "ignored")

    assert result.mode == "runtime_only"
    assert result.status == "indeterminate"
    assert result.candidates == ()


def test_unknown_provider_is_rejected() -> None:
    """Unregistered providers cannot silently become executable capacity."""
    try:
        CANDIDATES.discover("mystery-provider", "{}")
    except ValueError as exc:
        assert "unsupported factory provider" in str(exc)
    else:
        raise AssertionError("unknown provider did not fail closed")
