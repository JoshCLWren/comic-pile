#!/usr/bin/env python3
"""Validate the deterministic free-model factory roster and control plane."""

from __future__ import annotations

import csv
import re
from collections import Counter
from pathlib import Path

MANIFEST = Path('.github/free-model-factories.tsv')
DISPATCHER = Path('.github/workflows/fixed-model-factory-dispatch.yml')
ENTRY = Path('.github/workflows/free-model-factory-entry.yml')
RUNNER = Path('.github/workflows/free-model-factory-run.yml')
DISCOVERY = Path('.github/workflows/chromium-discovery.yml')
DISCOVERY_CLASSIFIER = Path('.github/scripts/classify-chromium-discovery.py')
PLAYWRIGHT_CONFIG = Path('frontend/playwright.config.ts')
WORKER = Path('.github/scripts/free-model-factory-worker.sh')
PRIMITIVES = Path('.github/scripts/free-model-factory-worker-primitives.sh')
CONTROLLER = Path('.github/scripts/factory-work-controller.py')
POLICY = Path('.github/scripts/factory_work_policy.py')
KILO_HELPER = Path('.github/scripts/kilo-auto-factory-run.sh')
GUARD = Path('.github/scripts/fixed-model-guard.py')
EXPECTED_WORKERS = {6, 9, 10, 11, 14, 16, 17, 18, 19, 20, 21, 23, 29} | set(range(39, 72))
EXPECTED_SOURCE_COUNTS = {'nvidia': 13, 'opencode-free': 20, 'kilo-auto': 1, 'openrouter-free': 12}
EXPECTED_OPENCODE_FREE_MODELS = {
    'big-pickle',
    'deepseek-v4-flash-free',
    'hy3-free',
    'laguna-s-2.1-free',
    'mimo-v2.5-free',
    'muse-spark-1.2-contributor-free',
    'nemotron-3-ultra-free',
    'nemotron-3.5-lightning-free',
    'x-preview-f-free',
}
EXPECTED_OPENROUTER_FREE_MODELS = {'stealth/ox-alpha'}
SCHEDULE_MINUTES = tuple(range(0, 60, 5))
ENTRY_PERMISSIONS = ('contents: write', 'issues: write', 'pull-requests: write', 'actions: write', 'checks: read')


def main() -> None:
    """Validate roster, runtime, lease, assignment, and discovery invariants."""
    with MANIFEST.open(newline='', encoding='utf-8') as handle:
        rows = list(csv.DictReader(
            (line for line in handle if not line.startswith('# worker')),
            fieldnames=['worker', 'source', 'model', 'minute', 'scheduler', 'display_name'],
            delimiter='\t',
        ))

    assert len(rows) == 46, f'expected 38 external factory lanes, got {len(rows)}'
    workers = [int(row['worker']) for row in rows]
    assert set(workers) == EXPECTED_WORKERS
    assert len(workers) == len(set(workers)), 'duplicate worker IDs'
    assert Counter(row['source'] for row in rows) == EXPECTED_SOURCE_COUNTS

    opencode_models = {row['model'] for row in rows if row['source'] == 'opencode-free'}
    assert opencode_models == EXPECTED_OPENCODE_FREE_MODELS
    openrouter_models = {row['model'] for row in rows if row['source'] == 'openrouter-free'}
    assert openrouter_models == EXPECTED_OPENROUTER_FREE_MODELS
    kilo = [row for row in rows if row['source'] == 'kilo-auto']
    assert len(kilo) == 1 and kilo[0]['worker'] == '46'
    assert kilo[0]['model'] == 'kilo-auto/free'
    assert kilo[0]['display_name'] == 'Kilo Auto Free · Forge'

    counts: Counter[int] = Counter()
    for index, row in enumerate(rows):
        minute = int(row['minute'])
        assert row['scheduler'] == 'dispatcher'
        assert minute == SCHEDULE_MINUTES[index % len(SCHEDULE_MINUTES)]
        counts[minute] += 1
    assert set(counts) == set(SCHEDULE_MINUTES)
    assert max(counts.values()) - min(counts.values()) <= 1
    assert sum(counts.values()) == 46

    dispatcher = DISPATCHER.read_text(encoding='utf-8')
    assert 'workflow_run:' not in dispatcher
    assert 'schedule:' in dispatcher
    for minute in SCHEDULE_MINUTES:
        assert f"cron: '{minute} 0-23 * * *'" in dispatcher
    assert 'SCHEDULE_EXPR: ${{ github.event.schedule }}' in dispatcher
    assert 'elif [[ "$EVENT_NAME" == schedule ]]; then' in dispatcher
    assert 'minute="${SCHEDULE_EXPR%% *}"' in dispatcher
    assert 'workers=\'["6","39","46"]\'' in dispatcher
    assert 'gh workflow run free-model-factory-entry.yml' in dispatcher
    assert "'.github/scripts/factory-work-controller.py'" in dispatcher
    assert "'.github/scripts/free-model-factory-worker.sh'" in dispatcher
    assert "'.github/scripts/kilo-auto-factory-run.sh'" in dispatcher
    for required in (
        'group: fixed-model-factory-dispatch',
        'queued in_progress',
        'gh run cancel "$run_id"',
        'release_cancelled_worker_leases',
        'factory:unowned',
        'another worker already owns it',
        'takeover observed',
        'python3 "$controller" reconcile',
        'python3 "$controller" assign --worker "$worker"',
        'python3 "$controller" release --worker "$worker"',
        'while (( attempt <= 3 ))',
        'later workers were still attempted',
    ):
        assert required in dispatcher, f'deployment/assignment fence missing: {required}'

    entry = ENTRY.read_text(encoding='utf-8')
    assert 'workflow_dispatch:' in entry
    assert 'run-name: Factory ${{ inputs.worker }} · fixed-model entry' in entry
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
        'select_controller_assignment',
        'no control-plane assignment is leased to this worker',
        'controller-assignment-read-failed',
        'session-end-handoff',
        'no-persisted-change-handoff',
        'stage_trusted_kilo_helper',
        'TRUSTED_KILO_HELPER',
        'handing it to the merge controller',
    ):
        assert required in worker, f'controller-assigned worker invariant missing: {required}'
    for forbidden in (
        'choose_existing_pr',
        'choose_ranked_issues',
        "claim_from_pool 'user-bug'",
        "claim_from_pool 'bug'",
        "claim_from_pool 'product'",
        'leased unowned PR',
        'gh pr merge "$NUMBER"',
        'trigger_backlog_zero_discovery',
    ):
        assert forbidden not in worker, f'worker still owns repo-wide selection/merge behavior: {forbidden}'
    assert 'gh workflow run chromium-discovery.yml' not in worker

    assert POLICY.exists(), 'tracked factory ranking policy module is missing'
    controller = CONTROLLER.read_text(encoding='utf-8')
    policy = POLICY.read_text(encoding='utf-8')
    for required in (
        'from factory_work_policy import',
        'def reconcile_stale_leases(',
        'def active_fixed_workers(',
        'def assign_candidate(',
        'def release_worker(',
        'latest_lease_activity_epoch',
        'queued',
        'in_progress',
    ):
        assert required in controller, f'factory controller runtime invariant missing: {required}'
    for required in (
        'class Candidate:',
        'def build_candidates(',
        "'e2e-discovered'",
        'return 4',
        'return 5',
        'factory:ready',
        'LOCAL_LEASE_TTL_SECONDS',
    ):
        assert required in policy, f'factory ranking/lease policy invariant missing: {required}'

    if DISCOVERY.exists():
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

    if PLAYWRIGHT_CONFIG.exists():
        playwright = PLAYWRIGHT_CONFIG.read_text(encoding='utf-8')
        for required in (
            "outputFile: '../test-results/results.json'",
            "trace: 'retain-on-failure'",
            "screenshot: 'only-on-failure'",
            "video: 'retain-on-failure'",
            "retries: process.env.CI ? 2 : 0",
        ):
            assert required in playwright, f'Playwright failure-evidence invariant missing: {required}'

    if DISCOVERY_CLASSIFIER.exists():
        classifier = DISCOVERY_CLASSIFIER.read_text(encoding='utf-8')
        for required in (
            'chromium-discovery-failure:',
            'e2e-discovered',
            'e2e-infrastructure',
            'factory:unowned',
            'ralph-status:pending',
            'results.json',
            'GITHUB_RUN_ID',
            'GITHUB_SHA',
            'args = ["issue", "create"',
            'run_gh(*args)',
        ):
            assert required in classifier, f'discovery classifier invariant missing: {required}'
        assert re.search(
            r'run_gh\(\s*"issue",\s*"comment"',
            classifier,
        ), 'discovery classifier issue comment call missing'

    print(f'Validated {len(rows)} external factory lanes, centralized assignment, staggered scheduling, and daily Chromium discovery.')
    for minute in SCHEDULE_MINUTES:
        print(f'  :{minute:02d} -> {counts[minute]} workers')
    for source, count in EXPECTED_SOURCE_COUNTS.items():
        print(f'  {source}: {count}')


if __name__ == '__main__':
    main()
