"""Regression checks for bounded same-run dynamic OpenCode smoke rotation."""

from __future__ import annotations

import importlib.util
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
WORKFLOW = ROOT / ".github/workflows/free-model-factory-run.yml"
SELECTOR = ROOT / ".github/scripts/factory_live_opencode.py"


def test_same_run_smoke_excludes_attempted_models_and_never_falls_back_to_paid() -> None:
    """Every retry uses the existing catalog policy and excludes prior failures."""
    workflow = WORKFLOW.read_text()
    assert 'if [[ "$SOURCE" == opencode-free && "$DEEPSEEK_MODE" == normal ]]' in workflow
    assert 'attempted+=("$model")' in workflow
    assert 'exclusions+=(--attempted "$prior")' in workflow
    assert '--catalog "$catalog" --comments "$comments" --worker "$WORKER"' in workflow
    assert 'All eligible zero-cost OpenCode models exhausted' in workflow
    assert 'factory-provider-quota' in workflow
    assert 'crouton-tool-smoke-marker' in workflow


def test_selected_smoked_model_is_used_for_actual_factory_session() -> None:
    """Successful fallback must not execute the originally selected failed model."""
    workflow = WORKFLOW.read_text()
    assert 'id: smoke' in workflow
    assert 'echo "model=$model" >> "$GITHUB_OUTPUT"' in workflow
    assert 'echo "runtime_model=$RUNTIME_MODEL" >> "$GITHUB_OUTPUT"' in workflow
    assert 'FACTORY_MODEL: ${{ steps.smoke.outputs.model || steps.executor.outputs.model || steps.lane.outputs.model }}' in workflow
    assert 'FACTORY_RUNTIME_MODEL: ${{ steps.smoke.outputs.runtime_model || steps.executor.outputs.runtime_model || steps.lane.outputs.runtime_model }}' in workflow


def test_selector_supports_per_run_exclusion() -> None:
    """The selector excludes failed candidates in addition to durable cooldowns."""
    source = SELECTOR.read_text()
    assert 'parser.add_argument("--attempted", action="append", default=[])' in source
    assert 'and model not in (attempted or set())' in source
    assert 'attempted=set(args.attempted)' in source
