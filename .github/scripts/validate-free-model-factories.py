#!/usr/bin/env python3
from __future__ import annotations

import csv
import re
from collections import Counter, defaultdict
from pathlib import Path

MANIFEST = Path('.github/free-model-factories.tsv')
EXPECTED_WORKERS = set(range(6, 48))
EXPECTED_SOURCE_COUNTS = {
    'nvidia': 22,
    'omniroute-opencode': 8,
    'zen': 7,
    'kilo': 1,
    'llm7': 4,
}
EXPECTED_SCHEDULERS = {'A', 'B', 'C', 'D'}
RETIRED_SCHEDULERS = (
    Path('.github/workflows/nvidia-factory-6.yml'),
    Path('.github/workflows/omniroute-factory-16.yml'),
    Path('.github/workflows/omniroute-factory-17.yml'),
)


def main() -> None:
    with MANIFEST.open(newline='', encoding='utf-8') as handle:
        rows = list(csv.DictReader(
            (line for line in handle if not line.startswith('# worker')),
            fieldnames=['worker', 'source', 'model', 'minute', 'scheduler', 'display_name'],
            delimiter='\t',
        ))

    assert len(rows) == 42, f'expected 42 fixed-model lanes, got {len(rows)}'

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

    source_models = [(row['source'], row['model']) for row in rows]
    assert len(source_models) == len(set(source_models)), 'duplicate model inside the same source'

    schedule_minutes: dict[str, list[int]] = defaultdict(list)
    seen_slots: set[tuple[str, int]] = set()
    for row in rows:
        worker = int(row['worker'])
        minute = int(row['minute'])
        scheduler = row['scheduler']
        assert scheduler in EXPECTED_SCHEDULERS, f'worker {worker}: invalid scheduler {scheduler!r}'
        assert 0 <= minute <= 59, f'worker {worker}: invalid minute {minute}'
        slot = (scheduler, minute)
        assert slot not in seen_slots, f'duplicate scheduler slot {scheduler}:{minute:02d}'
        seen_slots.add(slot)
        schedule_minutes[scheduler].append(minute)
        assert row['model'], f'worker {worker}: model is empty'
        assert row['display_name'], f'worker {worker}: display name is empty'

    for scheduler, minutes in schedule_minutes.items():
        ordered = sorted(minutes)
        wrapped = ordered + [ordered[0] + 60]
        gaps = [right - left for left, right in zip(wrapped, wrapped[1:])]
        assert min(gaps) >= 5, (
            f'scheduler {scheduler} violates five-minute floor: minutes={ordered}, gaps={gaps}'
        )

        workflow = Path(f'.github/workflows/free-model-factory-{scheduler.lower()}.yml')
        text = workflow.read_text(encoding='utf-8')
        actual = {
            int(match.group(1))
            for match in re.finditer(r"cron:\s*['\"](\d+) \* \* \* \*['\"]", text)
        }
        assert actual == set(ordered), (
            f'scheduler {scheduler} workflow does not match manifest: '
            f'expected={ordered} actual={sorted(actual)}'
        )

    for retired in RETIRED_SCHEDULERS:
        assert not retired.exists(), f'obsolete rotating scheduler still exists: {retired}'

    runner = Path('.github/workflows/free-model-factory-run.yml')
    worker = Path('.github/scripts/free-model-factory-worker.sh')
    assert runner.exists(), 'reusable fixed-model runner is missing'
    assert worker.exists(), 'fixed-model worker script is missing'
    worker_text = worker.read_text(encoding='utf-8')
    assert 'rotate_model' not in worker_text, 'fixed-model worker must never rotate models'
    assert 'Do not switch models' in worker_text, 'fixed-model no-fallback contract is missing'

    print('Validated 42 fixed-model factory lanes across schedulers A-D.')
    for source, count in EXPECTED_SOURCE_COUNTS.items():
        print(f'  {source}: {count}')


if __name__ == '__main__':
    main()
