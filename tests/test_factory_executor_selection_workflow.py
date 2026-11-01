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
    """Incident restore: nvidia/opencode/openrouter/kilo run; OmniRoute does not."""
    workflow = WORKFLOW.read_text(encoding="utf-8")
    selector = _dispatch_selector(workflow)

    assert "nvidia)" in workflow
    assert "opencode-free)" in workflow
    assert "openrouter-free)" in workflow
    assert "factory_live_opencode.py" in selector
    assert "kilo-auto)" in workflow
    assert "z-ai|ollama-cloud|mistral|orcarouter|requesty)" in workflow
    assert "vercel-ai-gateway)" in workflow
    assert (
        "nvidia|kilo-auto|z-ai|ollama-cloud|vercel-ai-gateway|mistral|orcarouter|requesty)"
        in workflow
    )
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


def _nvidia_probe_step(workflow: str) -> str:
    """Return the NVIDIA pre-smoke probe step body."""
    return workflow.split("- name: Probe pinned NVIDIA model before OpenCode smoke", maxsplit=1)[
        1
    ].split("- name: Smoke exact pinned model through OpenCode", maxsplit=1)[0]


def test_openai_compatible_factory_providers_inject_opencode_config() -> None:
    """Z.AI and Ollama Cloud lanes write OmniRoute-shaped openai-compat config."""
    workflow = WORKFLOW.read_text(encoding="utf-8")

    assert "Configure OpenAI-compatible factory provider" in workflow
    assert "https://api.z.ai/api/paas/v4" in workflow
    assert "https://ollama.com/v1" in workflow
    assert "https://api.mistral.ai/v1" in workflow
    assert "https://api.orcarouter.ai/v1" in workflow
    assert "https://router.requesty.ai/v1" in workflow
    assert "https://ai-gateway.vercel.sh/v1" in workflow
    assert "Require Pixel Canary to remain zero-price" in workflow
    assert "Prove Pixel Canary can use OpenCode tools" in workflow
    assert "Z_AI_API_KEY: ${{ secrets.Z_AI_API_KEY }}" in workflow
    assert "OLLAMA_API_KEY: ${{ secrets.OLLAMA_API_KEY }}" in workflow
    assert "MISTRAL_API_KEY: ${{ secrets.MISTRAL_API_KEY }}" in workflow
    assert 'package: "@opencode/ai/providers/openai-compatible"' in workflow


def test_runtime_provider_probes_remain_authoritative() -> None:
    """Pinned NVIDIA and catalog free slots keep real probe/smoke authority."""
    workflow = WORKFLOW.read_text(encoding="utf-8")

    assert "Probe pinned NVIDIA model before OpenCode smoke" in workflow
    assert "Smoke exact pinned model through OpenCode" in workflow
    assert "Smoke Kilo Auto Free through Kilo CLI" in workflow
    assert "integrate.api.nvidia.com" in workflow


def test_nvidia_probe_retries_http_000_and_curl_transport_timeouts() -> None:
    """Empty curl responses must retry like 429, then soft-exit instead of hard-fail."""
    probe = _nvidia_probe_step(WORKFLOW.read_text(encoding="utf-8"))

    assert "--max-time 45" in probe
    assert "--max-time 120" not in probe
    assert "chat/completions || true" not in probe
    assert "|| curl_exit=$?" in probe
    assert "curl_exit" in probe
    assert 'code="${code:-000}"' in probe
    assert '"$code" == "000"' in probe
    assert '"$curl_exit" =~ ^(6|7|28|35|52|56)$' in probe
    assert "allowing worker to proceed with built-in retry handling" in probe
    assert "factory-model-retired-410:v1" in probe
    assert "model_retired_410" in probe
    assert "provider_failure\\tNVIDIA probe HTTP" in probe
    assert "model_unavailable\\tNVIDIA probe HTTP 404" in probe
    assert "max_attempts=3" in probe
    # Transport exhaustion must not sticky-retire or write 410.
    assert probe.index('"$code" == "000"') < probe.index("allowing worker to proceed")
    assert probe.index("allowing worker to proceed") < probe.index(
        "provider_failure\\tNVIDIA probe HTTP"
    )


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
    assert f"FACTORY_MODEL: {selected_model}" in workflow
    assert f"FACTORY_RUNTIME_MODEL: {selected_runtime}" in workflow
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


def test_live_selector_receives_durable_registry_comments() -> None:
    """The live free branch reads all registry pages before invoking the selector."""
    selector = _dispatch_selector(WORKFLOW.read_text(encoding="utf-8"))
    live = selector.split("# Models are selected at execution", 1)[1].split("openrouter-free)", 1)[
        0
    ]
    assert "gh api --paginate --slurp" in live
    assert "/issues/1093/comments?per_page=100" in live
    assert '--comments "$comments_file"' in live
    assert "Factory cooldown evidence could not be read" in live


def test_exact_smoke_failure_reaches_outcome_file(tmp_path: Path) -> None:
    """Execute the real smoke shell with an unavailable model and inspect its record."""
    import os
    import subprocess

    workflow = WORKFLOW.read_text(encoding="utf-8")
    step = workflow.split("- name: Smoke exact pinned model through OpenCode", 1)[1].split(
        "- name: Prove pinned DeepSeek",
        1,
    )[0]
    script = step.split("run: |\n", 1)[1]
    script = "\n".join(line[10:] for line in script.splitlines())
    script = script.replace(
        ".github/scripts/factory_live_opencode.py",
        str(ROOT / ".github/scripts/factory_live_opencode.py"),
    )
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    for name, body in {
        "git": "#!/bin/sh\nexit 0\n",
        "opencode": '#!/bin/sh\necho "Error: Model unavailable: opencode/ll-alpha-free"\nexit 1\n',
    }.items():
        executable = bin_dir / name
        executable.write_text(body)
        executable.chmod(0o755)
    result = subprocess.run(
        ["bash", "-c", script],
        env={
            **os.environ,
            "PATH": f"{bin_dir}:{os.environ['PATH']}",
            "RUNNER_TEMP": str(tmp_path),
            "RUNTIME_MODEL": "opencode/ll-alpha-free",
            "DEEPSEEK_MODE": "normal",
        },
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 1, result.stderr
    assert (tmp_path / "factory-discovery-outcome").read_text() == (
        "model_unavailable\tModel unavailable: opencode/ll-alpha-free\n"
    )


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
