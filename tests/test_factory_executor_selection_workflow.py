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
    assert ".github/scripts/factory_candidate_health.py" in selector
    assert "factory-attempt-comments.json" in selector
    assert "--worker \"$WORKER\"" in selector


def test_catalog_backed_slots_share_provider_candidates() -> None:
    """Catalog-backed slots rank candidates across both supported providers."""
    workflow = WORKFLOW.read_text(encoding="utf-8")
    selector = workflow.split(
        "- name: Select execution candidate at dispatch time", maxsplit=1
    )[1].split("- name: Report selected executor heartbeat", maxsplit=1)[0]

    assert "opencode-free|openrouter-free)" in selector
    assert "catalog_candidates='[]'" in selector
    assert "$left + $right | unique_by([.provider, .model])" in selector
    assert ".selected.provider // empty" in selector
    assert "Selected unsupported catalog provider" in selector


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

    selected_source = (
        "${{ steps.executor.outputs.source || steps.lane.outputs.source }}"
    )
    selected_model = (
        "${{ steps.executor.outputs.model || steps.lane.outputs.model }}"
    )
    selected_runtime = (
        "${{ steps.executor.outputs.runtime_model "
        "|| steps.lane.outputs.runtime_model }}"
    )
    selected_branch = (
        "${{ steps.executor.outputs.branch_suffix "
        "|| steps.lane.outputs.branch_suffix }}"
    )
    assert f"SOURCE: {selected_source}" in workflow
    assert f"FACTORY_SOURCE: {selected_source}" in workflow
    assert f"MODEL: {selected_model}" in workflow
    assert f"FACTORY_MODEL: {selected_model}" in workflow
    assert f"FACTORY_RUNTIME_MODEL: {selected_runtime}" in workflow
    assert f"FACTORY_BRANCH_SUFFIX: {selected_branch}" in workflow
    assert "from-live-provider-catalog" in workflow
    assert "health_state=" in workflow


def test_discovery_failures_publish_normalized_outcomes() -> None:
    """Catalog transport and eligibility failures are not generic failures."""
    workflow = WORKFLOW.read_text(encoding="utf-8")

    assert "catalog_failures+=('OpenCode model discovery command failed')" in workflow
    assert "catalog_failures+=('OpenRouter model catalog request failed')" in workflow
    assert "provider_unavailable\\t%s" in workflow
    assert "No catalog provider was executable" in workflow
    assert (
        "model_unavailable\\tLive catalogs exposed no policy-eligible candidate"
        in workflow
    )
    assert 'discovery_record="$(cat "$DISCOVERY_OUTCOME_FILE"' in workflow
    assert "attempt_outcome attempt_detail" in workflow
    assert "outcome='selection-failed'" in workflow
