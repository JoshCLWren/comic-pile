#!/usr/bin/env python3
"""Read-only resident CPU benchmark on the existing disposable testuser snapshot.

Both runtimes receive the exact same loaded scalar input. Python times the
canonical evaluate() only. Rust receives JSON lines and includes deserialization
and serialization CPU, making the compute boundary conservative for Rust.
This is NOT a full Roll endpoint or Vercel billing measurement.
"""
import asyncio
import json
import os
from pathlib import Path
import statistics
import subprocess
import sys
import time
from dataclasses import asdict
from urllib.parse import urlsplit

ROOT=Path(__file__).resolve().parents[2]
sys.path.insert(0,str(ROOT))
from scripts.profile_local_traffic import safe_database_url

BIN=Path(__file__).resolve().parent/"target/release/eligibility"

async def load():
    url=os.environ["LOCAL_PROFILE_DATABASE_URL"]
    safe_database_url(url)
    p=urlsplit(url.replace("+asyncpg",""))
    if p.hostname!="127.0.0.1" or p.port!=55435:
        raise ValueError("Only disposable 127.0.0.1:55435 database permitted")
    os.environ.update(DATABASE_URL=url,TEST_DATABASE_URL=url,
                      ENVIRONMENT="production",TEST_ENVIRONMENT="false")
    from sqlalchemy import text
    from sqlalchemy.ext.asyncio import create_async_engine,async_sessionmaker
    from app.repositories.reading_shadow_repository import load_shadow_inputs
    from app.services.reading_list_evaluator import ReadingSnapshot
    from app.services.reading_list_cycle_validator import validate_reading_constraints
    engine=create_async_engine(url, connect_args={"server_settings":{
        "default_transaction_read_only":"on"}})
    try:
        async with async_sessionmaker(engine)() as db:
            uid=(await db.execute(text("SELECT id FROM users WHERE username=:u"),
                                  {"u":"testuser"})).scalar_one()
            inp=await load_shadow_inputs(db,uid,include_legacy_diagnostics=False)
            if inp.unresolved:
                raise ValueError("Unresolved reader references")
            snapshot=ReadingSnapshot(user_id=inp.user_id,threads=inp.threads,
                issues=inp.issues,lists=inp.lists,prerequisites=inp.prerequisites,
                excluded_issue_ids=inp.excluded_issue_ids)
            validate_reading_constraints(snapshot)
            return snapshot
    finally:
        await engine.dispose()

def main():
    import argparse
    import psutil
    from app.services.reading_list_evaluator import evaluate
    ap=argparse.ArgumentParser()
    ap.add_argument("--pairs",type=int,default=15)
    ap.add_argument("--repetitions",type=int,default=5)
    args=ap.parse_args()
    if not (5<=args.pairs<=50 and 2<=args.repetitions<=50):
        raise ValueError("Use 5..50 pairs and 2..50 repetitions")
    if not BIN.is_file():
        raise FileNotFoundError("Build native eligibility binary first")
    snap=asyncio.run(load())
    payload=asdict(snap)
    payload["excluded_issue_ids"]=sorted(snap.excluded_issue_ids)
    raw=json.dumps(payload,separators=(",",":"))
    def normalize(result):
        return json.loads(json.dumps([
            {"thread_id":tid,"next_issue_id":row.next_issue_id,
             "eligible":row.eligible,"blockers":[asdict(b) for b in row.blockers]}
            for tid,row in result.items()]))
    expected=normalize(evaluate(snap))
    proc=subprocess.Popen([str(BIN),"--stream"],stdin=subprocess.PIPE,
                          stdout=subprocess.PIPE,stderr=subprocess.DEVNULL,
                          text=True,bufsize=1)
    try:
        ps=psutil.Process(proc.pid)
        def rust_call():
            proc.stdin.write(raw+"\n")
            proc.stdin.flush()
            line=proc.stdout.readline()
            if not line:
                raise RuntimeError("Native evaluator exited")
            return json.loads(line)
        if rust_call()!=expected:
            raise AssertionError("Initial Python/Rust parity failed")
        samples={"python":[],"rust":[]}
        for pair in range(args.pairs):
            for kind in (("python","rust") if pair%2==0 else ("rust","python")):
                if kind=="python":
                    before=time.process_time_ns()
                    for _ in range(args.repetitions):
                        if normalize(evaluate(snap))!=expected:
                            raise AssertionError("Python parity drift")
                    ms=(time.process_time_ns()-before)/1e6/args.repetitions
                else:
                    before=ps.cpu_times()
                    for _ in range(args.repetitions):
                        if rust_call()!=expected:
                            raise AssertionError("Rust parity drift")
                    after=ps.cpu_times()
                    ms=((after.user+after.system)-(before.user+before.system))*1000/args.repetitions
                samples[kind].append(ms)
        py=samples["python"]
        rs=samples["rust"]
        delta=[a-b for a,b in zip(py,rs)]
        print(f"PASS: {args.pairs} paired resident measurements; all responses identical")
        print(f"Input: {len(snap.threads)} threads, {len(snap.issues)} issues, "+
              f"{len(snap.lists)} lists, {len(snap.prerequisites)} prerequisites")
        print(f"Python median process CPU per evaluation: {statistics.median(py):.4f} ms")
        print(f"Rust median process CPU per evaluation: {statistics.median(rs):.4f} ms")
        print(f"Paired Python-minus-Rust median: {statistics.median(delta):+.4f} ms")
        print(f"Paired savings range: {min(delta):+.4f}..{max(delta):+.4f} ms")
        print("Limitations: Python excludes input JSON parsing; Rust includes it.")
        print("Read-only database input; not full Roll CPU or Vercel billing.")
    finally:
        proc.stdin.close()
        try:
            proc.wait(timeout=5)
        except subprocess.TimeoutExpired:
            proc.kill()
            proc.wait()

if __name__=="__main__":
    main()
