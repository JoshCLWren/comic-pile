"""Every factory bot-merge path dispatches Deploy Production.

A merge made with the built-in GITHUB_TOKEN fires no push or workflow_run
event, so Deploy Production never ran for factory merges (PR #3869 merged as
1319bc5a at 12:10 PM CT with no deploy). workflow_dispatch is the one event
GITHUB_TOKEN may raise, so every bot-merge path must call
``factory_dispatch_production_deploy`` and run with ``actions: write``.
"""

from __future__ import annotations

import os
import re
import shutil
import subprocess
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[1]
HELPER = ROOT / ".github/scripts/factory-dispatch-production-deploy.sh"
DISPATCH_CALL = "factory_dispatch_production_deploy"

MERGE_RE = re.compile(
    r"gh pr merge\b|/pulls/[^\s\"']*/merge\b|pulls\.merge\(|mergePullRequest|enablePullRequestAutoMerge"
)
# Merge paths that do not merge with GITHUB_TOKEN, with the reason.
EXEMPT = {
    # Local operator pipeline: merges with the operator's own token, which
    # fires push events, so Deploy Production runs on its own.
    "scripts/opencode_pipeline.sh",
    # Validator that forbids the merge string in the live worker.
    ".github/scripts/validate-free-model-factories.py",
}
SCANNED_SUFFIXES = {".sh", ".py", ".cjs", ".mjs", ".js", ".yml", ".yaml"}


def code_lines(path: Path) -> list[tuple[int, str]]:
    lines = []
    for number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
        stripped = line.lstrip()
        if stripped.startswith(("#", "//", "*")):
            continue
        lines.append((number, line))
    return lines


def bot_merge_paths() -> dict[str, list[int]]:
    found: dict[str, list[int]] = {}
    for base in (ROOT / ".github", ROOT / "scripts"):
        for path in base.rglob("*"):
            if not path.is_file() or path.suffix not in SCANNED_SUFFIXES:
                continue
            rel = path.relative_to(ROOT).as_posix()
            if "/tests/" in f"/{rel}" or rel.endswith((".test.cjs", ".test.mjs", ".test.js")):
                continue
            hits = [n for n, line in code_lines(path) if MERGE_RE.search(line)]
            if hits:
                found[rel] = hits
    return found


def test_known_bot_merge_paths_are_all_found() -> None:
    paths = set(bot_merge_paths())
    assert {
        ".github/workflows/factory-ready-merge-drain.yml",
        ".github/workflows/fixed-model-factory-dispatch.yml",
        ".github/scripts/free-model-factory-worker-primitives.sh",
        ".github/scripts/nvidia-factory-worker.sh",
        ".github/scripts/omniroute-factory-worker.sh",
    } <= paths


def test_every_bot_merge_path_dispatches_deploy_production() -> None:
    missing = [
        rel
        for rel in bot_merge_paths()
        if rel not in EXEMPT and DISPATCH_CALL not in (ROOT / rel).read_text(encoding="utf-8")
    ]
    assert not missing, (
        "These files merge PRs but never dispatch Deploy Production; a GITHUB_TOKEN merge "
        f"fires no push event, so call {DISPATCH_CALL} after the merge: {missing}"
    )


def test_worker_merges_dispatch_right_after_the_merge() -> None:
    for rel, hits in bot_merge_paths().items():
        if rel in EXEMPT or not rel.endswith(".sh"):
            continue
        lines = (ROOT / rel).read_text(encoding="utf-8").splitlines()
        for number in hits:
            following = "\n".join(lines[number : number + 3])
            assert DISPATCH_CALL in following, (
                f"{rel}:{number} merges without dispatching the deploy"
            )


def _effective_actions_permission(workflow: dict, job: dict) -> str | None:
    perms = job.get("permissions", workflow.get("permissions"))
    if perms == "write-all":
        return "write"
    if isinstance(perms, dict):
        return perms.get("actions")
    return None


def test_bot_merge_workflow_jobs_can_dispatch_workflows() -> None:
    for rel in bot_merge_paths():
        if not rel.startswith(".github/workflows/"):
            continue
        workflow = yaml.safe_load((ROOT / rel).read_text(encoding="utf-8"))
        for name, job in workflow["jobs"].items():
            runs = "\n".join(step.get("run", "") for step in job.get("steps", []))
            if not MERGE_RE.search(runs):
                continue
            assert _effective_actions_permission(workflow, job) == "write", (
                f"{rel} job {name} needs actions: write"
            )
            assert "trap dispatch_deploy_after_merges EXIT" in runs, (
                f"{rel} job {name} must dispatch once per run"
            )


# --- behaviour: drains dispatch once, after the last merge ---------------------


def _step_script(workflow_rel: str, step_name: str) -> str:
    workflow = yaml.safe_load((ROOT / workflow_rel).read_text(encoding="utf-8"))
    for job in workflow["jobs"].values():
        for step in job.get("steps", []):
            if step.get("name") == step_name:
                return step["run"]
    raise AssertionError(f"{step_name} not found in {workflow_rel}")


def _write_exe(path: Path, body: str) -> None:
    path.write_text("#!/usr/bin/env bash\n" + body, encoding="utf-8")
    path.chmod(0o755)


def _run_drain(tmp_path: Path, workflow_rel: str, *, gate: str = "pass", prs: int = 2) -> list[str]:
    work = tmp_path / "work"
    (work / ".github/scripts").mkdir(parents=True)
    shutil.copy(HELPER, work / ".github/scripts" / HELPER.name)
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    log = tmp_path / "calls.log"
    rows = "".join(f"{100 + i}\\tsha{100 + i}\\tfactory,factory:ready\\n" for i in range(prs))
    _write_exe(
        bin_dir / "gh",
        f"""echo "gh $*" >> {log}
case "$1 $2" in
  "api --paginate"|"pr list") printf '{rows}' ;;
  "pr merge") exit 0 ;;
  "pr view") echo MERGED ;;
  "workflow run") exit 0 ;;
esac
""",
    )
    _write_exe(
        bin_dir / "python3",
        f"""case "$2" in
  authorized) pr="$4"; echo "{{\\"authorized\\":true,\\"head\\":\\"sha$pr\\"}}" ;;
  gates) echo '{{"decision":"{gate}","reason":"test"}}' ;;
  *) exit 0 ;;
esac
""",
    )
    env = {
        **os.environ,
        "PATH": f"{bin_dir}{os.pathsep}{os.environ['PATH']}",
        "GITHUB_REPOSITORY": "JoshCLWren/comic-pile",
        "RUNNER_TEMP": str(tmp_path),
        "DEPLOY_FROZEN": "false",
        "GH_TOKEN": "test",
    }
    script = _step_script(workflow_rel, "Drain exact-head ready factory PRs")
    result = subprocess.run(
        ["bash", "-c", script], cwd=work, env=env, text=True, capture_output=True, check=False
    )
    assert result.returncode == 0, result.stdout + result.stderr
    return log.read_text(encoding="utf-8").splitlines() if log.exists() else []


DRAINS = (
    ".github/workflows/factory-ready-merge-drain.yml",
    ".github/workflows/fixed-model-factory-dispatch.yml",
)


def test_drains_dispatch_one_deploy_after_the_last_merge(tmp_path: Path) -> None:
    for index, rel in enumerate(DRAINS):
        calls = _run_drain(tmp_path / str(index), rel)
        merges = [i for i, call in enumerate(calls) if call.startswith("gh pr merge")]
        dispatches = [i for i, call in enumerate(calls) if call.startswith("gh workflow run")]
        assert len(merges) == 2, (rel, calls)
        assert len(dispatches) == 1, (rel, calls)
        assert dispatches[0] > merges[-1], (rel, calls)
        assert (
            "gh workflow run deploy-production.yml --repo JoshCLWren/comic-pile --ref main -f source=factory-merge"
            in calls[dispatches[0]]
        )
        assert "merged 2 PR(s)" in calls[dispatches[0]]


def test_drains_without_a_merge_do_not_dispatch(tmp_path: Path) -> None:
    for index, rel in enumerate(DRAINS):
        calls = _run_drain(tmp_path / f"retry{index}", rel, gate="retry")
        assert not [call for call in calls if call.startswith("gh pr merge")]
        assert not [call for call in calls if call.startswith("gh workflow run")], (rel, calls)
        empty = _run_drain(tmp_path / f"empty{index}", rel, prs=0)
        assert not [call for call in empty if call.startswith("gh workflow run")], (rel, empty)


# --- helper and deploy workflow -------------------------------------------------


def _run_helper(
    tmp_path: Path, gh_exit: int, extra_env: dict[str, str] | None = None
) -> tuple[int, str, str]:
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir(parents=True)
    log = tmp_path / "gh.log"
    _write_exe(bin_dir / "gh", f'echo "gh $*" >> {log}\nexit {gh_exit}\n')
    env = {**os.environ, "PATH": f"{bin_dir}{os.pathsep}{os.environ['PATH']}", **(extra_env or {})}
    result = subprocess.run(
        ["bash", "-c", f'source {HELPER}; {DISPATCH_CALL} "test merge"; echo rc=$?'],
        env=env,
        text=True,
        capture_output=True,
        check=True,
    )
    return result.returncode, result.stdout + result.stderr, log.read_text() if log.exists() else ""


def test_helper_dispatches_deploy_on_main_and_never_fails_the_caller(tmp_path: Path) -> None:
    _, out, calls = _run_helper(tmp_path / "ok", 0)
    assert "rc=0" in out
    assert calls.strip() == (
        "gh workflow run deploy-production.yml --repo JoshCLWren/comic-pile --ref main "
        "-f source=factory-merge -f reason=test merge"
    )
    _, out, _ = _run_helper(tmp_path / "fail", 1)
    assert "rc=0" in out and "::warning::Unable to dispatch Deploy Production" in out
    _, out, calls = _run_helper(tmp_path / "off", 0, {"FACTORY_DEPLOY_DISPATCH": "off"})
    assert "rc=0" in out and calls == ""


def test_deploy_production_dedupes_factory_dispatches_and_serializes_runs() -> None:
    text = (ROOT / ".github/workflows/deploy-production.yml").read_text(encoding="utf-8")
    workflow = yaml.safe_load(text)
    triggers = workflow[True] if True in workflow else workflow["on"]
    assert triggers["workflow_dispatch"]["inputs"]["source"]["default"] == "manual"
    assert workflow["concurrency"] == {"group": "vercel-production", "cancel-in-progress": False}
    assert "DISPATCH_SOURCE: ${{ github.event.inputs.source || 'manual' }}" in text
    assert (
        '"$GITHUB_EVENT_NAME" == "workflow_dispatch" && "$DISPATCH_SOURCE" != "factory-merge"'
        in text
    )
    # Every run deploys the checked-out tip of main, never an event SHA.
    preflight = workflow["jobs"]["preflight"]
    assert preflight["steps"][0]["with"]["ref"] == "main"
