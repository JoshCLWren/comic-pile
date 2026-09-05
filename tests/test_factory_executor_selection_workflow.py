"""Regression coverage for dispatch-time factory executor selection."""

from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
WORKFLOW = ROOT / ".github" / "workflows" / "free-model-factory-run.yml"


def _native_intent_selector(workflow: str) -> str:
    """Return the native OmniRoute intent selection step body."""
    return workflow.split(
        "- name: Select native OmniRoute execution intent", maxsplit=1
    )[1].split("- name: Report selected executor heartbeat", maxsplit=1)[0]


def test_omniroute_is_the_only_execution_gateway() -> None:
    """GitHub agents select a native OmniRoute intent without catalog discovery."""
    workflow = WORKFLOW.read_text(encoding="utf-8")
    selector = _native_intent_selector(workflow)

    assert "GitHub execution is OmniRoute-only" in selector
    assert "auto/coding:free" in selector
    assert 'omniroute/${LANE_MODEL}' in selector
    assert "${OMNIROUTE_BASE_URL%/}/models" not in selector
    assert "/models" not in selector
    assert ".github/scripts/factory_provider_candidates.py" not in selector
    assert "factory-attempt-comments.json" not in selector
    assert ".github/scripts/factory_candidate_health.py" not in selector
    assert "reason=native-omniroute-intent-direct" in selector


def test_other_catalogs_cannot_be_execution_capacity() -> None:
    """Non-OmniRoute sources and wrong intents fail closed at selection."""
    workflow = WORKFLOW.read_text(encoding="utf-8")
    selector = _native_intent_selector(workflow)

    assert "GitHub execution is OmniRoute-only" in selector
    assert "Unexpected native OmniRoute coding intent" in selector
    assert "Native OmniRoute runtime selector mismatch" in selector
    assert "catalog_candidates" not in selector
    assert "$left + $right | unique_by([.provider, .model])" not in selector
    assert "Selected unsupported catalog provider" not in selector


def test_runtime_only_providers_keep_real_probe_authority() -> None:
    """Runtime-only provider credentials cannot bypass the OmniRoute gateway."""
    workflow = WORKFLOW.read_text(encoding="utf-8")
    selector = _native_intent_selector(workflow)

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
    assert "native-omniroute-intent-direct" in workflow
    assert "health_state=" not in workflow


def test_discovery_failures_publish_normalized_outcomes() -> None:
    """Native intent selection fails closed without catalog probing."""
    workflow = WORKFLOW.read_text(encoding="utf-8")

    assert (
        "control_plane_failure\\tGitHub execution is OmniRoute-only; got %s\\n"
        in workflow
    )
    assert (
        "control_plane_failure\\tUnexpected native OmniRoute coding intent: %s\\n"
        in workflow
    )
    assert (
        "control_plane_failure\\tNative OmniRoute runtime selector mismatch: %s\\n"
        in workflow
    )
    assert "catalog_failures+=('OmniRoute model catalog request failed')" not in workflow
    assert "catalog_failures+=('OmniRoute candidate adapter failed')" not in workflow
    assert "${OMNIROUTE_BASE_URL%/}/models" not in workflow
    assert "OpenRouter_API_KEY" not in workflow
    assert "integrate.api.nvidia.com" not in workflow
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


def test_smoke_timeout_reaches_gateway_retry_path() -> None:
    """A CLI timeout is transient and must reach the worker retry loop."""
    workflow = WORKFLOW.read_text(encoding="utf-8")

    assert "status == 124 || status == 137 || status == 143" in workflow
    assert "allowing worker to proceed with built-in retry handling" in workflow
