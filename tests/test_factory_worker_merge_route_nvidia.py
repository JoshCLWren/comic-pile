import pytest
from pathlib import Path
from tests.test_factory_worker_merge_route import (_worker_merge_call_site, _run_call_site, PR, HEAD, PRIMITIVES, _merge_calls)

# Test that nvidia-factory-worker.sh behaves same as free-model-factory-worker-primitives.sh

@pytest.mark.parametrize(
    "script_path",
    [
        PRIMITIVES,
        Path(".github/scripts/nvidia-factory-worker.sh"),
    ],
)
def test_worker_merge_call_site_with_both_scripts(tmp_path, script_path):
    block = _worker_merge_call_site(script_path)
    assert "factory_merge_with_canonical_gates" in block
    assert "gh issue close" not in block
    calls, _ = _run_call_site(tmp_path, script_path)
    assert _merge_calls(calls) == [f"gh pr merge {PR} --merge --match-head-commit {HEAD} --delete-branch"]
    assert not [c for c in calls if c.startswith("gh issue close")]
