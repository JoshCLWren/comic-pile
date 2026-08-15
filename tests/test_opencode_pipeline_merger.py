import pathlib

def test_merger_rebase_logic_present():
    script_path = pathlib.Path('scripts/opencode_pipeline.sh')
    content = script_path.read_text()
    # Ensure rebase command is used when strategy is rebase for worktree path
    assert 'if [[ "$STRATEGY" == "rebase" ]]; then' in content
    assert 'git -C "$wt_path" rebase origin/main' in content
    # Ensure rebase command is also used for scratch worktree
    assert 'git -C "$tmpwt" rebase origin/main' in content
