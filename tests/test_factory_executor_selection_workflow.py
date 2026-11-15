"""Regression coverage for dispatch-time factory executor selection."""

from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
WORKFLOW = ROOT / ".github" / "workflows" / "free-model-factory-run.yml"


def _dispatch_selector(workflow: str) -> str:
    """Return the dispatch-time candidate selection step body."""
    return workflow.split("- name: Select execution candidate at dispatch time", maxsplit=1)[
        1
    ].split("- name: Report selected executor heartbeat", maxsplit=1)[0]


def test_multi_provider_entry_is_restored_while_omniroute_stays_dark() -> None:
    """Native lanes remain executable; compatible providers use the registry."""
    workflow = WORKFLOW.read_text(encoding="utf-8")
    selector = _dispatch_selector(workflow)

    assert "factory_provider_registry.py resolve" in workflow
    assert "opencode-free|openrouter-free)" in workflow
    assert "factory_live_opencode.py" in selector
    assert "kilo-auto)" in workflow
    assert "omniroute-disabled-incident" in workflow
    assert "FACTORY_OMNIROUTE_ENABLED" in workflow
    assert "factory_provider_candidates.py" in selector
    assert "factory_candidate_health.py" in selector
    assert "auto/coding:free" not in selector
    assert "auto/best-free" not in workflow
    assert "GitHub execution is OmniRoute-only" not in workflow


def test_omniroute_catalog_discovery_requires_explicit_enable() -> None:
    """OmniRoute catalog fetch stays gated off during the incident."""
    workflow = WORKFLOW.read_text(encoding="utf-8")
    selector = _dispatch_selector(workflow)

    assert 'FACTORY_OMNIROUTE_ENABLED:-off}" =~ ^(1|on|true|yes)$' in selector
    configure = workflow.split("- name: Configure selected OmniRoute capacity", maxsplit=1)[1][:240]
    assert "vars.FACTORY_OMNIROUTE_ENABLED == 'on'" in configure


def test_openai_compatible_factory_providers_inject_opencode_config() -> None:
    """A single registry configures all compatible provider endpoints."""
    workflow = WORKFLOW.read_text(encoding="utf-8")
    registry = (ROOT / ".github" / "scripts" / "factory_provider_registry.py").read_text(encoding="utf-8")

    assert "Configure OpenAI-compatible factory provider" in workflow
    assert "factory_provider_registry.py config" in workflow
    assert "modelID" in registry
    assert "Require Vercel model to remain zero-price" in workflow
    for key in ("Z_AI_API_KEY", "OLLAMA_API_KEY", "MISTRAL_API_KEY", "ORCAROUTER_API_KEY", "REQUESTY_API_KEY"):
        assert f"{key}: ${{{{ secrets.{key} }}}}" in workflow


def test_new_free_api_sources_use_real_provider_models_and_credentials() -> None:
    """New source identities and keys live in the registry, not shell cases."""
    workflow = WORKFLOW.read_text(encoding="utf-8")
    registry = (ROOT / ".github" / "scripts" / "factory_provider_registry.py").read_text(encoding="utf-8")
    for source, secret in (
        ("gemini-free", "GEMINI_API_KEY"),
        ("groq-free", "GROQ_API_KEY"),
        ("aion-free", "AION_API_KEY"),
        ("cohere-eval", "COHERE_API_KEY"),
        ("typhoon-free", "TYPHOON_API_KEY"),
    ):
        assert f'"{source}": ProviderSpec(' in registry
        assert f'"{secret}"' in registry
        assert f"{secret}: ${{{{ secrets.{secret} }}}}" in workflow
    assert "Require Vercel model to remain zero-price" in workflow


def test_model_requests_are_reserved_for_the_real_work_session() -> None:
    """No redundant model inference is spent on probes or tool-canary prompts."""
    workflow = WORKFLOW.read_text(encoding="utf-8")
    prework = workflow.split("- name: Run continuous fixed-model factory session", 1)[0]
    assert "Wait for exact model in OpenCode catalog" in prework
    assert "Require Vercel model to remain zero-price" in prework
    assert "opencode run" not in prework
    assert "KILO_AUTO_FREE_OK" not in prework
    assert "/chat/completions" not in prework


def test_selected_executor_metadata_reaches_worker_and_telemetry() -> None:
    """Provider and selected model remain attempt metadata for the worker."""
    workflow = WORKFLOW.read_text(encoding="utf-8")

    selected_source = "${{ steps.executor.outputs.source || steps.lane.outputs.source }}"
    selected_model = "${{ steps.executor.outputs.model || steps.lane.outputs.model }}"
    selected_runtime = (
        "${{ steps.executor.outputs.runtime_model || steps.lane.outputs.runtime_model }}"
    )
    selected_branch = (
        "${{ steps.executor.outputs.branch_suffix || steps.lane.outputs.branch_suffix }}"
    )
    assert f"SOURCE: {selected_source}" in workflow
    assert f"FACTORY_SOURCE: {selected_source}" in workflow
    assert f"MODEL: {selected_model}" in workflow
    assert (
        "FACTORY_MODEL: ${{ steps.model_preflight.outputs.model || steps.executor.outputs.model || steps.lane.outputs.model }}"
        in workflow
    )
    assert (
        "FACTORY_RUNTIME_MODEL: ${{ steps.model_preflight.outputs.runtime_model || steps.executor.outputs.runtime_model || steps.lane.outputs.runtime_model }}"
        in workflow
    )
    assert f"RUNTIME_MODEL: {selected_runtime}" in workflow
    assert f"FACTORY_BRANCH_SUFFIX: {selected_branch}" in workflow


def test_discovery_failures_publish_normalized_outcomes() -> None:
    """Catalog/provider discovery failures write normalized outcome markers."""
    workflow = WORKFLOW.read_text(encoding="utf-8")
    selector = _dispatch_selector(workflow)

    assert "factory-discovery-outcome" in selector
    assert "control_plane_failure" in selector
    assert "provider_unavailable" in selector or "model_unavailable" in selector


def test_worker_refuses_omniroute_source_during_incident() -> None:
    """The session wrapper refuses omniroute-free while OmniRoute is dark."""
    worker = (ROOT / ".github" / "scripts" / "free-model-factory-worker.sh").read_text(
        encoding="utf-8"
    )

    assert "OmniRoute Entry is disabled for this incident" in worker
    assert "omniroute-free" in worker
    assert "OmniRoute-only" not in worker


def test_live_selector_uses_trusted_neon_exclusions_without_registry_scan() -> None:
    """Dynamic free models use a trusted Neon snapshot and a live-cost catalog."""
    workflow = WORKFLOW.read_text(encoding="utf-8")
    selector = _dispatch_selector(workflow)
    live = selector.split("# Models are selected at execution", 1)[1].split("openrouter-free)", 1)[0]
    assert "/issues/1093/comments?per_page=100" not in live
    assert '--exclusions-file "$exclusions_file"' in live
    assert 'printf \'[]\\n\' > "$comments_file"' in live
    assert 'FACTORY_MODEL_EXCLUSIONS: ${{ inputs.model_exclusions }}' in workflow
    assert 'jq -e \'type == "object" and all(.[]; type == "array")\'' in selector


def test_unavailability_snapshot_cannot_be_overwritten_as_worker_record(tmp_path: Path) -> None:
    """Execute terminal reporting and inspect the separate immutable failure body."""
    import json
    import os
    import subprocess

    import yaml

    workflow = yaml.safe_load(WORKFLOW.read_text(encoding="utf-8"))
    report = next(
        step for step in workflow["jobs"]["factory"]["steps"]
        if step.get("name") == "Report terminal heartbeat"
    )
    script = report["run"]
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    gh = bin_dir / "gh"
    gh.write_text(
        "#!/usr/bin/env python3\n"
        "import json, os, sys\n"
        "args=sys.argv[1:]\n"
        "if '--method' in args and args[args.index('--method')+1]=='POST':\n"
        "    with open(os.environ['CAPTURE_FILE'], 'a') as file:\n"
        "        file.write(json.dumps(args[-1].removeprefix('body='))+'\\n')\n"
        "print('[]')\n"
    )
    gh.chmod(0o755)
    outcome = tmp_path / "outcome"
    outcome.write_text("model_unavailable\tModel unavailable: opencode/ll-alpha-free\n")
    capture = tmp_path / "posted.jsonl"
    result = subprocess.run(
        ["bash", "-c", script],
        env={
            **os.environ,
            "PATH": f"{bin_dir}:{os.environ['PATH']}",
            "CAPTURE_FILE": str(capture),
            "WORKER": "41",
            "MODEL": "ll-alpha-free",
            "SOURCE": "opencode-free",
            "MINUTE": "0",
            "CONFIGURED": "true",
            "REASON": "selected-from-live-free-catalog",
            "JOB_STATUS": "failure",
            "WORKER_STATUS_FILE": str(tmp_path / "missing"),
            "DISCOVERY_OUTCOME_FILE": str(outcome),
            "GITHUB_RUN_ID": "123",
            "GITHUB_REPOSITORY": "owner/repo",
        },
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0, result.stderr
    posted = [json.loads(line) for line in capture.read_text().splitlines()]
    snapshots = [body for body in posted if "<!-- factory-model-unavailable:v1" in body]
    assert len(snapshots) == 1
    snapshot = snapshots[0]
    assert "<!-- factory-attempt-outcome:v1" not in snapshot
    assert "Model: ll-alpha-free\nSource: opencode-free" in snapshot
    assert "Attempt outcome: model_unavailable" in snapshot
    assert "Updated: " in snapshot
    assert "Run: 123" in snapshot
    assert sum("<!-- factory-attempt-outcome:v1" in body for body in posted) == 1
