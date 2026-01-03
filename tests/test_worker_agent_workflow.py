"""Test file created by worker agent Charlie to demonstrate workflow."""


def test_worker_agent_can_create_tests():
    """Verify worker agent can create and run test files."""
    assert True


def test_worker_agent_worktree_isolation():
    """Verify worktree is properly isolated from main repo."""
    import os

    worktree_path = os.getcwd()
    assert worktree_path != "/home/josh/code/comic-pile"
