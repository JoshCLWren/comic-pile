"""Issue #1093 registry comments are optional visibility, never a worker prerequisite.

Production runs 43983704814 and 43983667431 validated their assignment and
selected a model, then died in "Report selected executor heartbeat" because
GitHub refuses new comments on a thread with more than 2,500 comments
(HTTP 403). The worker session never started and the lease was released.

These tests execute the real workflow step scripts and the real worker
failover functions against a fake ``gh`` that refuses every registry write.
Worker IDs, sources and models are generated or discovered dynamically.
"""

from __future__ import annotations

import json
import os
import random
import re
import subprocess
import sys
import uuid
from datetime import UTC, datetime
from pathlib import Path

import pytest
import yaml

ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / ".github" / "scripts"
RUN_WORKFLOW = ROOT / ".github" / "workflows" / "free-model-factory-run.yml"
OBSERVER_WORKFLOW = ROOT / ".github" / "workflows" / "fixed-model-runtime-observer.yml"
WORKER_SCRIPT = SCRIPTS / "free-model-factory-worker.sh"
PRIMITIVES = SCRIPTS / "free-model-factory-worker-primitives.sh"
SESSION_STEP = "Run continuous fixed-model factory session"
THREAD_EXHAUSTED = "gh: Commenting is disabled on issues with more than 2500 comments (HTTP 403)"
THROTTLED = "gh: API rate limit exceeded for installation (HTTP 429)"

sys.path.insert(0, str(SCRIPTS))

# Fake gh: GET/PATCH/POST behaviour is chosen per test through environment
# variables, and every invocation is captured for assertions.
FAKE_GH = r"""#!/usr/bin/env python3
import json, os, sys
args = sys.argv[1:]
method = args[args.index("--method") + 1] if "--method" in args else "GET"
with open(os.environ["GH_CAPTURE"], "a", encoding="utf-8") as capture:
    capture.write(json.dumps({"method": method, "args": args}) + "\n")
mode = os.environ.get(f"GH_{method}", "ok")
if mode != "ok":
    sys.stderr.write(mode + "\n")
    raise SystemExit(1)
if method == "GET":
    print(os.environ.get("GH_GET_BODY", "{}"))
elif method == "POST":
    print(json.dumps({"id": int(os.environ.get("GH_POST_ID", "1"))}))
"""


def _worker_id() -> str:
    return str(random.randint(10**11, 10**13))


def _step(workflow: Path, job: str, name: str) -> dict[str, object]:
    data = yaml.safe_load(workflow.read_text(encoding="utf-8"))
    return next(step for step in data["jobs"][job]["steps"] if step.get("name") == name)


def _gh_bin(tmp_path: Path) -> Path:
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir(exist_ok=True)
    gh = bin_dir / "gh"
    gh.write_text(FAKE_GH, encoding="utf-8")
    gh.chmod(0o755)
    return bin_dir


def _calls(capture: Path) -> list[dict[str, object]]:
    if not capture.exists():
        return []
    return [json.loads(line) for line in capture.read_text(encoding="utf-8").splitlines()]


def _trusted_marker(kind: str, worker: str, comment_id: int, run_id: str) -> str:
    marker = "heartbeat" if kind == "heartbeat" else "attempt-outcome"
    return json.dumps({
        "id": comment_id,
        "issue_url": "https://api.github.com/repos/JoshCLWren/comic-pile/issues/1093",
        "user": {"login": "github-actions[bot]", "type": "Bot"},
        "author_association": "NONE",
        "performed_via_github_app": {"slug": "github-actions"},
        "body": (
            f"<!-- factory-{marker}:v1 worker=opencode-free-model-factory-{worker} -->\n"
            f"Worker: opencode-free-model-factory-{worker}\nRun: {run_id}"
        ),
    })


def _run_step(
    tmp_path: Path, script: str, env: dict[str, str]
) -> tuple[subprocess.CompletedProcess[str], list[dict[str, object]], Path]:
    capture = tmp_path / "gh-calls.jsonl"
    github_env = tmp_path / "github-env"
    github_env.touch()
    result = subprocess.run(
        ["bash", "-c", script],
        cwd=ROOT,
        env={
            **os.environ,
            "PATH": f"{_gh_bin(tmp_path)}:{os.environ['PATH']}",
            "GH_CAPTURE": str(capture),
            "RUNNER_TEMP": str(tmp_path),
            "GITHUB_ENV": str(github_env),
            "GITHUB_REPOSITORY": "JoshCLWren/comic-pile",
            "GITHUB_RUN_ID": str(random.randint(10**10, 10**11)),
            **env,
        },
        capture_output=True,
        text=True,
        check=False,
    )
    return result, _calls(capture), github_env


def _heartbeat_env(worker: str, **extra: str) -> dict[str, str]:
    return {
        "WORKER": worker,
        "MODEL": f"model-{uuid.uuid4().hex[:8]}",
        "SOURCE": f"source-{uuid.uuid4().hex[:8]}",
        "MINUTE": "7",
        "CONFIGURED": "true",
        "REASON": "selected-from-live-runtime-catalog",
        "EXECUTOR_OUTCOME": "success",
        "FACTORY_HEARTBEAT_COMMENT_ID": "",
        **extra,
    }


def test_session_cannot_be_skipped_by_a_registry_write_step() -> None:
    """Every #1093 write before the session is continue-on-error and nonfatal."""
    data = yaml.safe_load(RUN_WORKFLOW.read_text(encoding="utf-8"))
    steps = data["jobs"]["factory"]["steps"]
    session = next(i for i, step in enumerate(steps) if step.get("name") == SESSION_STEP)
    registry_writers = [
        step for step in steps[:session]
        if "issues/1093/comments" in str(step.get("run") or "")
    ]
    assert registry_writers, "the selected-executor heartbeat must still be published"
    for step in registry_writers:
        # The session step's implicit success() would otherwise be false.
        assert step.get("continue-on-error") is True, step.get("name")
        assert "exit 1" not in str(step["run"]), step.get("name")
    # The session itself remains gated only on the trusted lane, not on telemetry.
    assert steps[session]["if"] == "steps.lane.outputs.configured == 'true'"


@pytest.mark.parametrize("failure", [THREAD_EXHAUSTED, "gh: Not Found (HTTP 404)",
                                     "gh: Validation Failed (HTTP 422)", THROTTLED])
def test_selected_heartbeat_create_failure_is_nonfatal(tmp_path: Path, failure: str) -> None:
    """403 exhausted thread, 404, 422 and 429 do not fail the pre-session heartbeat."""
    step = _step(RUN_WORKFLOW, "factory", "Report selected executor heartbeat")
    result, calls, github_env = _run_step(
        tmp_path, str(step["run"]), {**_heartbeat_env(_worker_id()), "GH_POST": failure},
    )
    assert result.returncode == 0, result.stderr
    assert [call["method"] for call in calls] == ["POST"]
    assert "FACTORY_REGISTRY_VISIBILITY_SKIPPED op=heartbeat-create" in result.stderr
    status = re.search(r"HTTP (\d{3})", failure)
    assert status and f"http={status.group(1)}" in result.stderr
    # No fabricated locator is exported when the write failed.
    assert "FACTORY_HEARTBEAT_COMMENT_ID" not in github_env.read_text(encoding="utf-8")


def test_selected_heartbeat_unverifiable_locator_never_duplicates(tmp_path: Path) -> None:
    """A throttled lookup cannot prove absence: skip, never POST a duplicate."""
    step = _step(RUN_WORKFLOW, "factory", "Report selected executor heartbeat")
    env = _heartbeat_env(_worker_id(), FACTORY_HEARTBEAT_COMMENT_ID="4242", GH_GET=THROTTLED)
    result, calls, _ = _run_step(tmp_path, str(step["run"]), env)
    assert result.returncode == 0, result.stderr
    assert [call["method"] for call in calls] == ["GET"]
    assert "op=heartbeat-lookup" in result.stdout + result.stderr


def test_selected_heartbeat_patch_failure_keeps_verified_locator(tmp_path: Path) -> None:
    """An existing verified marker that refuses PATCH stays non-fatal."""
    worker = _worker_id()
    comment_id = random.randint(10**9, 10**10)
    step = _step(RUN_WORKFLOW, "factory", "Report selected executor heartbeat")
    env = _heartbeat_env(
        worker,
        FACTORY_HEARTBEAT_COMMENT_ID=str(comment_id),
        GH_GET_BODY=_trusted_marker("heartbeat", worker, comment_id, "1"),
        GH_PATCH=THREAD_EXHAUSTED,
    )
    result, calls, github_env = _run_step(tmp_path, str(step["run"]), env)
    assert result.returncode == 0, result.stderr
    assert [call["method"] for call in calls] == ["GET", "PATCH"]
    assert "op=heartbeat-update" in result.stderr
    assert f"FACTORY_HEARTBEAT_COMMENT_ID={comment_id}" in github_env.read_text()


def test_selected_heartbeat_success_still_records_locator(tmp_path: Path) -> None:
    """Healthy GitHub keeps the existing visibility behaviour."""
    step = _step(RUN_WORKFLOW, "factory", "Report selected executor heartbeat")
    new_id = str(random.randint(10**9, 10**10))
    result, calls, github_env = _run_step(
        tmp_path, str(step["run"]), {**_heartbeat_env(_worker_id()), "GH_POST_ID": new_id},
    )
    assert result.returncode == 0, result.stderr
    assert [call["method"] for call in calls] == ["POST"]
    assert f"FACTORY_HEARTBEAT_COMMENT_ID={new_id}" in github_env.read_text()
    assert "FACTORY_REGISTRY_VISIBILITY_SKIPPED" not in result.stderr


@pytest.mark.parametrize("outcome", ["model_unavailable", "provider_quota", "model_retired_410"])
def test_terminal_reporting_survives_exhausted_registry(tmp_path: Path, outcome: str) -> None:
    """Terminal heartbeat, snapshots and attempt marker failures are warnings only."""
    step = _step(RUN_WORKFLOW, "factory", "Report terminal heartbeat")
    discovery = tmp_path / "discovery"
    discovery.write_text(f"{outcome}\tobserved during real assigned work\n")
    # The snapshot branches are keyed on registered source names; read them
    # from the step itself rather than hard-coding provider identities.
    script = str(step["run"])
    source = {
        "model_retired_410": re.search(r'\[\[ "\$SOURCE" == (\S+) && "\$attempt_outcome" == model_retired_410', script),
        "model_unavailable": re.search(r'\[\[ "\$SOURCE" == (\S+) && \( "\$attempt_outcome" == model_unavailable', script),
        "provider_quota": re.search(r'\[\[ "\$SOURCE" == (\S+) && \( "\$attempt_outcome" == model_unavailable', script),
    }[outcome]
    assert source is not None
    env = {
        **_heartbeat_env(_worker_id(), SOURCE=source.group(1)),
        "JOB_STATUS": "failure",
        "WORKER_STATUS_FILE": str(tmp_path / "missing-status"),
        "DISCOVERY_OUTCOME_FILE": str(discovery),
        "FACTORY_ATTEMPT_COMMENT_ID": "",
        "GH_POST": THREAD_EXHAUSTED,
    }
    result, calls, _ = _run_step(tmp_path, script, env)
    assert result.returncode == 0, result.stderr
    posts = [call for call in calls if call["method"] == "POST"]
    # heartbeat + run-specific snapshot + attempt marker were each attempted once.
    assert len(posts) == 3
    assert result.stderr.count("FACTORY_REGISTRY_VISIBILITY_SKIPPED") == 3
    assert "::error::" not in result.stdout + result.stderr


def test_terminal_throttled_lookup_never_duplicates_markers(tmp_path: Path) -> None:
    """Comment API throttling neither duplicates markers nor fails the job."""
    step = _step(RUN_WORKFLOW, "factory", "Report terminal heartbeat")
    env = {
        **_heartbeat_env(_worker_id(), FACTORY_HEARTBEAT_COMMENT_ID="31", FACTORY_ATTEMPT_COMMENT_ID="32"),
        "JOB_STATUS": "success",
        "WORKER_STATUS_FILE": str(tmp_path / "missing-status"),
        "DISCOVERY_OUTCOME_FILE": str(tmp_path / "missing-discovery"),
        "GH_GET": THROTTLED,
    }
    result, calls, _ = _run_step(tmp_path, str(step["run"]), env)
    assert result.returncode == 0, result.stderr
    assert {call["method"] for call in calls} == {"GET"}
    output = result.stdout + result.stderr
    assert "op=heartbeat-lookup" in output
    assert "op=attempt-lookup" in output


def test_runtime_observer_registry_write_cannot_fail_neon_completion() -> None:
    """The observer's optional marker never exits before Neon persistence."""
    data = yaml.safe_load(OBSERVER_WORKFLOW.read_text(encoding="utf-8"))
    steps = next(
        job["steps"] for job in data["jobs"].values()
        if any("issues/1093/comments" in str(step.get("run") or "") for step in job["steps"])
    )
    writer = next(step for step in steps if "issues/1093/comments" in str(step.get("run") or ""))
    script = str(writer["run"])
    assert "exit 1" not in script
    assert script.count("FACTORY_REGISTRY_VISIBILITY_SKIPPED") == 3
    persist = next(step for step in steps if step.get("name") == "Persist classified worker completion in Neon")
    assert str(persist["if"]).startswith("always()")


def _worker_failover_harness(tmp_path: Path, candidates: list[dict[str, str]]) -> str:
    """Build a bash harness around the real worker failover functions."""
    worker = WORKER_SCRIPT.read_text(encoding="utf-8")
    start = worker.index("registry_visibility() {")
    end = worker.index("\n}\n", worker.index("select_next_eligible_model() {")) + 3
    functions = worker[start:end]
    log_line = next(
        line for line in PRIMITIVES.read_text(encoding="utf-8").splitlines()
        if line.startswith("log() {")
    )
    trusted = tmp_path / "trusted"
    trusted.mkdir()
    (trusted / "candidates.json").write_text(json.dumps(candidates))
    # Fake trusted selector: returns the first candidate not yet attempted.
    (trusted / "factory_model_failover.py").write_text(
        "import json, pathlib, sys\n"
        "args = sys.argv[1:]\n"
        "tried = {args[i + 1] for i, a in enumerate(args) if a == '--attempted-pair'}\n"
        "for c in json.loads((pathlib.Path(__file__).parent / 'candidates.json').read_text()):\n"
        "    if json.dumps([c['source'], c['model']], separators=(',', ':')) not in tried:\n"
        "        print(json.dumps(c)); raise SystemExit(0)\n"
        "raise SystemExit(1)\n"
    )
    (trusted / "factory_provider_registry.py").write_text("print('{}')\n")
    # Exit 3 marks the first runtime as missing from the executable catalog.
    unavailable = candidates[0]["runtime_model"]
    (trusted / "wait-opencode-model.sh").write_text(
        f'[[ "$1" == "{unavailable}" ]] && exit 3\nexit 0\n'
    )
    home = tmp_path / "home"
    (home / ".config" / "opencode").mkdir(parents=True)
    (home / ".config" / "opencode" / "opencode.json").write_text("{}")
    return f"""
set -Eeuo pipefail
export HOME={home}
FACTORY_TRUSTED_FAILOVER_DIR={trusted}
TERMINAL_OUTCOME_FILE={tmp_path}/terminal-outcome
{log_line}
remaining() {{ echo 100000; }}
stop_work_checkpoint() {{ :; }}
start_work_checkpoint() {{ :; }}
record_terminal_outcome() {{ printf '%s\\t%s\\n' "$1" "$2" > "$TERMINAL_OUTCOME_FILE"; }}
{functions}
ORIGINAL_SOURCE="$SOURCE"
attempted_pairs=()
blocked_providers=()
# Same call the worker makes after an attributable inference failure.
if ! record_model_failover_failure "$SOURCE" "$MODEL" provider_throttle model; then
  echo 'control-plane stop' >&2
  exit 9
fi
select_next_eligible_model
echo "SELECTED source=$SOURCE model=$MODEL runtime=$RUNTIME_MODEL"
"""


def test_worker_failover_advances_and_is_attested_without_comments(tmp_path: Path) -> None:
    """Transitions survive an exhausted #1093 and are persisted from the job log."""
    from factory_provider_candidates import ADAPTERS
    from factory_state_ledger import refine_trusted_failover_models

    # Sources whose executable catalog is not pre-checked cannot model a
    # catalog miss; read that exemption from the selector instead of naming it.
    selector = WORKER_SCRIPT.read_text(encoding="utf-8").split("select_next_eligible_model() {", 1)[1]
    exempt = set(re.findall(
        r'if \[\[ "\$next_source" != (\S+) \]\]; then\n\s+candidate_status=0', selector,
    ))
    assert exempt
    sources = sorted(set(ADAPTERS) - exempt)
    assert len(sources) >= 3
    rng = random.Random()
    origin, first, second = rng.sample(sources, 3)
    candidates = [
        {"source": src, "model": f"m-{uuid.uuid4().hex[:10]}", "runtime_model": f"rt-{uuid.uuid4().hex[:10]}"}
        for src in (first, second)
    ]
    worker = _worker_id()
    origin_model = f"m-{uuid.uuid4().hex[:10]}"
    script = _worker_failover_harness(tmp_path, candidates)
    result, calls, _ = _run_step(tmp_path, script, {
        "WORKER": worker, "WORKER_ID": f"opencode-free-model-factory-{worker}",
        "SOURCE": origin, "MODEL": origin_model, "RUNTIME_MODEL": "rt-origin",
        "MODE": "issue", "NUMBER": str(random.randint(100, 9999)), "EXPECTED_HEAD": "",
        "GITHUB_RUN_NUMBER": "1", "GH_POST": THREAD_EXHAUSTED,
    })
    assert result.returncode == 0, result.stderr
    chosen = candidates[1]
    assert (
        f"SELECTED source={chosen['source']} model={chosen['model']} "
        f"runtime={chosen['runtime_model']}"
    ) in result.stdout
    # No control-plane terminal outcome was recorded for a refused comment.
    assert not (tmp_path / "terminal-outcome").exists()
    posts = [call for call in calls if call["method"] == "POST"]
    # inference failure + catalog-miss snapshots, then one fleet transition
    assert len(posts) == 3
    assert "op=model-failover" in result.stderr
    assert "op=fleet-transition" in result.stderr

    # Actions timestamps every log line; the trusted persister reads only that.
    stamp = datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%S.0000000Z")
    job_log = "\n".join(f"{stamp} {line}" for line in result.stdout.splitlines())
    refined = refine_trusted_failover_models(
        {"worker": worker, "source": chosen["source"], "model": chosen["model"]}, job_log,
    )
    assert refined["trusted_source_switch"] is True
    # The attributable inference failure keeps independent, model-scoped health.
    assert {
        "source": origin, "model": origin_model,
        "outcome": "provider_throttle", "scope": "model",
    } in refined["model_failures"]


def test_lease_validation_remains_fatal() -> None:
    """Only telemetry became optional; assignment validation still gates the job."""
    data = yaml.safe_load(RUN_WORKFLOW.read_text(encoding="utf-8"))
    factory = data["jobs"]["factory"]
    assert factory["needs"] == "validate_assignment"
    assert "always()" not in str(factory.get("if") or "")
    for step in data["jobs"]["validate_assignment"]["steps"]:
        assert step.get("continue-on-error") is not True, step.get("name")
    for name in ("Verify original active claim and live target", "Require trusted push credential"):
        steps = [s for job in data["jobs"].values() for s in job["steps"] if s.get("name") == name]
        assert steps and all(s.get("continue-on-error") is not True for s in steps)
