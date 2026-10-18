"""OrcaRouter/Requesty factory lanes: pins, runner wiring, and daily budgets."""

from __future__ import annotations

import ast
import importlib.util
import json
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / ".github" / "scripts"


def _load(name: str, filename: str):
    spec = importlib.util.spec_from_file_location(name, SCRIPTS / filename)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


budget = _load("factory_source_budget", "factory_source_budget.py")
roster = _load("factory_roster_for_budget_tests", "factory_roster.py")

SOURCES = {
    "46": "kilo-auto",
    "21": "nvidia",
    "91": "orcarouter",
    "92": "requesty",
    "93": "requesty",
}
CAPS = {"orcarouter": 1, "requesty": 4}


def test_committed_budgets_stay_under_account_limits() -> None:
    """OrcaRouter (50 req/day) gets 1 session/day; Requesty (200 req/day) 4."""
    assert budget.load_budgets() == CAPS


def test_committed_roster_pins_smoked_router_lanes() -> None:
    """Workers 91-93 are the smoked OrcaRouter/Requesty lanes."""
    rows = {row["worker"]: row for row in roster.load_roster_rows(roster.default_roster_path())}
    assert (rows["91"]["source"], rows["91"]["model"]) == ("orcarouter", "z-ai/glm-5.3-flash-free")
    assert (rows["92"]["source"], rows["92"]["model"]) == (
        "requesty",
        "nvidia/nemotron-3-ultra-550b-a55b",
    )
    assert (rows["93"]["source"], rows["93"]["model"]) == (
        "requesty",
        "nvidia/nemotron-3-super-120b-a12b",
    )
    lock = json.loads((ROOT / ".github" / "factory-expected-workers.json").read_text())
    assert {91, 92, 93} <= set(lock["expected_workers"])
    # tencent/hy4-preview-free hit OrcaRouter's free-tier prompt cap in smoke.
    assert "tencent/hy4-preview-free" not in {row["model"] for row in rows.values()}


def test_router_pin_guards() -> None:
    """Only approved ids may occupy router lanes; Orca auto-router is rejected."""
    assert roster.orcarouter_model_is_free("z-ai/glm-5.3-flash-free")
    assert roster.orcarouter_model_is_free("orcarouter/tencent/hy3-free")
    assert not roster.orcarouter_model_is_free("orcarouter/free")
    assert not roster.orcarouter_model_is_free("orca/orcaverify-text1.0-free")
    assert roster.requesty_model_is_approved("requesty/nvidia/nemotron-3-ultra-550b-a55b")
    assert not roster.requesty_model_is_approved("openai/gpt-5")


def test_router_retirement_key_is_source_scoped() -> None:
    """Requesty's nvidia/* ids must not match NVIDIA/OpenRouter lock entries."""
    assert roster.retirement_key("requesty", "nvidia/nemotron-3-ultra-550b-a55b") == (
        "requesty/nvidia/nemotron-3-ultra-550b-a55b"
    )
    assert roster.retirement_key("nvidia", "z-ai/glm-5.3") == "z-ai/glm-5.3"


def test_filter_caps_per_source_including_within_batch() -> None:
    """A batch never exceeds the remaining daily budget of a source."""
    titles = ["Factory 92 · fixed-model entry", "Factory 21 · fixed-model entry", "junk"]
    kept, messages = budget.filter_workers(
        ["21", "91", "92", "93", "46"], titles=titles, caps=CAPS, sources=SOURCES
    )
    assert kept == ["21", "91", "92", "93", "46"]
    titles = ["Factory 91 · fixed-model entry"] + ["Factory 93 · fixed-model entry"] * 3
    kept, messages = budget.filter_workers(
        ["91", "92", "93", "21"], titles=titles, caps=CAPS, sources=SOURCES
    )
    assert kept == ["92", "21"]
    assert any("orcarouter daily dispatch budget 1/1" in m for m in messages)
    assert any("Factory 93 skipped: source requesty" in m for m in messages)


def test_block_reason_and_worker_46_exempt() -> None:
    """The controller gate names the exhausted source; worker 46 is never gated."""
    titles = ["Factory 91 · fixed-model entry"]
    reason = budget.budget_block_reason("91", titles=titles, caps=CAPS, sources=SOURCES)
    assert reason and "orcarouter" in reason and "1/1" in reason
    assert budget.budget_block_reason("92", titles=titles, caps=CAPS, sources=SOURCES) is None
    assert (
        budget.budget_block_reason("46", titles=titles, caps={"kilo-auto": 0}, sources=SOURCES)
        is None
    )


def test_unverifiable_history_fails_closed_for_metered_sources_only(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """If gh cannot read run history, only metered-source workers are dropped."""

    def boom(now=None):
        raise subprocess.CalledProcessError(1, ["gh"])

    monkeypatch.setattr(budget, "todays_entry_titles", boom)
    kept, messages = budget.filter_workers(["21", "91", "92"], caps=CAPS, sources=SOURCES)
    assert kept == ["21"] and len(messages) == 2
    assert budget.budget_block_reason("91", caps=CAPS, sources=SOURCES)


def test_runner_and_dispatcher_wiring() -> None:
    """Runner configures both routers; dispatcher and controller enforce budgets."""
    runner = (ROOT / ".github" / "workflows" / "free-model-factory-run.yml").read_text()
    for needle in (
        "ORCAROUTER_API_KEY: ${{ secrets.ORCAROUTER_API_KEY }}",
        "REQUESTY_API_KEY: ${{ secrets.REQUESTY_API_KEY }}",
        "https://api.orcarouter.ai/v1",
        "https://router.requesty.ai/v1",
        "missing-ORCAROUTER_API_KEY",
        "missing-REQUESTY_API_KEY",
    ):
        assert needle in runner
    dispatcher = (ROOT / ".github" / "workflows" / "fixed-model-factory-dispatch.yml").read_text()
    assert dispatcher.index("factory_source_budget.py filter") < dispatcher.index(
        'controller" capacity'
    )
    controller = (SCRIPTS / "factory-work-controller.py").read_text()
    assert (
        "budget_block_reason(worker)" in controller.split("def assign(", 1)[1].split("\ndef ", 1)[0]
    )


def test_budget_module_parses_on_older_python() -> None:
    """The dispatcher runs this with the runner's system python3."""
    ast.parse((SCRIPTS / "factory_source_budget.py").read_text(), feature_version=(3, 10))


def test_controller_budget_gate_integration() -> None:
    """The controller's assign() function calls budget_block_reason() and blocks workers with exhausted budgets."""
    # Import the controller module
    controller = _load("factory_work_controller", "factory-work-controller.py")
    
    # Mock the budget_block_reason function to return a blocking reason
    def mock_budget_block_reason(worker, **kwargs):
        return f"Factory {worker} source budget exhausted"
    
    # Mock other dependencies to focus on budget check
    original_budget_block_reason = budget.budget_block_reason
    budget.budget_block_reason = mock_budget_block_reason
    
    try:
        # Test that a worker with budget block reason gets skipped
        result = controller.assign("91", dry_run=True)
        assert result is None
        
        # Test that a worker without budget block reason gets processed
        def mock_budget_block_reason_none(worker, **kwargs):
            return None
        
        budget.budget_block_reason = mock_budget_block_reason_none
        result = controller.assign("91", dry_run=True)
        assert result is not None
        
    finally:
        # Restore original function
        budget.budget_block_reason = original_budget_block_reason


def test_scheduled_batch_applies_source_budget_before_offer_cap() -> None:
    """Over-budget metered lanes must not displace eligible workers in the cap."""
    text = (ROOT / ".github/workflows/fixed-model-factory-dispatch.yml").read_text(encoding="utf-8")
    scheduled = text[text.index("source_seed=") : text.index("Scheduled batch:")]
    assert scheduled.index("factory_source_budget.py filter") < scheduled.index(".[:$cap]")
