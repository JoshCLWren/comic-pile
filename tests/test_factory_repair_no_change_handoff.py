"""Regression coverage for repair-no-change factory stage handoffs."""
from __future__ import annotations

import os
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PRIMITIVES = ROOT / ".github" / "scripts" / "free-model-factory-worker-primitives.sh"


def release_stage(reason: str, fallback_stage: str) -> str:
    """Run the release primitive with a stale ready label and capture its handoff stage."""
    script = f"""
source <(sed '/^ensure_owner_label$/,$d' \"{PRIMITIVES}\")
current_stage() {{ printf '%s\\n' 'factory:ready'; }}
replace_labels() {{ printf '%s\\n' \"$3\"; }}
gh() {{ :; }}
log() {{ :; }}
release_target 2010 \"{fallback_stage}\" \"{reason}\" pr
"""
    env = os.environ.copy()
    env.update(
        {
            "FACTORY_WORKER": "45",
            "FACTORY_SOURCE": "opencode-free",
            "FACTORY_MODEL": "test-model",
            "FACTORY_RUNTIME_MODEL": "test-runtime",
        }
    )
    completed = subprocess.run(
        ["bash", "-c", script],
        cwd=ROOT,
        env=env,
        text=True,
        capture_output=True,
        check=True,
    )
    return completed.stdout.strip()


def test_repair_no_change_ready_handoff_cannot_preserve_false_ready() -> None:
    """A no-change READY token still requires independent semantic review."""
    assert release_stage("repair-no-change-ready-handoff", "factory:review") == "factory:review"


def test_repair_no_persisted_change_handoff_preserves_assigned_repair_stage() -> None:
    """A no-change repair without READY cannot inherit an accidental ready label."""
    assert (
        release_stage("repair-no-persisted-change-handoff", "factory:changes-requested")
        == "factory:changes-requested"
    )


def test_other_release_handoffs_still_preserve_current_stage() -> None:
    """The repair-specific guard does not change ordinary lease-release semantics."""
    assert release_stage("repairs-pushed-handoff", "factory:review") == "factory:ready"
