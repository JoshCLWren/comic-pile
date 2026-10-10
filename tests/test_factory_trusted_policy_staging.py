"""Exercise the trusted worker policy bundle outside the source checkout."""

from __future__ import annotations

import shutil
import subprocess
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def test_staged_worker_policy_imports_only_pinned_eligibility(tmp_path: Path) -> None:
    """The worker must not depend on /scripts or an untrusted PR worktree."""
    worker = (ROOT / ".github/scripts/free-model-factory-worker.sh").read_text()
    assert 'cp scripts/factory_eligibility.py "$trusted_dir/factory_eligibility.py"' in worker

    staged = tmp_path / "trusted"
    staged.mkdir()
    for name in ("factory_work_policy.py", "factory_review_policy.py"):
        shutil.copy2(ROOT / ".github/scripts" / name, staged / name)
    shutil.copy2(ROOT / "scripts/factory_eligibility.py", staged / "factory_eligibility.py")

    check = """
import pathlib
import sys
sys.path.insert(0, sys.argv[1])
import factory_work_policy
canonical = pathlib.Path(sys.argv[1], 'factory_eligibility.py').resolve()
assert pathlib.Path(factory_work_policy.eligibility.__file__).resolve() == canonical
assert factory_work_policy.eligibility.is_manual_only('<!-- factory-execution:manual-only -->')
"""
    result = subprocess.run(
        [sys.executable, "-I", "-c", check, str(staged)],
        cwd=tmp_path,
        text=True,
        capture_output=True,
        check=False,
        timeout=20,
    )
    assert result.returncode == 0, result.stderr


def test_stage_does_not_copy_policy_from_pr_checkout() -> None:
    worker = (ROOT / ".github/scripts/free-model-factory-worker.sh").read_text()
    staging = worker.split("stage_trusted_review_controller() {", 1)[1].split("\n}", 1)[0]
    assert staging.index('cp scripts/factory_eligibility.py') < staging.index('TRUSTED_REVIEW_CONTROLLER=')
    assert '[[ -z "${TRUSTED_REVIEW_CONTROLLER:-}" ]] || return 0' in staging
