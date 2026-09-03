"""Regression coverage for dispatch-time factory executor selection."""

from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
WORKFLOW = ROOT / ".github" / "workflows" / "free-model-factory-run.yml"


def test_omniroute_is_the_only_execution_gateway() -> None:
    """GitHub agents discover and execute through OmniRoute only."""
    workflow = WORKFLOW.read_text(encoding="utf-8")
    selector = workflow.split(
        "- name: Select execution candidate at dispatch time", maxsplit=1
    )[1].split("- name: Report selected executor heartbeat", maxsplit=1)[0]

    assert "${OMNIROUTE_BASE_URL%/}/models" in selector
    assert "provider == \"omniroute-free\"" in selector
    assert ".github/scripts/factory_provider_candidates.py" in selector
    assert "--configured-model" not in selector
    assert "free-model-factories.tsv" not in selector
    assert ".github/scripts/factory_candidate_health.py" in selector
    assert "factory-attempt-comments.json" in selector
    assert "--worker \"$WORKER\"" in selector
    assert "--preferred-provider \"$preferred_provider\"" in selector
    assert "preferred_provider='omniroute-free'" in selector


def test_other_catalogs_cannot_be_execution_capacity() -> None:
    """Diagnostic provider catalogs cannot bypass the OmniRoute gateway."""
    workflow = WORKFLOW.read_text(encoding="utf-8")
    selector = workflow.split(
        "- name: Select execution candidate at dispatch time", maxsplit=1
    )[1].split("- name: Report selected executor heartbeat", maxsplit=1)[0]

    assert "OmniRoute exposed no policy-eligible candidate" in selector
    assert "catalog_candidates='[]'" in selector
    assert "$left + $right | unique_by([.provider, .model])" in selector
    assert ".selected.provider // empty" in selector
    assert "Selected unsupported catalog provider" in selector


def test_runtime_only_providers_keep_real_probe_authority() -> None:
    """Runtime-only provider credentials cannot bypass the OmniRoute gateway."""
    workflow = WORKFLOW.read_text(encoding="utf-8")
    selector = workflow.split(
        "- name: Select execution candidate at dispatch time", maxsplit=1
    )[1].split("- name: Report selected executor heartbeat", maxsplit=1)[0]

    assert "GitHub execution is OmniRoute-only" in selector
    assert "selected-by-runtime-evidence" not in selector


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
    """OmniRoute catalog failures are not generic failures."""
    workflow = WORKFLOW.read_text(encoding="utf-8")

    assert "catalog_failures+=('OmniRoute model catalog request failed')" in workflow
    assert "catalog_failures+=('OmniRoute candidate adapter failed')" in workflow
    assert "OpenRouter_API_KEY" not in workflow
    assert "integrate.api.nvidia.com" not in workflow
    assert "provider_unavailable\\t%s" in workflow
    assert "No catalog provider was executable" in workflow
    assert (
        "model_unavailable\\tLive catalogs exposed no policy-eligible candidate"
        in workflow
    )
    assert 'discovery_record="$(cat "$DISCOVERY_OUTCOME_FILE"' in workflow
    assert "attempt_outcome attempt_detail" in workflow
    assert "outcome='selection-failed'" in workflow


def test_direct_provider_probes_are_removed_from_the_runner() -> None:
    """The production runner cannot bypass OmniRoute with direct probes."""
    workflow = WORKFLOW.read_text(encoding="utf-8")

    assert "Probe pinned NVIDIA model" not in workflow
    assert "No fallback is allowed for a fixed-model lane" not in workflow


def test_smoke_persists_permanent_model_failures() -> None:
    """A failed smoke records exact model retirement/unavailability for rotation."""
    workflow = WORKFLOW.read_text(encoding="utf-8")

    assert "record_smoke_model_outcome()" in workflow
    assert "model_retired_410\\t%s\\n" in workflow
    assert "model_unavailable\\t%s\\n" in workflow
    assert "Model is unavailable" in workflow
