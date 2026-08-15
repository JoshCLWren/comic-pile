#!/usr/bin/env python3
"""Validate the deterministic free-model factory roster and shared-pool worker."""

from __future__ import annotations

import csv
import re
import subprocess
from collections import Counter
from pathlib import Path

MANIFEST = Path('.github/free-model-factories.tsv')
DISPATCHER = Path('.github/workflows/free-model-factory-dispatch.yml')
ENTRY = Path('.github/workflows/free-model-factory-entry.yml')
RUNNER = Path('.github/workflows/free-model-factory-run.yml')
WATCHDOG = Path('.github/workflows/factory-heartbeat-watchdog.yml')
WORKER = Path('.github/scripts/free-model-factory-worker.sh')
KILO_HELPER = Path('.github/scripts/kilo-auto-factory-run.sh')
GUARD = Path('.github/scripts/fixed-model-guard.py')
EXPECTED_WORKERS = set(range(6, 25)) | {29} | set(range(39, 47))
EXPECTED_SOURCE_COUNTS = {'nvidia': 20, 'opencode-free': 7, 'kilo-auto': 1}
EXPECTED_OPENCODE_FREE_MODELS = {
    'big-pickle',
    'deepseek-v4-flash-free',
    'hy3-free',
    'laguna-s-2.1-free',
    'mimo-v2.5-free',
    'nemotron-3-ultra-free',
    'nemotron-3.5-lightning-free',
}
BATCH_MINUTES = (0, 15, 30, 45)
ENTRY_PERMISSIONS = ('contents: write', 'issues: write', 'pull-requests: write', 'actions: read', 'checks: read')


def assert_in_order(text: str, *needles: str) -> None:
    positions = [text.index(needle) for needle in needles]
    assert positions == sorted(positions), f'expected ordering: {needles}'


def main() -> None:
    with MANIFEST.open(newline='', encoding='utf-8') as handle:
        rows = list(csv.DictReader(
            (line for line in handle if not line.startswith('# worker')),
            fieldnames=['worker', 'source', 'model', 'minute', 'scheduler', 'display_name'],
            delimiter='\t',
        ))

    assert len(rows) == 28, f'expected 28 external factory lanes, got {len(rows)}'
    workers = [int(row['worker']) for row in rows]
    assert set(workers) == EXPECTED_WORKERS
    assert len(workers) == len(set(workers)), 'duplicate worker IDs'
    assert Counter(row['source'] for row in rows) == EXPECTED_SOURCE_COUNTS

    opencode_models = {row['model'] for row in rows if row['source'] == 'opencode-free'}
    assert opencode_models == EXPECTED_OPENCODE_FREE_MODELS
    kilo = [row for row in rows if row['source'] == 'kilo-auto']
    assert len(kilo) == 1 and kilo[0]['worker'] == '46'
    assert kilo[0]['model'] == 'kilo-auto/free'
    assert kilo[0]['display_name'] == 'Kilo Auto Free · Forge'

    counts: Counter[int] = Counter()
    for row in rows:
        worker = int(row['worker'])
        minute = int(row['minute'])
        assert row['scheduler'] == 'watchdog'
        assert minute == BATCH_MINUTES[(worker - 6) % 4]
        counts[minute] += 1
    assert counts == Counter({0: 7, 15: 7, 30: 7, 45: 7})

    watchdog = WATCHDOG.read_text(encoding='utf-8')
    assert "cron: '*/15 * * * *'" in watchdog

    dispatcher = DISPATCHER.read_text(encoding='utf-8')
    assert 'workflow_run:' in dispatcher
    assert "workflows: ['Factory heartbeat watchdog']" in dispatcher
    assert 'schedule:' not in dispatcher
    assert 'slots=(0 15 30 45)' in dispatcher
    assert 'workers=\'["6","39","46"]\'' in dispatcher
    assert 'gh workflow run free-model-factory-entry.yml' in dispatcher
    assert "'.github/scripts/free-model-factory-worker.sh'" in dispatcher
    assert "'.github/scripts/kilo-auto-factory-run.sh'" in dispatcher
    for required in (
        'queued in_progress',
        'gh run cancel "$run_id"',
        'release_cancelled_worker_leases',
        'factory:unowned',
        'another worker already owns it',
        'takeover observed',
    ):
        assert required in dispatcher, f'deployment/lease fence missing: {required}'

    entry = ENTRY.read_text(encoding='utf-8')
    assert 'workflow_dispatch:' in entry
    assert 'uses: ./.github/workflows/free-model-factory-run.yml' in entry
    assert 'secrets: inherit' in entry
    for permission in ENTRY_PERMISSIONS:
        assert permission in entry

    runner = RUNNER.read_text(encoding='utf-8')
    assert 'group: fixed-model-factory-${{ inputs.worker }}' in runner
    assert 'cancel-in-progress: false' in runner
    assert 'opencode-free)' in runner and 'runtime_model="opencode/${model}"' in runner
    assert 'OPENCODE_API_KEY' not in runner
    assert 'kilo-auto)' in runner and 'runtime_model="kilo/${model}"' in runner
    assert "KILO_VERSION: '7.4.22'" in runner
    assert 'Smoke Kilo Auto Free through Kilo CLI' in runner
    assert 'PR_REBASE_TOKEN: ${{ secrets.PR_REBASE_TOKEN }}' in runner
    assert 'x-access-token:${PR_REBASE_TOKEN}' in runner

    kilo_text = KILO_HELPER.read_text(encoding='utf-8')
    for required in (
        'unset KILO_API_KEY KILOCODE_API_KEY',
        'kilo run -m "$RUNTIME_MODEL" --auto --format json',
        'requested_route=kilo-auto/free',
        'step_finish',
        'non-zero cost',
    ):
        assert required in kilo_text, f'Kilo free-route invariant missing: {required}'

    guard = GUARD.read_text(encoding='utf-8')
    assert 'factory-control-out-of-scope' in guard and 'is_factory_control_path' in guard

    worker = WORKER.read_text(encoding='utf-8')

    # The repair intentionally reuses the proven worker primitives from the
    # immediately preceding repository blob and replaces only the drifted main
    # selector/session loop. Factory runners use fetch-depth: 0, so this blob is
    # a local Git-history dependency rather than a hosted service dependency.
    match = re.search(r"LEGACY_WORKER_BLOB='([0-9a-f]{40})'", worker)
    assert match, 'shared-pool worker must pin its inherited primitive blob'
    legacy_blob = match.group(1)
    legacy = subprocess.run(
        ['git', 'cat-file', 'blob', legacy_blob],
        check=True,
        capture_output=True,
        text=True,
    ).stdout
    for required in (
        'release_owned_targets',
        'comic-pile-factory-implement-claim-v3',
        'comic-pile-factory-claim-released-v3',
        'issue_has_open_factory_pr',
        'reject_out_of_scope_diff',
        'fixed-model-guard.py',
        "[[ \"$SOURCE\" == 'kilo-auto' ]]",
        "[[ \"$SOURCE\" != 'kilo-auto' ]]",
        '.github/scripts/kilo-auto-factory-run.sh',
        'Do not switch models',
    ):
        assert required in legacy, f'inherited worker primitive missing: {required}'

    # One shared pool: user bugs first, then bugs, then all other executable
    # product work. ralph-task remains useful metadata but is not an eligibility
    # gate. Existing unowned PRs come only after fresh executable product work.
    for required in (
        'choose_ranked_issues',
        'issue_is_executable',
        'issue_has_open_blocker',
        'dependencies/blocked_by',
        "claim_from_pool 'user-bug'",
        "claim_from_pool 'bug'",
        "claim_from_pool 'product'",
        'ralph-priority:critical',
        'ralph-priority:high',
        'issue_has_open_factory_pr "$issue" && return 1',
        'release_owned_targets \'previous-run-stale-lease\'',
        'session-end-handoff',
        'no-persisted-change-handoff',
        'leased unowned PR',
    ):
        assert required in worker, f'shared-pool invariant missing: {required}'
    assert "for selector in 'user-reported bug' 'bug' 'ralph-task'" not in worker
    assert 'choose_backlog_zero_child' not in worker
    assert 'issues/679/sub_issues' not in worker
    assert 'claim_issue "$candidate"' in worker
    assert_in_order(
        worker,
        "claim_from_pool 'user-bug'",
        "claim_from_pool 'bug'",
        "claim_from_pool 'product'",
        'done < <(choose_unowned_pr)',
        'trigger_backlog_zero_discovery',
    )

    # Effective backlog zero is a behavior, not a magic issue lease. The worker
    # directly dispatches the maintained Chromium discovery workflow.
    assert 'gh workflow run chromium-discovery.yml --ref main' in worker
    assert 'no coordination issue is required' in worker
    assert '#679 child' not in worker

    print('Validated 28 external factory lanes and canonical shared-pool selection.')
    for minute in BATCH_MINUTES:
        print(f'  :{minute:02d} -> {counts[minute]} workers')
    for source, count in EXPECTED_SOURCE_COUNTS.items():
        print(f'  {source}: {count}')


if __name__ == '__main__':
    main()
