"""Regression coverage for dispatch-time factory executor selection."""

from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
WORKFLOW = ROOT / ".github" / "workflows" / "free-model-factory-run.yml"


def test_catalog_backed_providers_use_central_adapter() -> None:
    """OpenCode and OpenRouter choose from live provider catalogs."""
    workflow = WORKFLOW.read_text(encoding="utf-8")
    selector = workflow.split(
        "- name: Select execution candidate at dispatch time", maxsplit=1
    )[1].split("- name: Report selected executor heartbeat", maxsplit=1)[0]

    assert "opencode models opencode --refresh" in selector
    assert "https://openrouter.ai/api/v1/models" in selector
    assert ".github/scripts/factory_provider_candidates.py" in selector
    assert ".github/free-model-factories.tsv | sort -u" in selector
    assert "candidate_index=" in selector


def test_runtime_only_providers_keep_real_probe_authority() -> None:
    """Non-enumerating providers retain their request until a real probe."""
    workflow = WORKFLOW.read_text(encoding="utf-8")
    selector = workflow.split(
        "- name: Select execution candidate at dispatch time", maxsplit=1
    )[1].split("- name: Report selected executor heartbeat", maxsplit=1)[0]

    assert "nvidia|kilo-auto|omniroute-opencode)" in selector
    assert "selected-by-runtime-evidence" in selector


def test_selected_executor_metadata_reaches_worker_and_telemetry() -> None:
    """Provider and selected model remain attempt metadata, not slot identity."""
    workflow = WORKFLOW.read_text(encoding="utf-8")

    selected_model = (
        "${{ steps.executor.outputs.model || steps.lane.outputs.model }}"
    )
    selected_runtime = (
        "${{ steps.executor.outputs.runtime_model "
        "|| steps.lane.outputs.runtime_model }}"
    )
    assert f"MODEL: {selected_model}" in workflow
    assert f"FACTORY_MODEL: {selected_model}" in workflow
    assert f"FACTORY_RUNTIME_MODEL: {selected_runtime}" in workflow
    assert "selected-from-live-provider-catalog" in workflow


def test_discovery_failures_publish_normalized_outcomes() -> None:
    """Catalog transport and eligibility failures are not generic failures."""
    workflow = WORKFLOW.read_text(encoding="utf-8")

    assert "provider_unavailable\\tOpenCode model discovery command failed" in workflow
    assert "provider_unavailable\\tOpenRouter model catalog request failed" in workflow
    assert "model_unavailable\\t%s catalog exposed no policy-eligible candidate" in workflow
    assert 'discovery_record="$(cat "$DISCOVERY_OUTCOME_FILE"' in workflow
    assert "attempt_outcome attempt_detail" in workflow
    assert "outcome='selection-failed'" in workflow
