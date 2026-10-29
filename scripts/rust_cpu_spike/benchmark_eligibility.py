#!/usr/bin/env python3
"""Measure pure Option E evaluation with identical synthetic input and JSON parity.

Subprocess Rust invocation is measured separately from resident Python evaluation.
This is a pure compute microbenchmark, not full Roll or equivalent process startup.
"""
from __future__ import annotations
import json
import os
from pathlib import Path
import statistics
import subprocess
import sys
import time
ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
from dataclasses import asdict
from app.services.reading_list_evaluator import (
    ReadingIssue, ReadingThread, ReadingList, ReadingListEntry,
    ReadingPrerequisite, ReadingSnapshot, evaluate
)

BIN = Path(__file__).resolve().parent / "target/release/eligibility"

def fixture(size: int) -> ReadingSnapshot:
    threads = tuple(ReadingThread(t, comicvine_volume_id=str(t)) for t in range(1, size+1))
    issues = tuple(ReadingIssue(t*100+j,t,j,"read" if j == 1 else "unread")
                   for t in range(1,size+1) for j in range(1,5))
    lists = (ReadingList(1,"strict",tuple(
        ReadingListEntry(t*100+2) for t in range(1,size+1))),)
    prerequisites = tuple(ReadingPrerequisite(t,t*100+3,(t+1)*100+2)
                          for t in range(1,size))
    return ReadingSnapshot(1, threads=threads, issues=issues,
                           lists=lists, prerequisites=prerequisites)

def main():
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument("--threads",type=int,default=60)
    parser.add_argument("--pairs",type=int,default=15)
    args=parser.parse_args()
    if not (5 <= args.threads <= 200 and 5 <= args.pairs <= 100):
        raise SystemExit("threads 5..200 and pairs 5..100 required")
    snapshot = fixture(args.threads)
    payload = asdict(snapshot)
    payload["excluded_issue_ids"] = []
    serialized = json.dumps(payload)
    if not BIN.is_file():
        raise SystemExit("Build native eligibility binary first")
    def python_result():
        return json.loads(json.dumps([
            {"thread_id": t, "next_issue_id": v.next_issue_id,
             "eligible": v.eligible, "blockers": [asdict(b) for b in v.blockers]}
            for t,v in evaluate(snapshot).items()
        ]))
    expected=python_result()
    rust = subprocess.run([str(BIN)],input=serialized,text=True,capture_output=True,check=True)
    if json.loads(rust.stdout) != expected:
        raise AssertionError("Rust/Python evaluator parity failed")
    samples=[]
    for pair in range(1,args.pairs+1):
        order=("python","rust") if pair % 2 else ("rust","python")
        for kind in order:
            start_cpu=time.process_time_ns()
            start_wall=time.perf_counter_ns()
            if kind == "python":
                result=python_result()
                cpu_ms=(time.process_time_ns()-start_cpu)/1e6
            else:
                import resource
                before=resource.getrusage(resource.RUSAGE_CHILDREN)
                proc=subprocess.run([str(BIN)],input=serialized,text=True,capture_output=True,check=True)
                after=resource.getrusage(resource.RUSAGE_CHILDREN)
                cpu_ms=((after.ru_utime+after.ru_stime)-(before.ru_utime+before.ru_stime))*1000
                result=json.loads(proc.stdout)
            wall_ms=(time.perf_counter_ns()-start_wall)/1e6
            if result != expected:
                raise AssertionError(f"Parity failed pair {pair} {kind}")
            samples.append((pair,kind,cpu_ms,wall_ms))
    for kind in ("python","rust"):
        values=[r for r in samples if r[1]==kind]
        print(f"{kind}: median CPU={statistics.median(r[2] for r in values):.3f} ms; "
              f"median wall={statistics.median(r[3] for r in values):.3f} ms")
    diffs=[next(r[2] for r in samples if r[0]==pair and r[1]=="python")-
           next(r[2] for r in samples if r[0]==pair and r[1]=="rust")
           for pair in range(1,args.pairs+1)]
    print(f"Paired Python-Rust CPU saved median={statistics.median(diffs):.3f} ms; "
          f"range={min(diffs):.3f}..{max(diffs):.3f} ms")
    print(f"Parity PASS: {args.pairs} pairs, {args.threads} threads, {len(snapshot.issues)} issues")
    print("Caveat: Python is resident in the parent process; Rust CPU includes fresh binary process startup and JSON I/O.")

if __name__=="__main__":
    main()
