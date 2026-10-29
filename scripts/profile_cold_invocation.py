#!/usr/bin/env python3
"""Profile *complete* local cold invocations with Python CPU stacks.

Starts each fresh Uvicorn process under py-spy (not by attaching after startup),
sends the first authenticated Roll GET, then stops. A separate unprofiled\nwarm-control process serves multiple GETs for comparison.
The database and HTTP endpoints must remain on loopback. This is an executable
local approximation, NOT a measurement of Vercel's billable Active CPU.
"""

from __future__ import annotations

import argparse
from datetime import UTC, datetime
import json
import os
from pathlib import Path
import secrets
import shutil
import signal
import socket
import subprocess
import sys
import time

# Running this file by path sets sys.path[0] to scripts/, not the repo root.
ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


from scripts.profile_local_traffic import (
    api_process,
    cpu_seconds,
    free_port,
    get,
    local_token,
    safe_database_url,
    safe_route,
    server_environment,
)


def _find_api_child(profiler_pid: int) -> int | None:
    """Find the actual Python server child, not the py-spy sampler process."""
    import psutil

    try:
        children = psutil.Process(profiler_pid).children(recursive=True)
    except (psutil.NoSuchProcess, psutil.AccessDenied):
        return None
    for child in children:
        try:
            args = child.cmdline()
        except (psutil.NoSuchProcess, psutil.AccessDenied):
            continue
        if "uvicorn" in args and "api.index:app" in args:
            return child.pid
    return None


def _await_server(profiler: subprocess.Popen, port: int, timeout: float = 60) -> int:
    """Wait for TCP readiness without sending a warming HTTP request."""
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if profiler.poll() is not None:
            raise RuntimeError("py-spy or its server exited before readiness; inspect server log")
        pid = _find_api_child(profiler.pid)
        if pid is not None:
            try:
                with socket.create_connection(("127.0.0.1", port), timeout=0.2):
                    return pid
            except OSError:
                pass
        time.sleep(0.04)
    raise TimeoutError("Cold Uvicorn startup took over 60 seconds; inspect server log")


def _stop_profile(profiler: subprocess.Popen, server_pid: int | None) -> None:
    """Gracefully shut down the profiled child so py-spy writes its profile."""
    import psutil

    if server_pid is not None and psutil.pid_exists(server_pid):
        try:
            os.kill(server_pid, signal.SIGINT)
        except ProcessLookupError:
            pass
    try:
        profiler.wait(timeout=15)
    except subprocess.TimeoutExpired:
        profiler.terminate()
        try:
            profiler.wait(timeout=5)
        except subprocess.TimeoutExpired:
            profiler.kill()
            profiler.wait(timeout=5)


def profile_samples(path: Path) -> int:
    """Count samples or timeline events in the generated Speedscope profile."""
    data = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(data.get("profiles"), list) or not data["profiles"]:
        raise ValueError("py-spy did not write usable Speedscope stacks")
    return sum(
        len(entry.get("samples", entry.get("events", [])))
        for entry in data["profiles"]
    )


def profile_once(
    db_url: str,
    token: str,
    route: str,
    output: Path,
    iteration: int,
    warm_requests: int,
    sample_rate: int,
) -> dict:
    """Measure process startup plus first request and gather complete CPU stacks."""
    spy = shutil.which("py-spy")
    if spy is None:
        raise RuntimeError("py-spy executable not found; use uv run --with py-spy")
    port = free_port()
    env = server_environment(db_url, port)
    base = f"http://127.0.0.1:{port}"
    speedscope_path = output / f"cold-{iteration}.speedscope.json"
    log_path = output / f"cold-{iteration}.server.log"
    python_cmd = [
        sys.executable, "-m", "uvicorn", "api.index:app",
        "--host", "127.0.0.1", "--port", str(port),
        "--workers", "1", "--no-access-log",
    ]
    command = [
        spy, "record", "--format", "speedscope",
        "--rate", str(sample_rate), "--output", str(speedscope_path),
        "--", *python_cmd,
    ]
    server_pid = None
    proc = None
    result = None
    with log_path.open("wb") as log:
        os.chmod(log_path, 0o600)
        started = time.perf_counter()
        proc = subprocess.Popen(
            command, cwd=ROOT, env=env, stdin=subprocess.DEVNULL,
            stdout=log, stderr=subprocess.STDOUT,
        )
        try:
            server_pid = _await_server(proc, port)
            ready_wall_ms = (time.perf_counter() - started) * 1000
            startup_cpu = cpu_seconds(server_pid)
            first = get(base, safe_route(route), token)
            after_first_cpu = cpu_seconds(server_pid)
            if first["status"] != 200 or not first["cold"]:
                raise RuntimeError(
                    f"First request status={first['status']} cold={first['cold']}; "
                    "aborting invalid cold profile"
                )
            result = {
                "run": iteration,
                "startup_cpu_ms": round(startup_cpu * 1000, 2),
                "startup_wall_ms": round(ready_wall_ms, 2),
                "first_request_cpu_ms": round((after_first_cpu - startup_cpu) * 1000, 2),
                "first_request_wall_ms": first["wall_ms"],
                "full_cold_cpu_ms": round(after_first_cpu * 1000, 2),
                "first_status": first["status"],
                "first_cold_header": first["cold"],
                "first_sql_queries": first["db_queries"],
                "warm_requests": warm_requests,
                "speedscope": str(speedscope_path),
                "server_log": str(log_path),
            }
        finally:
            _stop_profile(proc, server_pid)
    if not speedscope_path.is_file() or speedscope_path.stat().st_size == 0:
        raise RuntimeError(f"CPU stack profile was not generated; inspect {log_path}")
    os.chmod(speedscope_path, 0o600)
    assert result is not None
    result["profile_stack_records"] = profile_samples(speedscope_path)
    if result["profile_stack_records"] == 0:
        raise RuntimeError(f"CPU profile had zero stack records; inspect {log_path}")

    # Warm control runs in a separate process without py-spy's sampling overhead.
    # Its first request performs deferred initialization, then subsequent GETs
    # measure a genuinely warm application with the same isolated database.
    with api_process(db_url, output, f"warm-control-{iteration}") as (warm_proc, warm_base, _):
        warmup = get(warm_base, safe_route(route), token)
        if warmup["status"] != 200:
            raise RuntimeError("Warm control failed its initialization GET")
        before_warm = cpu_seconds(warm_proc.pid)
        warm_results = [
            get(warm_base, safe_route(route), token) for _ in range(warm_requests)
        ]
        warm_cpu = max(0, cpu_seconds(warm_proc.pid) - before_warm)
    if any(r["status"] != 200 for r in warm_results):
        raise RuntimeError("A warm control request failed; discard this run")
    result["warm_cpu_per_request_ms"] = round(warm_cpu * 1000 / warm_requests, 2)
    result["warm_wall_mean_ms"] = round(
        sum(r["wall_ms"] for r in warm_results) / warm_requests, 2
    )
    return result


def summary(results: list[dict]) -> str:
    """Show cold total as startup plus first response, not just readiness."""
    out = [
        "# Complete cold-invocation CPU profiles",
        "",
        "Each run starts a NEW Python interpreter under py-spy, serves its first",
        "authenticated GET, then stops. Warm controls use a SEPARATE unprofiled",
        "fresh process after its first request, avoiding sampler overhead.",
        "CPU is Python process user+system time. py-spy samples Python stacks",
        "but cannot attribute all native/runtime CPU; timings are NOT Vercel billing.",
        "",
        "| Run | Startup CPU | First GET CPU | Full cold CPU | First GET wall | Warm CPU/GET | Samples |",
        "|---:|---:|---:|---:|---:|---:|---:|",
    ]
    for r in results:
        out.append(
            f"| {r['run']} | {r['startup_cpu_ms']} ms | "
            f"{r['first_request_cpu_ms']} ms | {r['full_cold_cpu_ms']} ms | "
            f"{r['first_request_wall_ms']} ms | "
            f"{r['warm_cpu_per_request_ms']} ms | {r['profile_stack_records']} |"
        )
    out.extend([
        "",
        "## Profiles",
        "",
        *[f"- Run {r['run']}: `{r['speedscope']}`" for r in results],
        "",
        "Open a profile with speedscope (https://www.speedscope.app/) or inspect",
        "locally. Profiles may expose source paths; do not publish without review.",
        "",
        "## Limits",
        "",
        "- Loopback PostgreSQL and single-worker Uvicorn, not Vercel's runtime, Neon,",
        "  scaling behavior or platform-side CPU accounting.",
        "- Startup CPU includes interpreter/import/FastAPI startup through TCP readiness.",
        "- First GET CPU includes deferred imports, database activity, rendering.",
        "- py-spy begins sampling as the child launches; very early interpreter",
        "  frames and brief native frames can be missed. More samples improve detail.",
        "- Whole-process CPU includes garbage collection and any other app work.",
        "- Local data is synthetic, not a production data clone.",
        "- No production API or PostgreSQL endpoint is contacted.",
    ])
    return "\n".join(out) + "\n"


def main() -> int:
    """Run strictly loopback authenticated cold profiles."""
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--db-url", default=os.getenv("LOCAL_PROFILE_DATABASE_URL", ""))
    p.add_argument("--username", default="testuser")
    p.add_argument("--password-env", default="LOCAL_PROFILE_PASSWORD")
    p.add_argument("--route", default="/api/v2/roll/bootstrap")
    p.add_argument("--runs", type=int, default=3)
    p.add_argument("--warm-requests", type=int, default=5)
    p.add_argument("--sample-rate", type=int, default=250)
    p.add_argument("--output", type=Path, default=Path(".profile-local"))
    args = p.parse_args()
    try:
        safe_database_url(args.db_url)
        safe_route(args.route)
        if sys.platform not in {"darwin", "linux"}:
            raise ValueError("Requires macOS or Linux")
        if not 1 <= args.runs <= 10 or not 1 <= args.warm_requests <= 50:
            raise ValueError("Runs must be 1-10 and warm requests 1-50")
        if not 50 <= args.sample_rate <= 500:
            raise ValueError("Sample rate must be 50-500")
        if not os.environ.get(args.password_env):
            raise ValueError(f"Set local test password environment: {args.password_env}")
        if shutil.which("py-spy") is None:
            raise RuntimeError("Missing py-spy: run with uv run --with py-spy --with psutil")
        if sys.platform == "darwin":
            import psutil  # noqa: F401
        # All local children, including setup authentication, use the same
        # ephemeral signing key. Never use a production token or secret.
        os.environ["SECRET_KEY"] = secrets.token_urlsafe(48)
        args.output.mkdir(parents=True, exist_ok=True, mode=0o700)
        os.chmod(args.output, 0o700)
        output = args.output / ("cold-" + datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ"))
        output.mkdir(mode=0o700)
        print("Authenticating against the loopback disposable test database...", flush=True)
        token = local_token(args.db_url, output, args.username, os.environ[args.password_env])
        results = []
        for i in range(1, args.runs + 1):
            print(f"Profiling complete cold invocation {i}/{args.runs}...", flush=True)
            results.append(
                profile_once(
                    args.db_url, token, args.route, output, i,
                    args.warm_requests, args.sample_rate,
                )
            )
            print(
                f"  cold CPU {results[-1]['full_cold_cpu_ms']} ms "
                f"vs warm CPU {results[-1]['warm_cpu_per_request_ms']} ms/request",
                flush=True,
            )
        report = summary(results)
        for name, contents in (
            ("report.md", report), ("report.json", json.dumps(results, indent=2) + "\n")
        ):
            path = output / name
            path.write_text(contents, encoding="utf-8")
            os.chmod(path, 0o600)
        print(report)
        print("Reports: " + str(output / "report.md"), flush=True)
        return 0
    except (OSError, ValueError, RuntimeError, TimeoutError) as exc:
        print("Cold CPU profiling failed: " + str(exc), file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
