"""Regression coverage for repair-no-change factory stage handoffs."""
from __future__ import annotations

import os
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PRIMITIVES = ROOT / ".github" / "scripts" / "free-model-factory-worker-primitives.sh"


def release_stage(
    reason: str,
    fallback_stage: str,
    *,
    current_stage: str = "factory:ready",
    no_diff_limit: int = 1,
    existing_no_diff_comments: int = 5,
) -> str:
    """Run the release primitive and capture the stage passed to replace_labels.

    The gh stub returns enough no-diff comments to exceed FACTORY_NO_DIFF_RETRY_LIMIT
    so a regression that rewrites exhaustion to factory:blocked is observable.
    """
    script = f"""
source <(sed '/^ensure_owner_label$/,$d' \"{PRIMITIVES}\")
current_stage() {{ printf '%s\\n' '{current_stage}'; }}
replace_labels() {{ printf '%s\\n' \"$3\"; }}
gh() {{
  if [[ \"$1\" == api && \"$*\" == *comments* ]]; then
    python3 -c 'import json,sys; n=int(sys.argv[1]); print(json.dumps([[{{\"body\":\"<!-- comic-pile-factory-claim-released-v3:pr-2010:w:1:repair-no-persisted-change-handoff -->\"}}]*n]))' {existing_no_diff_comments}
    return 0
  fi
  return 0
}}
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
            "FACTORY_NO_DIFF_RETRY_LIMIT": str(no_diff_limit),
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


def test_repair_no_diff_retry_exhaustion_keeps_changes_requested_not_blocked() -> None:
    """Retry exhaustion must not rewrite a truthful repair stage to factory:blocked."""
    assert (
        release_stage(
            "repair-no-persisted-change-handoff",
            "factory:changes-requested",
            current_stage="factory:changes-requested",
        )
        == "factory:changes-requested"
    )


def test_review_no_diff_retry_exhaustion_keeps_review_not_blocked() -> None:
    """A review/head-change no-diff handoff keeps factory:review plus unowned."""
    assert (
        release_stage(
            "repair-no-persisted-change-handoff",
            "factory:review",
            current_stage="factory:review",
        )
        == "factory:review"
    )


def test_primitives_do_not_rewrite_no_diff_exhaustion_as_blocked() -> None:
    """Release accounting stays in markers; factory:blocked remains a genuine blocker."""
    text = PRIMITIVES.read_text(encoding="utf-8")
    assert "quarantining" not in text
    assert "stage='factory:blocked'" not in text
    assert "comic-pile-factory-claim-released-v3" in text
    assert "no-persisted-change-handoff" in text
