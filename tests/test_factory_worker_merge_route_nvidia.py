"""Regression coverage for the NVIDIA and OmniRoute worker merge call sites.

Issue #4081: the non-``kilo-auto`` worker merge route must use the canonical
exact-head route. These tests execute the real shell call sites for both
changed workers, not just the standalone dependency parser.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from tests.test_factory_worker_merge_route import (
    HEAD,
    PR,
    PRIMITIVES,
    _merge_calls,
    _run_call_site,
    _worker_merge_call_site,
)

NVIDIA_SCRIPT = Path(".github/scripts/nvidia-factory-worker.sh")
OMNIROUTE_SCRIPT = Path(".github/scripts/omniroute-factory-worker.sh")


@pytest.mark.parametrize(
    "script_path",
    [PRIMITIVES, NVIDIA_SCRIPT, OMNIROUTE_SCRIPT],
)
def test_worker_merge_call_site_uses_canonical_route(
    tmp_path: Path, script_path: Path
) -> None:
    """Every changed worker call site uses the canonical route, never raw close."""
    block = _worker_merge_call_site(script_path)
    assert "factory_merge_with_canonical_gates" in block
    assert "gh issue close" not in block
    calls, _ = _run_call_site(tmp_path, script_path)
    assert _merge_calls(calls) == [
        f"gh pr merge {PR} --merge --match-head-commit {HEAD} --delete-branch"
    ]
    assert not [call for call in calls if call.startswith("gh issue close")]


@pytest.mark.parametrize("script_path", [NVIDIA_SCRIPT, OMNIROUTE_SCRIPT])
def test_worker_merge_call_site_refusal_releases_without_merging(
    tmp_path: Path, script_path: Path
) -> None:
    """A refused controller decision releases the PR and never merges."""
    calls, _ = _run_call_site(tmp_path, script_path, FAKE_GATE_DECISION="retry")
    assert _merge_calls(calls) == []
    assert [call for call in calls if call.startswith("release ")] == [
        f"release {PR} factory/87-4081-opencode-free factory:review gate-denied"
    ]
    assert any(
        "decision=retry" in call
        for call in calls
        if call.startswith("log ")
    )


@pytest.mark.parametrize("script_path", [NVIDIA_SCRIPT, OMNIROUTE_SCRIPT])
def test_worker_merge_call_site_blocked_closure_leaves_issue_open(
    tmp_path: Path, script_path: Path
) -> None:
    """A blocked closure is reported and never treated as acceptance."""
    calls, _ = _run_call_site(
        tmp_path, script_path, FAKE_CLOSURE_OUTCOME="open-dependency: #4016"
    )
    assert len(_merge_calls(calls)) == 1
    assert any("issue left open" in call for call in calls if call.startswith("log "))
    assert not [call for call in calls if call.startswith("gh issue close")]
    assert not [call for call in calls if "ralph-status:done" in call]
