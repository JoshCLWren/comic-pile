#!/usr/bin/env python3
"""Validate the deterministic free-model factory roster and shared-pool worker."""

from __future__ import annotations

import csv
from collections import Counter
from pathlib import Path

MANIFEST = Path('.github/free-model-factories.tsv')
DISPATCHER = Path('.github/workflows/free-model-factory-dispatch.yml')
ENTRY = Path('.github/workflows/free-model-factory-entry.yml')
RUNNER = Path('.github/workflows/free-model-factory-run.yml')
WATCHDOG = Path('.github/workflows/factory-heartbeat-watchdog.yml')
DISCOVERY = Path('.github/workflows/chromium-discovery.yml')
DISCOVERY_CLASSIFIER = Path('.github/scripts/classify-chromium-discovery.py')
PLAYWRIGHT_CONFIG = Path('frontend/playwright.config.ts')
WORKER = Path('.github/scripts/free-model-factory-worker.sh')
PRIMITIVES = Path('.github/scripts/free-model-factory-worker-primitives.sh')
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
ENTRY_PERMISSIONS = ('contents: write', 'issues: write', 'pull-requests: write', 'actions: write', 'checks: read')


def assert_in_order(text: str, *needles: str) -> None:
    """Assert that the final call-site occurrence of each marker is ordered."""
    positions = [text.rfind(needle) for needle in needles]
    assert all(position >= 0 for position in positions), f'missing ordered marker: {needles}'
    assert positions == sorted(positions), f'expected ordering: {needles}'


def main() -> None:
    """Validate roster, runtime, lease, shared-pool, and discovery invariants."""
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
    assert PRIMITIVES.exists(), 'tracked worker primitives are missing'
    primitives = PRIMITIVES.read_text(encoding='utf-8')
    assert "source <(sed '/^ensure_owner_label$/,$d' .github/scripts/free-model-factory-worker-primitives.sh)" in worker
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
        assert required in primitives, f'inherited worker primitive missing: {required}'

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
        'stage_trusted_kilo_helper',
        'TRUSTED_KILO_HELPER',
        'daily Chromium discovery owns backlog replenishment',
    ):
        assert required in worker, f'shared-pool invariant missing: {required}'
    assert "for selector in 'user-reported bug' 'bug' 'ralph-task'" not in worker
    assert 'choose_backlog_zero_child' not in worker
    assert 'issues/679/sub_issues' not in worker
    assert 'claim_issue "$candidate"' in worker
    assert 'gh workflow run chromium-discovery.yml' not in worker
    assert 'trigger_backlog_zero_discovery' not in worker
    assert_in_order(
        worker,
        "claim_from_pool 'user-bug'",
        "claim_from_pool 'bug'",
        "claim_from_pool 'product'",
        'done < <(choose_unowned_pr)',
        'daily Chromium discovery owns backlog replenishment',
    )

    discovery = DISCOVERY.read_text(encoding='utf-8')
    for required in (
        'schedule:',
        "cron: '23 9 * * *'",
        'workflow_dispatch:',
        'fail-fast: false',
        'if: always()',
        'retention-days: 30',
        'playwright-report/',
        'test-results/',
        'discovery-artifacts/backend.log',
        'discovery-artifacts/run-metadata.json',
        'Classify persisted Chromium failures',
        'actions/download-artifact@v5',
        'classify-chromium-discovery.py',
        'issues: write',
    ):
        assert required in discovery, f'daily discovery invariant missing: {required}'
    assert 'cancel-in-progress: false' in discovery
    assert '\n  push:\n' not in discovery

    playwright = PLAYWRIGHT_CONFIG.read_text(encoding='utf-8')
    for required in (
        "outputFile: '../test-results/results.json'",
        "trace: 'retain-on-failure'",
        "screenshot: 'only-on-failure'",
        "video: 'retain-on-failure'",
        "retries: process.env.CI ? 2 : 0",
    ):
        assert required in playwright, f'Playwright failure-evidence invariant missing: {required}'

    classifier = DISCOVERY_CLASSIFIER.read_text(encoding='utf-8')
    for required in (
        'chromium-discovery-failure:',
        'e2e-discovered',
        'e2e-infrastructure',
        'factory:unowned',
        'ralph-status:pending',
        '"issue", "create"',
        '"issue", "comment"',
        'results.json',
        'GITHUB_RUN_ID',
        'GITHUB_SHA',
    ):
        assert required in classifier, f'discovery classifier invariant missing: {required}'

    print('Validated 28 external factory lanes, shared-pool selection, and daily Chromium discovery.')
    for minute in BATCH_MINUTES:
        print(f'  :{minute:02d} -> {counts[minute]} workers')
    for source, count in EXPECTED_SOURCE_COUNTS.items():
        print(f'  {source}: {count}')


if __name__ == '__main__':
    main()
