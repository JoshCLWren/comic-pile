#!/usr/bin/env python3
"""Validate the deterministic free-model factory roster and dispatcher wiring."""

from __future__ import annotations

import csv
import re
from collections import Counter
from pathlib import Path

MANIFEST = Path('.github/free-model-factories.tsv')
DISPATCHER = Path('.github/workflows/free-model-factory-dispatch.yml')
ENTRY = Path('.github/workflows/free-model-factory-entry.yml')
EXPECTED_WORKERS = set(range(6, 47))
EXPECTED_SOURCE_COUNTS = {
    'nvidia': 26,
    'omniroute-opencode': 7,
    'zen': 8,
}
EXPECTED_ZEN_MODELS = {
    'big-pickle',
    'deepseek-v4-flash-free',
    'hy3-free',
    'laguna-s-2.1-free',
    'ling-3.0-tiny-free',
    'mimo-v2.5-free',
    'nemotron-3-ultra-free',
    'nemotron-3.5-lightning-free',
}
DISPATCH_MINUTES = (7, 22, 37, 52)
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
    """Validate roster completeness, fixed assignments, and dispatcher invariants."""
    with MANIFEST.open(newline='', encoding='utf-8') as handle:
        rows = list(csv.DictReader(
            (line for line in handle if not line.startswith('# worker')),
            fieldnames=['worker', 'source', 'model', 'minute', 'scheduler', 'display_name'],
            delimiter='\t',
        ))

    assert len(rows) == 41, f'expected 41 fixed model lanes, got {len(rows)}'

    workers = [int(row['worker']) for row in rows]
    assert set(workers) == EXPECTED_WORKERS, (
        f'worker roster mismatch: missing={sorted(EXPECTED_WORKERS - set(workers))} '
        f'extra={sorted(set(workers) - EXPECTED_WORKERS)}'
    )
    assert len(workers) == len(set(workers)), 'duplicate worker IDs in fixed-model manifest'

    source_counts = Counter(row['source'] for row in rows)
    assert source_counts == EXPECTED_SOURCE_COUNTS, (
        f'source counts changed unexpectedly: {dict(source_counts)}'
    )

    zen_models = {row['model'] for row in rows if row['source'] == 'zen'}
    assert zen_models == EXPECTED_ZEN_MODELS, (
        f'OpenCode free roster changed: missing={sorted(EXPECTED_ZEN_MODELS - zen_models)} '
        f'extra={sorted(zen_models - EXPECTED_ZEN_MODELS)}'
    )

    source_models = [(row['source'], row['model']) for row in rows]
    assert len(source_models) == len(set(source_models)), 'duplicate model inside the same source'

    assert not any(
        row['source'] == 'nvidia' and row['model'] == 'deepseek-ai/deepseek-v4-pro'
        for row in rows
    ), 'page-only NVIDIA DeepSeek V4 Pro must not be scheduled as an API factory'

    expected_batch_counts = Counter({7: 11, 22: 10, 37: 10, 52: 10})
    actual_batch_counts: Counter[int] = Counter()
    for row in rows:
        worker = int(row['worker'])
        minute = int(row['minute'])
        assert row['scheduler'] == 'dispatcher', f'worker {worker}: stale scheduler {row["scheduler"]!r}'
        expected_minute = DISPATCH_MINUTES[(worker - 6) % len(DISPATCH_MINUTES)]
        assert minute == expected_minute, (
            f'worker {worker}: expected :{expected_minute:02d}, got :{minute:02d}'
        )
        actual_batch_counts[minute] += 1
        assert row['model'], f'worker {worker}: model is empty'
        assert row['display_name'], f'worker {worker}: display name is empty'
    assert actual_batch_counts == expected_batch_counts, (
        f'dispatch batch counts changed: {dict(actual_batch_counts)}'
    )

    assert DISPATCHER.exists(), 'single fixed-model dispatcher is missing'
    dispatcher_text = DISPATCHER.read_text(encoding='utf-8')
    actual_crons = {
        int(match.group(1))
        for match in re.finditer(r"cron:\s*['\"](\d+) \* \* \* \*['\"]", dispatcher_text)
    }
    assert actual_crons == set(DISPATCH_MINUTES), (
        f'dispatcher cron mismatch: expected={list(DISPATCH_MINUTES)} actual={sorted(actual_crons)}'
    )
    assert 'workers=\'["6","32","39"]\'' in dispatcher_text, (
        'dispatcher must retain immediate NVIDIA/OmniRoute/OpenCode post-merge smoke'
    )
    assert 'contents: read' in dispatcher_text and 'actions: write' in dispatcher_text
    assert 'gh workflow run free-model-factory-entry.yml' in dispatcher_text
    assert 'matrix:' not in dispatcher_text, 'dispatcher must not dynamically matrix-call reusable workflows'

    assert ENTRY.exists(), 'dispatchable fixed-model entry workflow is missing'
    entry_text = ENTRY.read_text(encoding='utf-8')
    assert 'workflow_dispatch:' in entry_text
    assert 'uses: ./.github/workflows/free-model-factory-run.yml' in entry_text
    assert 'worker: ${{ inputs.worker }}' in entry_text
    assert 'secrets: inherit' in entry_text
    for permission in ENTRY_PERMISSIONS:
        assert permission in entry_text, f'entry workflow missing permission {permission!r}'

    for retired in RETIRED_SCHEDULERS:
        assert not retired.exists(), f'obsolete scheduler still exists: {retired}'

    runner = Path('.github/workflows/free-model-factory-run.yml')
    worker = Path('.github/scripts/free-model-factory-worker.sh')
    assert runner.exists(), 'reusable fixed-model runner is missing'
    assert worker.exists(), 'fixed-model worker script is missing'
    worker_text = worker.read_text(encoding='utf-8')
    assert 'rotate_model' not in worker_text, 'fixed-model worker must never rotate models'
    assert 'Do not switch models' in worker_text, 'fixed-model no-fallback contract is missing'

    print('Validated 41 fixed model factories through dispatchable four-batch scheduler.')
    for minute in DISPATCH_MINUTES:
        print(f'  :{minute:02d} -> {actual_batch_counts[minute]} workers')
    for source, count in EXPECTED_SOURCE_COUNTS.items():
        print(f'  {source}: {count}')


if __name__ == '__main__':
    main()
