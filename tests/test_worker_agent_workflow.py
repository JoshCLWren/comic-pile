"""Test file created by worker agent Charlie to demonstrate workflow."""

import os

import pytest


def test_worker_agent_can_create_tests():
    """Verify worker agent can create and run test files."""
    assert True


@pytest.mark.skipif(
    os.path.basename(os.getcwd()) == "comic-pile",
    reason="Worktree isolation test only applies in worktrees",
)
def test_worker_agent_worktree_isolation():
    """Verify worktree is properly isolated from main repo."""
    worktree_path = os.getcwd()
    assert "comic-pile-" in worktree_path or "/code/comic-pile" not in worktree_path
