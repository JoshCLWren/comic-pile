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


def start(work: Path, *, run_id: str = '123456') -> subprocess.Popen[str]:
    env = {**os.environ, 'FACTORY_CHECKPOINT_INTERVAL_SECONDS': '1'}
    return subprocess.Popen(
        ['bash', str(CHECKPOINT), 'issue', '123', '42', run_id],
        cwd=work, env=env, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True,
    )


def remote_ref(work: Path, run_id: str = '123456') -> str:
    ref = f'refs/heads/factory/work-checkpoints/{run_id}'
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
        assert git(work, 'status', '--porcelain') == 'M tracked.rs\n?? new.rs'
        assert git(work, 'show', f'{sha}:new.rs') == 'fn added() {}'
        assert git(work, 'show', f'{sha}:tracked.rs') == 'fn edited() {}'
        assert '.env' not in git(work, 'ls-tree', '-r', '--name-only', sha).splitlines()
        (work / 'tracked.rs').write_text('fn second_edit() {}\n')
        stop(proc)
        sha2 = remote_ref(work)
        assert sha2 != sha
        assert git(work, 'show', f'{sha2}:tracked.rs') == 'fn second_edit() {}'
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
