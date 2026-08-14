#!/usr/bin/env python3
"""Validate the deterministic free-model factory roster and watchdog-backed dispatcher."""

from __future__ import annotations

import csv
from collections import Counter
from pathlib import Path

MANIFEST = Path('.github/free-model-factories.tsv')
DISPATCHER = Path('.github/workflows/free-model-factory-dispatch.yml')
ENTRY = Path('.github/workflows/free-model-factory-entry.yml')
WATCHDOG = Path('.github/workflows/factory-heartbeat-watchdog.yml')
EXPECTED_WORKERS = set(range(6, 47))
EXPECTED_SOURCE_COUNTS = {
    'nvidia': 26,
    'omniroute-opencode': 7,
    'opencode-free': 8,
}
EXPECTED_OPENCODE_FREE_MODELS = {
    'big-pickle',
    'deepseek-v4-flash-free',
    'hy3-free',
    'laguna-s-2.1-free',
    'ling-3.0-tiny-free',
    'mimo-v2.5-free',
    'nemotron-3-ultra-free',
    'nemotron-3.5-lightning-free',
}
BATCH_MINUTES = (0, 15, 30, 45)
RETIRED_SCHEDULERS = (
    Path('.github/workflows/nvidia-factory-6.yml'),
    Path('.github/workflows/omniroute-factory-16.yml'),
    Path('.github/workflows/omniroute-factory-17.yml'),
    Path('.github/workflows/free-model-factory-a.yml'),
    Path('.github/workflows/free-model-factory-b.yml'),
    Path('.github/workflows/free-model-factory-c.yml'),
    Path('.github/workflows/free-model-factory-d.yml'),
    Path('.github/workflows/free-model-factory-e.yml'),
)
ENTRY_PERMISSIONS = (
    'contents: write',
    'issues: write',
    'pull-requests: write',
    'actions: read',
    'checks: read',
)


def main() -> None:
    """Validate roster completeness, fixed assignments, and trigger invariants."""
    with MANIFEST.open(newline='', encoding='utf-8') as handle:
        rows = list(csv.DictReader(
            (line for line in handle if not line.startswith('# worker')),
            fieldnames=['worker', 'source', 'model', 'minute', 'scheduler', 'display_name'],
            delimiter='\t',
        ))

    assert len(rows) == 41, f'expected 41 fixed model lanes, got {len(rows)}'
    workers = [int(row['worker']) for row in rows]
    assert set(workers) == EXPECTED_WORKERS
    assert len(workers) == len(set(workers)), 'duplicate worker IDs'

    source_counts = Counter(row['source'] for row in rows)
    assert source_counts == EXPECTED_SOURCE_COUNTS, f'unexpected source counts: {dict(source_counts)}'

    opencode_free_models = {row['model'] for row in rows if row['source'] == 'opencode-free'}
    assert opencode_free_models == EXPECTED_OPENCODE_FREE_MODELS, (
        f'OpenCode free roster changed: missing={sorted(EXPECTED_OPENCODE_FREE_MODELS - opencode_free_models)} '
        f'extra={sorted(opencode_free_models - EXPECTED_OPENCODE_FREE_MODELS)}'
    )
    assert not any(row['source'] in {'zen', 'kilo', 'llm7', 'ovhcloud'} for row in rows), (
        'retired or unrelated provider source returned to the fixed-model roster'
    )

    source_models = [(row['source'], row['model']) for row in rows]
    assert len(source_models) == len(set(source_models)), 'duplicate model inside the same source'
    assert not any(
        row['source'] == 'nvidia' and row['model'] == 'deepseek-ai/deepseek-v4-pro'
        for row in rows
    )
    assert not any(
        row['source'] == 'nvidia' and row['model'] == 'mistralai/mistral-medium-3.5-128b'
        for row in rows
    ), 'Factory 13 retired NVIDIA model returned to the roster'

    expected_batch_counts = Counter({0: 11, 15: 10, 30: 10, 45: 10})
    actual_batch_counts: Counter[int] = Counter()
    for row in rows:
        worker = int(row['worker'])
        minute = int(row['minute'])
        assert row['scheduler'] == 'watchdog', f'worker {worker}: stale scheduler {row["scheduler"]!r}'
        expected_minute = BATCH_MINUTES[(worker - 6) % len(BATCH_MINUTES)]
        assert minute == expected_minute, f'worker {worker}: expected {expected_minute}, got {minute}'
        actual_batch_counts[minute] += 1
        assert row['model'] and row['display_name']
    assert actual_batch_counts == expected_batch_counts

    assert WATCHDOG.exists(), 'heartbeat watchdog is missing'
    watchdog_text = WATCHDOG.read_text(encoding='utf-8')
    assert "cron: '*/15 * * * *'" in watchdog_text, 'watchdog must remain on proven 15-minute clock'

    assert DISPATCHER.exists(), 'fixed-model dispatcher is missing'
    dispatcher_text = DISPATCHER.read_text(encoding='utf-8')
    assert 'workflow_run:' in dispatcher_text
    assert "workflows: ['Factory heartbeat watchdog']" in dispatcher_text
    assert 'schedule:' not in dispatcher_text, 'dispatcher must not own an independent cron clock'
    assert 'WATCHDOG_RUN_NUMBER' in dispatcher_text
    assert 'slots=(0 15 30 45)' in dispatcher_text
    assert 'workers=\'["6","32","39"]\'' in dispatcher_text
    assert 'contents: read' in dispatcher_text and 'actions: write' in dispatcher_text
    assert 'gh workflow run free-model-factory-entry.yml' in dispatcher_text
    assert 'matrix:' not in dispatcher_text

    assert ENTRY.exists(), 'dispatchable fixed-model entry workflow is missing'
    entry_text = ENTRY.read_text(encoding='utf-8')
    assert 'workflow_dispatch:' in entry_text
    assert 'uses: ./.github/workflows/free-model-factory-run.yml' in entry_text
    assert 'worker: ${{ inputs.worker }}' in entry_text
    assert 'secrets: inherit' in entry_text
    for permission in ENTRY_PERMISSIONS:
        assert permission in entry_text

    for retired in RETIRED_SCHEDULERS:
        assert not retired.exists(), f'obsolete scheduler still exists: {retired}'

    runner = Path('.github/workflows/free-model-factory-run.yml')
    worker = Path('.github/scripts/free-model-factory-worker.sh')
    assert runner.exists() and worker.exists()
    runner_text = runner.read_text(encoding='utf-8')
    assert 'opencode-free)' in runner_text
    assert 'runtime_model="opencode/${model}"' in runner_text
    assert "branch_suffix='opencode-free'" in runner_text
    assert 'OPENCODE_API_KEY' not in runner_text, 'direct OpenCode Free must remain keyless'
    assert all(source not in runner_text for source in ('kilo)', 'llm7)', 'ovhcloud)', 'zen)'))
    worker_text = worker.read_text(encoding='utf-8')
    assert 'rotate_model' not in worker_text
    assert 'Do not switch models' in worker_text

    print('Validated 41 fixed model factories on the proven 15-minute watchdog clock.')
    for minute in BATCH_MINUTES:
        print(f'  :{minute:02d} -> {actual_batch_counts[minute]} workers')
    for source, count in EXPECTED_SOURCE_COUNTS.items():
        print(f'  {source}: {count}')


if __name__ == '__main__':
    main()
