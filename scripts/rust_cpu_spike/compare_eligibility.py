#!/usr/bin/env python3
"""Compare canonical Python Option E evaluator with native Rust on deterministic fixtures.

Pure computation only. No database writes, network, or production access.
"""
import json
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app.services.reading_list_evaluator import (
    ReadingIssue, ReadingThread, ReadingListEntry, SeriesOverlapDecision,
    ReadingList, ReadingPrerequisite, ReadingSnapshot, evaluate,
)

BINARY = Path(__file__).resolve().parent / "target/release/eligibility"

def run_fixture(snapshot):
    from dataclasses import asdict
    payload = asdict(snapshot)
    payload["excluded_issue_ids"] = sorted(snapshot.excluded_issue_ids)
    proc = subprocess.run([str(BINARY)], input=json.dumps(payload), capture_output=True,
                          text=True, check=True)
    rust = json.loads(proc.stdout)
    python = []
    for thread_id, result in evaluate(snapshot).items():
        python.append({
            "thread_id": thread_id, "next_issue_id": result.next_issue_id,
            "eligible": result.eligible,
            "blockers": [asdict(b) for b in result.blockers],
        })
    # Dataclass asdict retains tuples; JSON transport converts them to arrays.
    python = json.loads(json.dumps(python))
    if rust != python:
        raise AssertionError(
            "Rust/Python mismatch: " + json.dumps({"python": python, "rust": rust}, indent=2))
    return len(rust)

def main():
    if not BINARY.is_file():
        raise SystemExit("Compile cargo --release --bin eligibility first")
    base_threads = (
        ReadingThread(1, comicvine_volume_id="a"),
        ReadingThread(2, comicvine_volume_id="b"),
        ReadingThread(3, comicvine_volume_id="c"),
    )
    issues = (ReadingIssue(11,1,1), ReadingIssue(12,1,2),
              ReadingIssue(21,2,1), ReadingIssue(22,2,2),
              ReadingIssue(31,3,1))
    fixtures = [
        ReadingSnapshot(1, threads=base_threads, issues=issues),
        ReadingSnapshot(1, threads=base_threads, issues=issues,
            lists=(ReadingList(1,"strict",(ReadingListEntry(11),ReadingListEntry(21),
                                           ReadingListEntry(12),ReadingListEntry(22))),)),
        ReadingSnapshot(1, threads=base_threads, issues=issues,
            lists=(ReadingList(2,"loose",(ReadingListEntry(11,"hold"),
                                          ReadingListEntry(21),ReadingListEntry(31,"after_previous"))),)),
        ReadingSnapshot(1, threads=base_threads, issues=issues,
            lists=(ReadingList(3,"strict",(ReadingListEntry(11),ReadingListEntry(21),
                                            ReadingListEntry(12),ReadingListEntry(22)),
                overlap_decisions=(SeriesOverlapDecision("b","a"),)),)),
        ReadingSnapshot(1, threads=base_threads, issues=issues,
            lists=(ReadingList(4,"strict",(ReadingListEntry(11,skipped=True),
                                            ReadingListEntry(21), ReadingListEntry(12))),),
            prerequisites=(ReadingPrerequisite(99,31,21,origin="converted",provenance=("fixture",)),)),
        ReadingSnapshot(1, threads=base_threads, issues=issues, excluded_issue_ids=frozenset((11,)),
            lists=(ReadingList(5,"strict",(ReadingListEntry(11),ReadingListEntry(12),
                                           ReadingListEntry(21))),)),
        ReadingSnapshot(1, threads=base_threads, issues=tuple(
            ReadingIssue(i.issue_id, i.thread_id, i.position,
                         "read" if i.issue_id in (11,21) else "unread") for i in issues),
            lists=(ReadingList(6,"strict",(ReadingListEntry(11),ReadingListEntry(21),
                                           ReadingListEntry(12),ReadingListEntry(22))),)),
    ]
    for number, fixture in enumerate(fixtures, 1):
        threads = run_fixture(fixture)
        print(f"Fixture {number}: PASS, {threads} active threads")
    print(f"PASS: {len(fixtures)} Python/Rust evaluator parity fixtures")

if __name__ == "__main__":
    main()
