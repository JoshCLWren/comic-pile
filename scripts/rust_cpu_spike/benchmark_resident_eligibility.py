#!/usr/bin/env python3
"""Resident Rust versus resident Python Option E evaluator CPU.

Uses the identical synthetic snapshot and validates every response.
Rust process CPU includes JSON decode/encode; Python numbers include
asdict + JSON encode/decode to approximate that boundary.
No database, network, or production access.
"""
import json
import os
from pathlib import Path
import statistics
import subprocess
import sys
import time
from dataclasses import asdict
ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
from scripts.rust_cpu_spike.benchmark_eligibility import fixture
from app.services.reading_list_evaluator import evaluate
import psutil

BINARY=Path(__file__).resolve().parent / "target/release/eligibility"

def main():
    import argparse
    ap=argparse.ArgumentParser()
    ap.add_argument("--threads",type=int,default=60)
    ap.add_argument("--samples",type=int,default=25)
    ap.add_argument("--repetitions",type=int,default=20)
    args=ap.parse_args()
    if not (5<=args.threads<=200 and 5<=args.samples<=100 and 2<=args.repetitions<=100):
        raise SystemExit("Invalid benchmark size")
    snapshot=fixture(args.threads)
    payload=asdict(snapshot)
    payload["excluded_issue_ids"]=[]
    raw=json.dumps(payload,separators=(",",":"))
    def python_call():
        result=[
            {"thread_id":thread_id,"next_issue_id":e.next_issue_id,
             "eligible":e.eligible,"blockers":[asdict(b) for b in e.blockers]}
            for thread_id,e in evaluate(snapshot).items()
        ]
        return json.loads(json.dumps(result))
    expected=python_call()
    p=subprocess.Popen([str(BINARY),"--stream"],stdin=subprocess.PIPE,
                       stdout=subprocess.PIPE,stderr=subprocess.DEVNULL,
                       text=True,bufsize=1)
    try:
        rust_proc=psutil.Process(p.pid)
        def rust_call():
            p.stdin.write(raw+"\n")
            p.stdin.flush()
            line=p.stdout.readline()
            if not line:
                raise RuntimeError("Rust evaluator exited unexpectedly")
            return json.loads(line)
        for _ in range(3):
            if rust_call()!=expected:
                raise AssertionError("Rust warmup parity failed")
        rows=[]
        for pair in range(args.samples):
            order=("python","rust") if pair%2==0 else ("rust","python")
            for kind in order:
                if kind=="python":
                    start=time.process_time_ns()
                    for _ in range(args.repetitions):
                        if python_call()!=expected:
                            raise AssertionError("Python parity failed")
                    cpu=(time.process_time_ns()-start)/1e6/args.repetitions
                else:
                    before=rust_proc.cpu_times()
                    for _ in range(args.repetitions):
                        if rust_call()!=expected:
                            raise AssertionError("Rust parity failed")
                    after=rust_proc.cpu_times()
                    cpu=((after.user+after.system)-(before.user+before.system))*1000/args.repetitions
                rows.append({"pair":pair+1,"kind":kind,"cpu_ms_per_eval":cpu})
        for kind in ("python","rust"):
            values=[r["cpu_ms_per_eval"] for r in rows if r["kind"]==kind]
            print(f"{kind} resident median CPU/evaluation: {statistics.median(values):.4f} ms")
        diffs=[next(r["cpu_ms_per_eval"] for r in rows if r["pair"]==i and r["kind"]=="python")-
               next(r["cpu_ms_per_eval"] for r in rows if r["pair"]==i and r["kind"]=="rust")
               for i in range(1,args.samples+1)]
        print(f"Median paired CPU saving (Python minus Rust): {statistics.median(diffs):+.4f} ms")
        print(f"Parity PASS; {args.samples} pairs x {args.repetitions} repetitions, {args.threads} threads")
        print("Note: Rust process CPU is measured using psutil; Python process CPU using process_time.")
        print("Both include response normalization; Rust includes JSON input parsing and IPC in wall time.")
    finally:
        p.stdin.close()
        try:
            p.wait(timeout=5)
        except subprocess.TimeoutExpired:
            p.kill()
            p.wait()
if __name__=="__main__":
    main()
