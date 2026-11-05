"""Regression checks for bounded same-run dynamic OpenCode smoke rotation."""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest
import yaml

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
    terminal = workflow.split('      - name: Report terminal heartbeat', 1)[1]
    assert 'MODEL: ${{ steps.smoke.outputs.model || steps.executor.outputs.model || steps.lane.outputs.model }}' in terminal


def test_selector_supports_per_run_exclusion() -> None:
    """The selector excludes failed candidates in addition to durable cooldowns."""
    source = SELECTOR.read_text()
    assert 'parser.add_argument("--attempted", action="append", default=[])' in source
    assert 'and model not in (attempted or set())' in source
    assert 'attempted=set(args.attempted)' in source


def _run_dynamic_smoke(
    tmp_path: Path,
    *,
    scenario: str,
    catalog_models: tuple[tuple[str, int], ...],
    initial_model: str = "model-a-free",
) -> tuple[subprocess.CompletedProcess[str], list[str], str, str]:
    """Exercise the real workflow's smoke script with deterministic fake executables."""
    workflow = yaml.safe_load(WORKFLOW.read_text(encoding="utf-8"))
    smoke = next(
        step["run"]
        for step in workflow["jobs"]["factory"]["steps"]
        if step.get("name") == "Smoke exact pinned model through OpenCode"
    )
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    git = bin_dir / "git"
    git.write_text("#!/bin/sh\nexit 0\n", encoding="utf-8")
    git.chmod(0o755)
    gh = bin_dir / "gh"
    gh.write_text(
        "#!/bin/sh\nprintf '%s\\n' \"$@\" >> \"$SMOKE_GH_LOG\"\n",
        encoding="utf-8",
    )
    gh.chmod(0o755)
    opencode = bin_dir / "opencode"
    opencode.write_text(
        "#!" + sys.executable + "\n"
        "import os, pathlib, sys\n"
        "model = sys.argv[sys.argv.index('-m') + 1]\n"
        "with open(os.environ['SMOKE_ATTEMPTS'], 'a') as out:\n"
        "    out.write(model + '\\n')\n"
        "scenario = os.environ['SMOKE_SCENARIO']\n"
        "if scenario == 'all-quota' or (scenario == 'quota-then-success' and model.endswith('model-a-free')):\n"
        "    print('Free usage limit reached')\n"
        "    sys.exit(1)\n"
        "if scenario == 'nonquota-failure':\n"
        "    print('Unexpected provider authentication failure')\n"
        "    sys.exit(17)\n"
        "if model == 'opencode/crouton-alpha-free' and scenario == 'crouton-tool':\n"
        "    (pathlib.Path(os.environ['RUNNER_TEMP']) / 'crouton-tool-smoke-marker').write_text('FIXED_MODEL_OPENCODE_OK')\n"
        "print('FIXED_MODEL_OPENCODE_OK')\n",
        encoding="utf-8",
    )
    opencode.chmod(0o755)

    (tmp_path / "factory-opencode-free-catalog").write_text(
        json.dumps(
            {
                "models": [
                    {"id": model, "cost": {"input": cost, "output": cost}}
                    for model, cost in catalog_models
                ]
            }
        ),
        encoding="utf-8",
    )
    (tmp_path / "factory-opencode-attempt-comments.json").write_text(
        "[]", encoding="utf-8"
    )
    output = tmp_path / "github-output"
    attempts = tmp_path / "smoke-attempts"
    gh_log = tmp_path / "smoke-gh-calls"
    result = subprocess.run(
        ["bash", "-c", smoke],
        cwd=ROOT,
        env={
            **os.environ,
            "PATH": f"{bin_dir}:{os.environ['PATH']}",
            "RUNNER_TEMP": str(tmp_path),
            "RUNTIME_MODEL": f"opencode/{initial_model}",
            "SOURCE": "opencode-free",
            "WORKER": "41",
            "DEEPSEEK_MODE": "normal",
            "GITHUB_RUN_ID": "12345",
            "GITHUB_RUN_NUMBER": "0",
            "GITHUB_REPOSITORY": "owner/repo",
            "GITHUB_OUTPUT": str(output),
            "SMOKE_SCENARIO": scenario,
            "SMOKE_ATTEMPTS": str(attempts),
            "SMOKE_GH_LOG": str(gh_log),
            "EXISTING_OPENCODE_KEY": "",
        },
        capture_output=True,
        text=True,
        check=False,
        timeout=30,
    )
    return (
        result,
        attempts.read_text(encoding="utf-8").splitlines(),
        output.read_text(encoding="utf-8") if output.exists() else "",
        gh_log.read_text(encoding="utf-8") if gh_log.exists() else "",
    )


@pytest.mark.parametrize(
    ("scenario", "expected_status", "expected_attempts"),
    [
        ("quota-then-success", 0, ["opencode/model-a-free", "opencode/model-b-free"]),
        ("all-quota", 1, ["opencode/model-a-free", "opencode/model-b-free"]),
        ("nonquota-failure", 17, ["opencode/model-a-free"]),
    ],
)
def test_dynamic_smoke_rotates_only_after_proven_failure(
    tmp_path: Path, scenario: str, expected_status: int, expected_attempts: list[str]
) -> None:
    """Provider quota retries another verified-free model; other failures do not."""
    result, attempts, output, evidence = _run_dynamic_smoke(
        tmp_path,
        scenario=scenario,
        catalog_models=(("model-a-free", 0), ("model-b-free", 0), ("paid-model", 2)),
    )
    assert result.returncode == expected_status, (result.stdout, result.stderr)
    assert attempts == expected_attempts
    assert "opencode/paid-model" not in attempts
    if scenario == "quota-then-success":
        assert "model=model-b-free" in output
        assert "runtime_model=opencode/model-b-free" in output
        assert "Model: model-a-free" in evidence
        assert "Attempt outcome: provider_quota" in evidence
        assert not (tmp_path / "factory-discovery-outcome").exists()
    elif scenario == "all-quota":
        assert not output
        assert "All eligible zero-cost OpenCode models exhausted" in result.stdout + result.stderr
        assert "Model: model-a-free" in evidence
        assert "Model: model-b-free" in evidence
        assert (tmp_path / "factory-discovery-outcome").read_text().startswith("provider_quota")
    else:
        assert not output
        assert not evidence
        assert not (tmp_path / "factory-discovery-outcome").exists()


@pytest.mark.parametrize(("scenario", "expected_status"), [("crouton-text", 1), ("crouton-tool", 0)])
def test_crouton_requires_actual_shell_tool_proof(
    tmp_path: Path, scenario: str, expected_status: int
) -> None:
    """Text-only Crouton response is rejected even with the expected answer marker."""
    result, attempts, output, _ = _run_dynamic_smoke(
        tmp_path,
        scenario=scenario,
        catalog_models=(("crouton-alpha-free", 0),),
        initial_model="crouton-alpha-free",
    )
    assert result.returncode == expected_status, (result.stdout, result.stderr)
    assert attempts == ["opencode/crouton-alpha-free"]
    assert ("runtime_model=opencode/crouton-alpha-free" in output) == (
        expected_status == 0
    )
