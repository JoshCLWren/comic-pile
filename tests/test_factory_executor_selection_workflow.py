"""Regression coverage for dispatch-time factory executor selection."""

from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
WORKFLOW = ROOT / ".github" / "workflows" / "free-model-factory-run.yml"
SMOKE_SCRIPT = ROOT / ".github" / "scripts" / "factory_omniroute_smoke.sh"


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
    assert "auto/reasoning:free" in selector
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
    assert "Unexpected native OmniRoute intent" in selector
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
        "${{ steps.smoke.outputs.model || steps.route.outputs.model || steps.executor.outputs.model || steps.lane.outputs.model }}"
    )
    selected_runtime = (
        "${{ steps.smoke.outputs.runtime_model || steps.route.outputs.runtime_model || steps.executor.outputs.runtime_model || steps.lane.outputs.runtime_model }}"
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
        "control_plane_failure\\tUnexpected native OmniRoute intent: %s\\n"
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
    smoke = SMOKE_SCRIPT.read_text(encoding="utf-8")

    assert "record_smoke_model_outcome()" in smoke
    assert "model_retired_410\\t%s\\n" in smoke
    assert "model_unavailable\\t%s\\n" in smoke
    assert "Model is unavailable" in smoke


def test_smoke_timeout_reaches_gateway_retry_path() -> None:
    """A CLI timeout is transient and must reach the worker retry loop."""
    workflow = WORKFLOW.read_text(encoding="utf-8")
    smoke = SMOKE_SCRIPT.read_text(encoding="utf-8")

    assert "status == 124 || status == 137 || status == 143" in smoke
    assert "allowing worker to proceed with built-in retry handling" in workflow


def test_review_intent_is_carried_through_without_backing_model_selection() -> None:
    """Exact-head review keeps auto/reasoning:free instead of a concrete model."""
    workflow = WORKFLOW.read_text(encoding="utf-8")
    selector = _native_intent_selector(workflow)
    smoke = workflow.split(
        "- name: Smoke selected OmniRoute route through OpenCode", maxsplit=1
    )[1].split("- name: Smoke Kilo Auto Free through Kilo CLI", maxsplit=1)[0]
    session = workflow.split(
        "- name: Run continuous fixed-model factory session", maxsplit=1
    )[1].split("- name: Report OmniRoute routing summary", maxsplit=1)[0]

    assert "auto/coding:free|auto/reasoning:free" in selector
    assert "factory_provider_candidates.py" not in selector
    assert "factory_candidate_health.py" not in selector
    assert "factory_omniroute_smoke.sh" in smoke
    assert "factory_provider_candidates.py" not in smoke
    assert "factory_candidate_health.py" not in smoke
    assert "factory_provider_candidates.py" not in SMOKE_SCRIPT.read_text(encoding="utf-8")
    assert "factory_candidate_health.py" not in SMOKE_SCRIPT.read_text(encoding="utf-8")
    assert "free-model-factory-worker.sh" in session
    assert "factory-work-controller.py inspect --worker" in workflow
    assert 'factory_omniroute_route.py --mode "$kind" --pr-stage "$stage"' in workflow
    assert "assignment-aware-native-intent" in workflow
    assert "auto/reasoning:free" in workflow


def test_pre_session_failure_releases_controller_claim_immediately() -> None:
    """Smoke/pre-session abort releases the lease without waiting 900s."""
    workflow = WORKFLOW.read_text(encoding="utf-8")

    assert "Release controller claim after pre-session abort" in workflow
    assert "steps.session.outcome == 'skipped'" in workflow
    assert "release --worker \"$WORKER\" --reason" in workflow
    assert "smoke-failure" in workflow
    assert "not waiting for the 900s stale-lease TTL" in workflow
    assert workflow.index("Smoke selected OmniRoute route through OpenCode") < (
        workflow.index("Release controller claim after pre-session abort")
    )


def test_temporary_capacity_bridge_retries_best_free_after_coding_skip() -> None:
    """Native intent stays first; ALL_TARGETS_SKIPPED may retry auto/best-free."""
    workflow = WORKFLOW.read_text(encoding="utf-8")
    smoke = workflow.split(
        "- name: Smoke selected OmniRoute route through OpenCode", maxsplit=1
    )[1].split("- name: Smoke Kilo Auto Free through Kilo CLI", maxsplit=1)[0]

    script = SMOKE_SCRIPT.read_text(encoding="utf-8")
    assert "factory_omniroute_smoke.sh" in smoke
    assert "TEMPORARY OmniRoute capacity bridge" in script
    assert "auto/best-free" in workflow
    assert "--next-after-smoke-failure" in script
    assert "FACTORY_OMNIROUTE_CAPACITY_BRIDGE=off" in script
    assert "FACTORY_ROUTE_OVERRIDE" in workflow
    assert "factory_provider_candidates.py" not in smoke
    assert "factory_candidate_health.py" not in smoke
    assert "${OMNIROUTE_BASE_URL%/}/models" not in smoke
    assert "factory_provider_candidates.py" not in script
    assert "factory_candidate_health.py" not in script


def test_missing_native_capacity_fails_at_smoke_not_catalog_selection() -> None:
    """Unusable native intent capacity is recorded by OpenCode smoke, not /models."""
    workflow = WORKFLOW.read_text(encoding="utf-8")
    selector = _native_intent_selector(workflow)
    smoke = workflow.split(
        "- name: Smoke selected OmniRoute route through OpenCode", maxsplit=1
    )[1].split("- name: Smoke Kilo Auto Free through Kilo CLI", maxsplit=1)[0]

    assert "Select execution candidate at dispatch time" not in workflow
    assert "${OMNIROUTE_BASE_URL%/}/models" not in selector
    assert "factory_candidate_health.py" not in selector
    assert "factory_omniroute_smoke.sh" in smoke
    assert "record_smoke_model_outcome()" in SMOKE_SCRIPT.read_text(encoding="utf-8")
    assert workflow.index("Select native OmniRoute execution intent") < workflow.index(
        "Smoke selected OmniRoute route through OpenCode"
    )
    assert workflow.index("Smoke selected OmniRoute route through OpenCode") < (
        workflow.index("Run continuous fixed-model factory session")
    )
