#!/usr/bin/env python3
from __future__ import annotations

import csv
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

    print('Validated 42 fixed-model factory lanes across schedulers A-D.')
    for source, count in EXPECTED_SOURCE_COUNTS.items():
        print(f'  {source}: {count}')


if __name__ == '__main__':
    main()
