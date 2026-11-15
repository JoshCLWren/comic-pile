"""Git-backed regression tests for unreviewed worker recovery checkpoints."""
from __future__ import annotations

import os
from pathlib import Path
import signal
import subprocess
import time

CHECKPOINT = Path(__file__).resolve().parents[1] / '.github/scripts/factory-work-checkpoint.sh'


def git(cwd: Path, *args: str) -> str:
    result = subprocess.run(['git', *args], cwd=cwd, check=True, text=True, capture_output=True)
    return result.stdout.strip()


def repo(tmp_path: Path) -> Path:
    remote, work = tmp_path / 'remote.git', tmp_path / 'work'
    git(tmp_path, 'init', '--bare', str(remote))
    work.mkdir()
    git(work, 'init', '-b', 'main')
    git(work, 'config', 'user.name', 'Checkpoint Test')
    git(work, 'config', 'user.email', 'checkpoint@example.test')
    (work / '.gitignore').write_text('.env\n')
    (work / 'tracked.rs').write_text('fn original() {}\n')
    git(work, 'add', '.')
    git(work, 'commit', '-m', 'base')
    git(work, 'remote', 'add', 'origin', str(remote))
    git(work, 'push', 'origin', 'main')
    git(work, 'switch', '-c', 'factory/42-123-test')
    return work


def start(
    work: Path, *, run_id: str = '123456', handoff: Path | None = None,
    mode: str = 'issue', issue: str = '',
) -> subprocess.Popen[str]:
    env = {
        **os.environ, 'FACTORY_CHECKPOINT_INTERVAL_SECONDS': '1',
        'FACTORY_CHECKPOINT_MODEL': 'provider/Exact.Model:free',
        'FACTORY_CHECKPOINT_RUNTIME_MODEL': 'runtime/Exact.Model:free',
        'FACTORY_CHECKPOINT_ISSUE': issue,
        'TRUSTED_CHECKPOINT_HANDOFF': str(handoff) if handoff else '',
        'GITHUB_REPOSITORY': 'test/checkpoint',
    }
    return subprocess.Popen(
        ['bash', str(CHECKPOINT), mode, '123', '42', run_id],
        cwd=work, env=env, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True,
    )


def remote_ref(work: Path, run_id: str = '123456') -> str:
    ref = f'refs/heads/factory/work-checkpoints/issue-123/provider-exact-model-free/{run_id}'
    response = git(work, 'ls-remote', '--heads', 'origin', ref)
    return response.split()[0] if response else ''


def wait_for_ref(work: Path, *, run_id: str = '123456') -> str:
    for _ in range(60):
        sha = remote_ref(work, run_id)
        if sha:
            return sha
        time.sleep(.1)
    raise AssertionError('model work was not durably committed to remote checkpoint')


def stop(proc: subprocess.Popen[str]) -> None:
    if proc.poll() is None:
        proc.send_signal(signal.SIGUSR1)
    _, error = proc.communicate(timeout=10)
    assert proc.returncode == 0, error


def test_checkpoint_saves_new_and_tracked_code_without_touching_agent_index(tmp_path: Path) -> None:
    work = repo(tmp_path)
    base = git(work, 'rev-parse', 'HEAD')
    (work / '.env').write_text('TOKEN=private\n')
    (work / 'tracked.rs').write_text('fn edited() {}\n')
    (work / 'new.rs').write_text('fn added() {}\n')
    proc = start(work)
    try:
        sha = wait_for_ref(work)
        assert git(work, 'rev-parse', 'HEAD') == base
        metadata = git(work, 'show', '-s', '--format=%B', sha)
        assert 'Issue: 123' in metadata
        assert 'Model: provider/Exact.Model:free' in metadata
        assert 'Runtime-model: runtime/Exact.Model:free' in metadata
        assert f'Base-commit: {base}' in metadata
        assert git(work, 'status', '--porcelain') == 'M tracked.rs\n?? new.rs'
        assert git(work, 'show', f'{sha}:new.rs') == 'fn added() {}'
        assert git(work, 'show', f'{sha}:tracked.rs') == 'fn edited() {}'
        assert '.env' not in git(work, 'ls-tree', '-r', '--name-only', sha).splitlines()
        (work / 'tracked.rs').write_text('fn second_edit() {}\n')
        proc.send_signal(signal.SIGUSR2)
        for _ in range(60):
            if remote_ref(work) != sha:
                break
            time.sleep(.1)
        else:
            raise AssertionError('model-exit flush did not save pending edits')
        assert proc.poll() is None
        # A correction model can still edit after the initial model exits.
        (work / 'tracked.rs').write_text('fn correction_edit() {}\n')
        stop(proc)
        sha2 = remote_ref(work)
        assert sha2 != sha
        assert git(work, 'show', f'{sha2}:tracked.rs') == 'fn correction_edit() {}'
        assert git(work, 'rev-parse', 'HEAD') == base
    finally:
        if proc.poll() is None:
            proc.kill()
            proc.wait()


def test_checkpoint_ref_is_only_created_for_changes_on_assigned_branch(tmp_path: Path) -> None:
    work = repo(tmp_path)
    proc = start(work, run_id='678901')
    try:
        time.sleep(1.4)
        stop(proc)
        assert remote_ref(work, '678901') == ''
    finally:
        if proc.poll() is None:
            proc.kill()
            proc.wait()

    (work / 'new.rs').write_text('fn created() {}\n')
    proc = start(work, run_id='678902')
    try:
        sha = wait_for_ref(work, run_id='678902')
        git(work, 'switch', '-c', 'some-other-branch')
        (work / 'new.rs').write_text('fn wrong_branch() {}\n')
        stop(proc)
        assert remote_ref(work, '678902') == sha
        assert git(work, 'show', f'{sha}:new.rs') == 'fn created() {}'
    finally:
        if proc.poll() is None:
            proc.kill()
            proc.wait()


def test_draft_publication_retries_without_another_edit(tmp_path: Path) -> None:
    """An API failure after a successful snapshot must not strand its branch."""
    work = repo(tmp_path)
    attempts = tmp_path / 'attempts'
    helper = tmp_path / 'handoff.py'
    helper.write_text(
        'from pathlib import Path\n'
        f'path = Path({str(attempts)!r})\n'
        'count = int(path.read_text()) + 1 if path.exists() else 1\n'
        'path.write_text(str(count))\n'
        'raise SystemExit(1 if count == 1 else 0)\n'
    )
    (work / 'tracked.rs').write_text('fn edited() {}\n')
    proc = start(work, handoff=helper)
    try:
        sha = wait_for_ref(work)
        for _ in range(60):
            if attempts.exists() and int(attempts.read_text()) >= 2:
                break
            time.sleep(.1)
        else:
            raise AssertionError('draft publication was not retried after API failure')
        stop(proc)
        assert remote_ref(work) == sha
    finally:
        if proc.poll() is None:
            proc.kill()
            proc.wait()


def test_pr_repair_branch_names_original_issue_and_model(tmp_path: Path) -> None:
    """PR identifiers must not masquerade as the issue being repaired."""
    work = repo(tmp_path)
    (work / 'tracked.rs').write_text('fn repair() {}\n')
    proc = start(work, mode='pr', issue='4853')
    ref = 'refs/heads/factory/work-checkpoints/issue-4853/provider-exact-model-free/123456'
    try:
        for _ in range(60):
            if git(work, 'ls-remote', '--heads', 'origin', ref):
                break
            time.sleep(.1)
        else:
            raise AssertionError('PR recovery branch did not identify original issue/model')
        stop(proc)
        sha = git(work, 'ls-remote', '--heads', 'origin', ref).split()[0]
        message = git(work, 'show', '-s', '--format=%B', sha)
        assert 'pr #123' in message
        assert 'Issue: 4853' in message
        assert 'Model: provider/Exact.Model:free' in message
    finally:
        if proc.poll() is None:
            proc.kill()
            proc.wait()


def function(name: str) -> str:
    """Extract a trusted wrapper function without starting a factory session."""
    source = (CHECKPOINT.parent / 'free-model-factory-worker-primitives.sh').read_text()
    offset = source.index(f'\n{name}() {{') + 1
    return source[offset:source.index('\n}\n', offset) + 3]


def test_finalize_adopts_saved_ancestry_and_updates_same_pr_without_reapplying(tmp_path: Path) -> None:
    """Real Git finalization validates all saved bytes and never opens another PR."""
    work = repo(tmp_path)
    base = git(work, 'rev-parse', 'HEAD')
    (work / 'tracked.rs').write_text('fn persisted() {}\n')
    proc = start(work)
    try:
        saved = wait_for_ref(work)
        stop(proc)
    finally:
        if proc.poll() is None:
            proc.kill()
            proc.wait()
    branch = 'factory/work-checkpoints/issue-123/provider-exact-model-free/123456'
    state = tmp_path / 'saved-ref'
    state.write_text(f'{saved}\n{branch}\n')
    script = '\n'.join([
        'set -Eeuo pipefail', f'EXPECTED_HEAD={base}', 'MODE=issue BRANCH=old WORKER=42',
        f'CHECKPOINT_REF_FILE={state}', 'GITHUB_REPOSITORY=test/checkpoint',
        'log() { echo "$*" >&2; }',
        # Clean worktree after adoption must still validate the entire initial diff.
        'reject_out_of_scope_diff() { [[ "$3" == "$EXPECTED_HEAD" ]]; }',
        'factory_run_fast_checks() { git diff "$1" HEAD -- tracked.rs | rg "fn persisted" >&2; }',
        'find_overlapping_factory_pr() { printf "{}"; }',
        'factory_advance_display() { printf test; }',
        'factory_push_credential() { printf "pat\\tplaceholder"; }',
        'factory_git_push() { shift 2; git push "$@"; }',
        'gh() { [[ "$*" == "pr list "* ]] || return 17; printf 5152; }',
        function('adopt_persisted_work'), function('_persist_issue_pr_untraced'),
        'adopt_persisted_work', '[[ -z "$(git status --porcelain)" ]]',
        '_persist_issue_pr_untraced 123 "$BRANCH"',
    ])
    result = subprocess.run(['bash', '-c', script], cwd=work, text=True, capture_output=True)
    assert result.returncode == 0, result.stderr
    assert result.stdout.strip() == '5152'
    head = remote_ref(work)
    assert head != saved
    assert git(work, 'rev-parse', f'{head}^') == saved
    assert git(work, 'show', f'{head}:tracked.rs') == 'fn persisted() {}'
    assert git(work, 'status', '--porcelain') == ''


def test_pr_repair_pushes_original_branch_and_tracking_ref_atomically(tmp_path: Path) -> None:
    work = repo(tmp_path)
    source = git(work, 'branch', '--show-current')
    git(work, 'push', 'origin', source)
    (work / 'tracked.rs').write_text('fn repaired() {}\n')
    proc = start(work, mode='pr', issue='123')
    try:
        saved = wait_for_ref(work)
        stop(proc)
    finally:
        if proc.poll() is None:
            proc.kill()
            proc.wait()
    assert git(work, 'ls-remote', 'origin', f'refs/heads/{source}').split()[0] == saved
    # A newer remote worker commit makes both updates fail, preserving that head
    # and the prior tracking ref instead of force-pushing either branch.
    newer = subprocess.run(['git', 'commit-tree', f'{saved}^{{tree}}', '-p', saved],
                           cwd=work, input='ordinary resumed commit\n', text=True,
                           check=True, capture_output=True).stdout.strip()
    git(work, 'push', 'origin', f'{newer}:refs/heads/{source}')
    (work / 'tracked.rs').write_text('fn stale_writer() {}\n')
    proc = start(work, mode='pr', issue='123')
    try:
        time.sleep(1.4)
        stop(proc)
    finally:
        if proc.poll() is None:
            proc.kill()
            proc.wait()
    assert remote_ref(work) == saved
    assert git(work, 'ls-remote', 'origin', f'refs/heads/{source}').split()[0] == newer
