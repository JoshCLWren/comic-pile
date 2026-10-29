#!/usr/bin/env python3
"""Profile a complete ComicPile cold invocation, including first-request imports.

Requires no sudo on macOS. cProfile instruments a fresh Python/Uvicorn process
from BEFORE importing Uvicorn until its first authenticated GET completes.
Separate uninstrumented cold/warm controls report real process CPU time because
instrumentation can substantially inflate CPU consumption.

All PostgreSQL and HTTP traffic is forced to localhost. Synthetic local data
is not a production clone, and local CPU is NOT Vercel billable Active CPU.
"""

from __future__ import annotations

import argparse
from datetime import UTC, datetime
import json
import os
from pathlib import Path
import pstats
import secrets
import signal
import socket
import subprocess
import sys
import time

# Executing by filename makes scripts/ sys.path[0] rather than repo root.
ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts.profile_local_traffic import (  # noqa: E402
    api_process,
    cpu_seconds,
    free_port,
    get,
    local_token,
    safe_database_url,
    safe_route,
    server_environment,
)


def _await_server(proc: subprocess.Popen, port: int, timeout: float = 60) -> None:
    """Wait for TCP readiness without sending a warming HTTP request."""
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if proc.poll() is not None:
            raise RuntimeError("Profiled API exited before readiness; inspect its server log")
        try:
            with socket.create_connection(("127.0.0.1", port), timeout=0.2):
                return
        except OSError:
            time.sleep(0.04)
    raise TimeoutError("Cold API startup exceeded 60 seconds; inspect server log")


def _stop_profile(proc: subprocess.Popen) -> None:
    """Send SIGINT for normal Uvicorn shutdown and cProfile's finally block."""
    if proc.poll() is not None:
        return
    proc.send_signal(signal.SIGINT)
    try:
        proc.wait(timeout=18)
    except subprocess.TimeoutExpired:
        proc.terminate()
        try:
            proc.wait(timeout=5)
        except subprocess.TimeoutExpired:
            proc.kill()
            proc.wait(timeout=5)


def profile_function_count(path: Path) -> int:
    """Validate that the saved cProfile stats contain real function calls."""
    stats = pstats.Stats(str(path))
    if not stats.stats or stats.total_calls <= 0:
        raise ValueError("Profile has no function call stacks")
    return len(stats.stats)


def _measure_unprofiled(
    db_url: str,
    token: str,
    route: str,
    output: Path,
    iteration: int,
    warm_requests: int,
) -> dict:
    """Measure realistic process CPU without profiler overhead."""
    with api_process(db_url, output, f"cold-control-{iteration}") as (proc, base, startup):
        before_first = cpu_seconds(proc.pid)
        first = get(base, safe_route(route), token)
        after_first = cpu_seconds(proc.pid)
        if first["status"] != 200 or not first["cold"]:
            raise RuntimeError(
                f"Unprofiled cold request status={first['status']} cold={first['cold']}"
            )
        before_warm = cpu_seconds(proc.pid)
        warm = [get(base, safe_route(route), token) for _ in range(warm_requests)]
        warm_cpu = max(0, cpu_seconds(proc.pid) - before_warm)
    if any(item["status"] != 200 for item in warm):
        raise RuntimeError("Unprofiled warm control request failed")
    startup_cpu = startup["cpu_seconds"]
    return {
        "run": iteration,
        "startup_cpu_ms": round(startup_cpu * 1000, 2),
        "startup_wall_ms": startup["wall_ms"],
        "first_request_cpu_ms": round((after_first - before_first) * 1000, 2),
        "first_request_wall_ms": first["wall_ms"],
        "full_cold_cpu_ms": round(after_first * 1000, 2),
        "first_status": first["status"],
        "first_cold_header": first["cold"],
        "first_sql_queries": first["db_queries"],
        "warm_cpu_per_request_ms": round(warm_cpu * 1000 / warm_requests, 2),
        "warm_wall_mean_ms": round(sum(item["wall_ms"] for item in warm) / warm_requests, 2),
        "warm_requests": warm_requests,
    }


def _record_cpu_call_graph(
    db_url: str,
    token: str,
    route: str,
    output: Path,
    iteration: int,
) -> dict:
    """Run a SEPARATE, profiled cold request for call-stack attribution."""
    port = free_port()
    env = server_environment(db_url, port)
    base = f"http://127.0.0.1:{port}"
    stats_path = (output / f"cold-{iteration}.pstats").resolve()
    log_path = output / f"cold-{iteration}.server.log"
    command = [
        sys.executable, str(ROOT / "scripts" / "profile_cold_server.py"),
        "--port", str(port), "--output", str(stats_path),
    ]
    with log_path.open("wb") as log:
        os.chmod(log_path, 0o600)
        proc = subprocess.Popen(
            command,
            cwd=ROOT,
            env=env,
            stdin=subprocess.DEVNULL,
            stdout=log,
            stderr=subprocess.STDOUT,
        )
        try:
            _await_server(proc, port)
            first = get(base, safe_route(route), token)
            if first["status"] != 200 or not first["cold"]:
                raise RuntimeError(
                    f"Profiled cold request status={first['status']} cold={first['cold']}; "
                    f"inspect {log_path}"
                )
        finally:
            _stop_profile(proc)
    top_path = stats_path.with_suffix(".top.txt")
    if not stats_path.is_file() or not top_path.is_file():
        raise RuntimeError(f"CPU call graph missing; inspect {log_path}")
    os.chmod(stats_path, 0o600)
    os.chmod(top_path, 0o600)
    return {
        "profile_functions": profile_function_count(stats_path),
        "profile_path": str(stats_path),
        "profile_top_path": str(top_path),
        "profile_server_log": str(log_path),
    }


def profile_once(
    db_url: str,
    token: str,
    route: str,
    output: Path,
    iteration: int,
    warm_requests: int,
) -> dict:
    """Pair an unprofiled CPU baseline with an instrumented cold call graph."""
    measured = _measure_unprofiled(db_url, token, route, output, iteration, warm_requests)
    profiled = _record_cpu_call_graph(db_url, token, route, output, iteration)
    return {**measured, **profiled}


def summary(results: list[dict]) -> str:
    """Present UNPROFILED CPU timings and locations of profiled call stacks."""
    out = [
        "# Complete local cold-invocation CPU profile",
        "",
        "**CPU numbers below are from unprofiled processes**, not from cProfile.",
        "Each run starts a fresh Python process, measures readiness plus its",
        "first authenticated GET, then compares several warmed-up GETs.",
        "A SEPARATE fresh process is CPU-profiled from before importing Uvicorn",
        "through the first GET; its call graph is for attribution, not cost.",
        "These are Python process user+system CPU values, NOT Vercel billing.",
        "",
        "| Run | Startup CPU | First GET CPU | Total cold CPU | First GET wall | Warm CPU/GET | Functions |",
        "|---:|---:|---:|---:|---:|---:|---:|",
    ]
    for r in results:
        out.append(
            f"| {r['run']} | {r['startup_cpu_ms']} ms | "
            f"{r['first_request_cpu_ms']} ms | {r['full_cold_cpu_ms']} ms | "
            f"{r['first_request_wall_ms']} ms | "
            f"{r['warm_cpu_per_request_ms']} ms | {r['profile_functions']} |"
        )
    out.extend(["", "## Hot-function reports and call graphs", ""])
    for r in results:
        out.append(
            f"- Run {r['run']}: `{r['profile_top_path']}` (top self and cumulative CPU)"
            f"; `{r['profile_path']}` (cProfile call graph)"
        )
    out.extend([
        "",
        "For a local interactive call graph, run snakeviz against a .pstats file.",
        "The .top.txt files need only 'cat' and can be pasted for analysis.",
        "",
        "## Limits",
        "",
        "- The separate cProfile run has instrumentation overhead; its times MUST",
        "  NOT be compared directly with the uninstrumented CPU baseline.",
        "- The profile captures Python calls and built-in function time, not all",
        "  native stacks. time.process_time() is the CPU timer for call attribution.",
        "- Loopback PostgreSQL and one Uvicorn worker are not the Vercel runtime.",
        "- Synthetic fixture, not a faithful clone of real ComicPile data.",
        "- Neither Vercel billed CPU nor platform cold-start scheduling is measured.",
        "- No production API or database endpoint is contacted.",
    ])
    return "\n".join(out) + "\n"


def main() -> int:
    """Run strictly loopback full-cold CPU measurement and call-stack profiling."""
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--db-url", default=os.getenv("LOCAL_PROFILE_DATABASE_URL", ""))
    p.add_argument("--username", default="testuser")
    p.add_argument("--password-env", default="LOCAL_PROFILE_PASSWORD")
    p.add_argument("--route", default="/api/v2/roll/bootstrap")
    p.add_argument("--runs", type=int, default=3)
    p.add_argument("--warm-requests", type=int, default=5)
    p.add_argument("--output", type=Path, default=Path(".profile-local"))
    args = p.parse_args()
    try:
        safe_database_url(args.db_url)
        safe_route(args.route)
        if sys.platform not in {"darwin", "linux"}:
            raise ValueError("Requires macOS or Linux")
        if not 1 <= args.runs <= 10 or not 1 <= args.warm_requests <= 50:
            raise ValueError("Runs must be 1-10 and warm requests 1-50")
        if not os.environ.get(args.password_env):
            raise ValueError(f"Set LOCAL test password in: {args.password_env}")
        if sys.platform == "darwin":
            import psutil  # noqa: F401
        # Distinct temporary signing key, shared only by loopback subprocesses.
        os.environ["SECRET_KEY"] = secrets.token_urlsafe(48)
        args.output.mkdir(parents=True, exist_ok=True, mode=0o700)
        os.chmod(args.output, 0o700)
        output = args.output / ("cold-" + datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ"))
        output.mkdir(mode=0o700)
        print("Authenticating against the disposable loopback database...", flush=True)
        token = local_token(args.db_url, output, args.username, os.environ[args.password_env])
        results = []
        for i in range(1, args.runs + 1):
            print(f"Measuring and profiling cold invocation {i}/{args.runs}...", flush=True)
            result = profile_once(
                args.db_url, token, args.route, output, i, args.warm_requests
            )
            results.append(result)
            print(
                f"  unprofiled cold CPU {result['full_cold_cpu_ms']} ms; "
                f"warm CPU {result['warm_cpu_per_request_ms']} ms/GET; "
                f"{result['profile_functions']} profiled functions",
                flush=True,
            )
        report = summary(results)
        for name, contents in (
            ("report.md", report), ("report.json", json.dumps(results, indent=2) + "\n")
        ):
            path = output / name
            path.write_text(contents, encoding="utf-8")
            os.chmod(path, 0o600)
        print(report, flush=True)
        print("Reports: " + str(output / "report.md"), flush=True)
        return 0
    except (OSError, ValueError, RuntimeError, TimeoutError) as exc:
        print("Cold CPU profiling failed: " + str(exc), file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
