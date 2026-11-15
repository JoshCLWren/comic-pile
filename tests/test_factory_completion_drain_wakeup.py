"""Completion signals wake one dispatcher without rediscovering factory demand."""
from pathlib import Path
import os
import subprocess

import yaml

ROOT = Path(__file__).resolve().parents[1]
WORKFLOW = ROOT / '.github/workflows/factory-completion-drain.yml'


def test_completion_is_a_credential_minimal_signal_without_discovery():
    workflow = yaml.safe_load(WORKFLOW.read_text())
    job = workflow['jobs']['drain']
    assert len(job['steps']) == 1
    assert 'concurrency' not in job
    assert workflow['permissions'] == {'actions': 'write', 'contents': 'read'}
    source = WORKFLOW.read_text()
    for obsolete in ('factory-state-cache', 'factory_full_completion_controller.py',
                     'actions/checkout', 'schedule:', 'factory-work-controller.py'):
        assert obsolete not in source


def test_actual_signal_command_dispatches_once_with_completion_context(tmp_path):
    workflow = yaml.safe_load(WORKFLOW.read_text())
    step = workflow['jobs']['drain']['steps'][0]
    gh = tmp_path / 'gh'
    gh.write_text('#!/bin/sh\nprintf "%s\\n" "$*" >> "$CALLS"\n')
    gh.chmod(0o755)
    calls = tmp_path / 'calls'
    result = subprocess.run(['bash', '-c', step['run']], text=True, capture_output=True,
                            env={**os.environ, 'PATH': str(tmp_path) + ':' + os.environ['PATH'],
                                 'CALLS': str(calls), 'SOURCE_RUN_ID': '12345',
                                 'GITHUB_REPOSITORY': 'owner/repo'})
    assert result.returncode == 0, result.stderr
    assert calls.read_text().splitlines() == [
        'workflow run fixed-model-factory-dispatch.yml --repo owner/repo --ref main -f mode=roster -f source_run_id=12345']
    assert 'dispatcher_wakeups=1' in result.stdout


def test_outcome_persistence_precedes_completion_signal_even_on_failure():
    entry = yaml.safe_load((ROOT / '.github/workflows/free-model-factory-entry.yml').read_text())
    signal = entry['jobs']['signal_completion']
    assert set(signal['needs']) == {'run', 'persist_outcome'}
    assert signal['if'] == '${{ always() }}'
    assert '-f source_run_id="$GITHUB_RUN_ID"' in signal['steps'][0]['run']
    dispatcher = (ROOT / '.github/workflows/fixed-model-factory-dispatch.yml').read_text()
    assert "cron: '7 * * * *'" in dispatcher


def test_dispatcher_is_the_only_entry_assignment_writer():
    """No refill clone can reconstruct the queue or lease independently."""
    writers = []
    for path in (ROOT / '.github/workflows').glob('*.yml'):
        if 'gh workflow run free-model-factory-entry.yml' in path.read_text():
            writers.append(path.name)
    assert writers == ['fixed-model-factory-dispatch.yml']
