#!/usr/bin/env python3
"""Paired read-only last-read projection CPU benchmark, NOT full Roll bootstrap."""
from __future__ import annotations
import argparse
import json
import os
from pathlib import Path
import secrets
import socket
import statistics
import subprocess
import sys
import time
from urllib import request

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
from scripts.profile_local_traffic import (
    cpu_seconds, free_port, local_token, safe_database_url, server_environment
)

BIN = Path(__file__).resolve().parent / "target/release/comicpile-rust-cpu-spike"

def sample(kind, db_url, token, session_id, output, label, warm):
    import psutil
    port = free_port()
    env = server_environment(db_url, port)
    env["LOCAL_PROFILE_DATABASE_URL"] = db_url.replace("+asyncpg", "") if kind == "rust" else db_url
    env["RUST_SPIKE_PORT"] = str(port)
    cmd = [str(BIN)] if kind == "rust" else [
        sys.executable, "-m", "uvicorn",
        "scripts.rust_cpu_spike.python_comparator:app",
        "--host", "127.0.0.1", "--port", str(port), "--no-access-log"
    ]
    with (output / (label + ".log")).open("wb") as log:
        started = time.perf_counter()
        proc = subprocess.Popen(cmd, cwd=ROOT, env=env, stdin=subprocess.DEVNULL,
                                stdout=log, stderr=subprocess.STDOUT)
        try:
            for _ in range(2000):
                if proc.poll() is not None:
                    raise RuntimeError(f"{kind} failed startup; inspect {label}.log")
                try:
                    with socket.create_connection(("127.0.0.1", port), timeout=.1):
                        break
                except OSError:
                    time.sleep(.02)
            else:
                raise TimeoutError("Server not ready")
            startup = cpu_seconds(proc.pid)
            process = psutil.Process(proc.pid)
            path = f"http://127.0.0.1:{port}/spike/sessions/{session_id}/last-read"
            def invoke():
                req = request.Request(path, headers={"Authorization": "Bearer " + token})
                t = time.perf_counter()
                with request.build_opener(request.ProxyHandler({})).open(req, timeout=15) as r:
                    return json.load(r), (time.perf_counter() - t) * 1000
            first, first_wall = invoke()
            after = cpu_seconds(proc.pid)
            warm_start = after
            for _ in range(warm):
                obj, _ = invoke()
                if obj != first:
                    raise AssertionError("Response changed within one measurement")
            warm_end = cpu_seconds(proc.pid)
            return {
                "startup_cpu_ms": startup * 1000,
                "first_cpu_ms": (after-startup)*1000,
                "cold_cpu_ms": after*1000,
                "warm_cpu_ms": (warm_end-warm_start)*1000/warm,
                "first_wall_ms": first_wall,
                "rss_mb_observed": process.memory_info().rss/(1024*1024)
            }, first
        finally:
            proc.terminate()
            try:
                proc.wait(timeout=5)
            except subprocess.TimeoutExpired:
                proc.kill()
                proc.wait()

def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--session-id", type=int, required=True)
    ap.add_argument("--pairs", type=int, default=5)
    ap.add_argument("--warm", type=int, default=10)
    ap.add_argument("--output", type=Path, default=Path(".profile-local/rust-spike"))
    a = ap.parse_args()
    db = os.environ["LOCAL_PROFILE_DATABASE_URL"]
    safe_database_url(db)
    from urllib.parse import urlsplit
    url = urlsplit(db.replace("+asyncpg", ""))
    if url.hostname != "127.0.0.1" or url.port != 55435:
        raise ValueError("Only the existing disposable loopback DB is allowed")
    if a.pairs < 5 or a.warm < 2 or not BIN.is_file():
        raise ValueError("Need >=5 pairs, >=2 warm requests and precompiled release binary")
    a.output.mkdir(parents=True, exist_ok=True)
    os.chmod(a.output, 0o700)
    os.environ["SECRET_KEY"] = secrets.token_urlsafe(48)
    token = local_token(db, a.output, "testuser", os.environ["LOCAL_PROFILE_PASSWORD"])
    results = []
    for n in range(1, a.pairs+1):
        observed = {}
        for kind in (("python", "rust") if n % 2 else ("rust", "python")):
            print(f"Pair {n}: {kind}", flush=True)
            metrics, body = sample(kind, db, token, a.session_id, a.output, f"{n}-{kind}", a.warm)
            observed[kind] = body
            results.append({"pair": n, "kind": kind, **metrics})
        if observed["python"] != observed["rust"]:
            raise AssertionError(f"JSON parity failed at pair {n}")
    metrics = ("startup_cpu_ms", "first_cpu_ms", "cold_cpu_ms",
               "warm_cpu_ms", "first_wall_ms", "rss_mb_observed")
    medians = {k: {m: round(statistics.median(r[m] for r in results if r["kind"] == k), 3)
                   for m in metrics} for k in ("python", "rust")}
    paired = {m: [round(next(r[m] for r in results if r["pair"] == n and r["kind"] == "python")
                      - next(r[m] for r in results if r["pair"] == n and r["kind"] == "rust"), 3)
                   for n in range(1, a.pairs+1)] for m in metrics}
    result = {"scope": "last-read subset, NOT complete Roll bootstrap",
              "parity": "PASS", "medians": medians,
              "paired_python_minus_rust": paired, "samples": results}
    output = a.output / "results.json"
    output.write_text(json.dumps(result, indent=2))
    os.chmod(output, 0o600)
    print(json.dumps({k: v for k, v in result.items() if k != "samples"}, indent=2))
    print("Report:", output)

if __name__ == "__main__":
    main()
