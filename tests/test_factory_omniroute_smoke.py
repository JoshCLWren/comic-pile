"""Executable coverage for Entry OpenCode smoke plus the capacity bridge.

These tests run the extracted smoke script with a fake ``timeout`` so a
primary hang (exit 124) can be proven to reach the TEMPORARY auto/best-free
retry. The real defect (Factory 11 run 34029915567) was ``set -e`` aborting
before ``--next-after-smoke-failure``.
"""

from __future__ import annotations

import os
import stat
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SMOKE = ROOT / ".github" / "scripts" / "factory_omniroute_smoke.sh"
WORKFLOW = ROOT / ".github" / "workflows" / "free-model-factory-run.yml"

FAKE_TIMEOUT = r"""#!/usr/bin/env bash
set -Euo pipefail
# Ignore GNU timeout flags and inspect the OpenCode model only.
model=''
prev=''
for arg in "$@"; do
  if [[ "$prev" == "-m" ]]; then
    model="$arg"
    break
  fi
  prev="$arg"
done
case "$model" in
  *coding:free*)
    echo '> build · auto/coding:free'
    exit 124
    ;;
  *best-free*)
    if [[ "${FAKE_TIMEOUT_BRIDGE_STATUS:-0}" != 0 ]]; then
      echo '> build · auto/best-free'
      echo 'all targets were skipped by pre-dispatch filters'
      exit "${FAKE_TIMEOUT_BRIDGE_STATUS}"
    fi
    echo 'FIXED_MODEL_OPENCODE_OK'
    exit 0
    ;;
  *)
    echo "unexpected smoke model: ${model}" >&2
    exit 9
    ;;
esac
"""

FAKE_OPENCODE = r"""#!/usr/bin/env bash
echo "real opencode must not run during factory smoke tests: $*" >&2
exit 9
"""


def _write_executable(path: Path, text: str) -> Path:
    path.write_text(text, encoding="utf-8")
    path.chmod(path.stat().st_mode | stat.S_IEXEC)
    return path


def _run_smoke(
    tmp_path: Path,
    *,
    bridge_status: int | None = None,
    extra_env: dict[str, str] | None = None,
) -> subprocess.CompletedProcess[str]:
    """Run the extracted smoke script against a hang-or-succeed timeout stub."""
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    _write_executable(bin_dir / "timeout", FAKE_TIMEOUT)
    _write_executable(bin_dir / "opencode", FAKE_OPENCODE)
    runner_temp = tmp_path / "runner"
    runner_temp.mkdir()
    github_output = tmp_path / "github-output"
    github_output.write_text("", encoding="utf-8")
    env = os.environ.copy()
    env.update(
        {
            "PATH": f"{bin_dir}{os.pathsep}{env.get('PATH', '')}",
            "RUNTIME_MODEL": "omniroute/auto/coding:free",
            "LANE_MODEL": "auto/coding:free",
            "RUNNER_TEMP": str(runner_temp),
            "GITHUB_OUTPUT": str(github_output),
            "FACTORY_SMOKE_PRIMARY_TIMEOUT_SECONDS": "2",
            "FACTORY_SMOKE_BRIDGE_TIMEOUT_SECONDS": "2",
            "FACTORY_SMOKE_KILL_AFTER_SECONDS": "1",
        }
    )
    if bridge_status is not None:
        env["FAKE_TIMEOUT_BRIDGE_STATUS"] = str(bridge_status)
    if extra_env:
        env.update(extra_env)
    return subprocess.run(
        ["bash", str(SMOKE)],
        cwd=ROOT,
        text=True,
        capture_output=True,
        check=False,
        env=env,
    )


def _outputs(tmp_path: Path) -> dict[str, str]:
    raw = (tmp_path / "github-output").read_text(encoding="utf-8")
    return dict(line.split("=", 1) for line in raw.splitlines() if "=" in line)


def test_workflow_delegates_smoke_to_extracted_script() -> None:
    """The runner must call the testable smoke script, not inline set -e."""
    workflow = WORKFLOW.read_text(encoding="utf-8")
    smoke_step = workflow.split(
        "- name: Smoke selected OmniRoute route through OpenCode", maxsplit=1
    )[1].split("- name: Smoke Kilo Auto Free through Kilo CLI", maxsplit=1)[0]
    assert "factory_omniroute_smoke.sh" in smoke_step
    smoke_once_body = SMOKE.read_text(encoding="utf-8").split(
        "smoke_once()", maxsplit=1
    )[1].split("is_native_intent=false", maxsplit=1)[0]
    assert not any(
        line.strip() == "set -e" or line.strip().startswith("set -e ")
        for line in smoke_once_body.splitlines()
    )


def test_primary_timeout_124_attempts_capacity_bridge(tmp_path: Path) -> None:
    """A hung coding-intent smoke must still request the best-free retry."""
    result = _run_smoke(tmp_path, bridge_status=1)
    combined = f"{result.stdout}\n{result.stderr}"
    assert result.returncode == 1
    assert "TEMPORARY OmniRoute capacity bridge:" in combined
    assert "auto/coding:free skipped/timed out; retrying auto/best-free" in combined
    assert "> build · auto/coding:free" in combined
    assert "> build · auto/best-free" in combined
    assert "TEMPORARY capacity bridge succeeded" not in combined
    assert _outputs(tmp_path)["override"] == ""


def test_capacity_bridge_success_uses_best_free(tmp_path: Path) -> None:
    """A successful best-free retry becomes the session route."""
    result = _run_smoke(tmp_path)
    combined = f"{result.stdout}\n{result.stderr}"
    assert result.returncode == 0
    assert "TEMPORARY OmniRoute capacity bridge:" in combined
    assert "TEMPORARY capacity bridge succeeded on auto/best-free" in combined
    outputs = _outputs(tmp_path)
    assert outputs["model"] == "auto/best-free"
    assert outputs["runtime_model"] == "omniroute/auto/best-free"
    assert outputs["override"] == "auto/best-free"
    effective = (tmp_path / "runner" / "factory-effective-model").read_text(
        encoding="utf-8"
    )
    assert effective.strip() == "auto/best-free"


def test_capacity_bridge_disabled_does_not_retry(tmp_path: Path) -> None:
    """FACTORY_OMNIROUTE_CAPACITY_BRIDGE=off leaves a coding timeout unretried."""
    result = _run_smoke(
        tmp_path,
        extra_env={"FACTORY_OMNIROUTE_CAPACITY_BRIDGE": "off"},
    )
    combined = f"{result.stdout}\n{result.stderr}"
    assert result.returncode == 1
    assert "TEMPORARY OmniRoute capacity bridge:" not in combined
    assert "retrying auto/best-free" not in combined
    assert "> build · auto/coding:free" in combined
    assert "> build · auto/best-free" not in combined
    assert _outputs(tmp_path)["model"] == "auto/coding:free"
    assert _outputs(tmp_path)["override"] == ""


def test_primary_smoke_uses_shorter_timeout_than_legacy_180s() -> None:
    """Hung coding:free must fail fast enough to leave budget for one retry."""
    smoke = SMOKE.read_text(encoding="utf-8")
    assert 'PRIMARY_TIMEOUT="${FACTORY_SMOKE_PRIMARY_TIMEOUT_SECONDS:-90}"' in smoke
    assert 'BRIDGE_TIMEOUT="${FACTORY_SMOKE_BRIDGE_TIMEOUT_SECONDS:-90}"' in smoke
    assert "timeout --signal=TERM --kill-after=10s 180s" not in smoke
    assert 'smoke_once "$RUNTIME_MODEL" "$SMOKE_LOG" "$PRIMARY_TIMEOUT" || status=$?' in smoke
    assert (
        'smoke_once "omniroute/${bridge}" "$SMOKE_LOG" "$BRIDGE_TIMEOUT" || status=$?'
        in smoke
    )
