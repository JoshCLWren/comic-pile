"""Contract checks for runtime-derived factory worker outcome classification."""
from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / ".github/scripts/factory_dynamic_outcome.py"
spec = importlib.util.spec_from_file_location("factory_dynamic_outcome_tested", SOURCE)
assert spec and spec.loader
module = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = module
spec.loader.exec_module(module)


def session(source: str, failure: str) -> str:
    worker = "10001"
    model = "synthetic/review-model"
    return (
        f"Factory {worker} assigned dynamic provider slot: source={source} configured=true\n"
        f"  FACTORY_RUNTIME_MODEL: {source}/{model}\n"
        f"[factory:{worker}][source:{source}][model:{model}] "
        "checked out pr #34 on factory/work\n"
        f"{failure}\n"
        f"[factory:{worker}][source:{source}][model:{model}] "
        "agent exit status 1 for pr #34\n"
    )


def test_dynamic_account_quota_is_real_provider_quota():
    result = module.classify(session(
        "ollama-cloud", "Error: Add usage credits or subscribe and save up to 66%",
    ))
    assert result["worker"] == "10001"
    assert result["model"] == "synthetic/review-model"
    assert result["source"] == "ollama-cloud"
    assert result["outcome_class"] == "provider_quota"
    assert not result["exact_model_proven"]


def test_dynamic_tier_denial_affects_selected_model_only():
    result = module.classify(session(
        "vercel-ai-gateway",
        "Error: Free tier users do not have access to this model. Upgrade to paid credits.",
    ))
    assert result["model"] == "synthetic/review-model"
    assert result["outcome_class"] == "model_unavailable"
    assert result["delivery_outcome"] == "none"


def test_all_candidates_cooling_is_idle_not_new_failure():
    result = module.classify(
        "Factory 10001 assigned dynamic provider slot: source=mistral configured=true\n"
        "factory catalog: mistral: catalog contained no eligible candidates outside cooldown\n"
    )
    assert result["worker"] == "10001"
    assert result["source"] == "mistral"
    assert result["outcome_class"] == "no_work"
    assert result["model"] == ""


def test_dynamic_other_errors_delegate_to_canonical_classifier():
    result = module.classify(session("pollinations", "Error: HTTP 429 Too Many Requests"))
    assert result["outcome_class"] == "provider_throttle"
    assert result["model"] == "synthetic/review-model"


def test_legacy_explicit_lock_continues_to_use_canonical_classifier():
    result = module.classify(
        "Factory 42 locked: source=mistral model=synthetic/model "
        "runtime=mistral/synthetic/model minute=:00 scheduler=test configured=true\n"
        "Error: HTTP 429 Too Many Requests\n"
    )
    assert result["worker"] == "42"
    assert result["outcome_class"] == "provider_throttle"


def test_unselected_catalog_errors_do_not_blame_entire_provider():
    result = module.classify(
        "Factory 10001 assigned dynamic provider slot: source=mistral configured=true\n"
        "factory catalog: mistral: invalid catalog JSON\n"
    )
    assert result["outcome_class"] == "control_plane_failure"
    assert result["model"] == ""
