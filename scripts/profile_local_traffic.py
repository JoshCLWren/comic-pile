#!/usr/bin/env python3
"""Replay safe local GET traffic and measure actual FastAPI process CPU.

All HTTP and PostgreSQL traffic is forced to loopback. Never targets production.
Run against a disposable, production-shaped LOCAL database copy.
"""
from __future__ import annotations

import argparse
import concurrent.futures
import contextlib
from dataclasses import dataclass
from datetime import UTC, datetime
import json
import os
import secrets
from pathlib import Path
import socket
import subprocess
import sys
import threading
import time
from urllib import error, parse, request

LOCAL_HOSTS = {"127.0.0.1", "localhost", "::1"}
DEFAULT_ROUTES = (
    "/api/v1/auth/me",
    "/api/v1/roll/bootstrap",
    "/api/v1/threads/",
    "/api/v1/users/me/preferences",
    "/api/v1/identity-inbox",
    "/api/v1/reading-mode",
)


@dataclass(frozen=True)
class Traffic:
    """Represent a sanitized API request and its replay offset."""
    url: str
    route: str
    offset: float = 0.0


def safe_database_url(value: str) -> parse.SplitResult:
    """Validate that a PostgreSQL URL targets an explicitly named local database."""
    p = parse.urlsplit(value)
    if p.scheme not in {"postgres", "postgresql", "postgresql+asyncpg"}:
        raise ValueError("Use a PostgreSQL URL")
    if p.hostname not in LOCAL_HOSTS or p.port is None:
        raise ValueError("Refusing non-local PostgreSQL; use localhost with an explicit port")
    if not p.path or p.path == "/":
        raise ValueError("Specify a named disposable local database")
    if {"host", "hostaddr", "service", "servicefile"} & set(parse.parse_qs(p.query)):
        raise ValueError("Database URL may not override the loopback host")
    return p


def proxy_url(p: parse.SplitResult, port: int) -> str:
    """Route an existing local PostgreSQL connection through the delay proxy."""
    auth = p.netloc.rsplit("@", 1)[0] + "@" if "@" in p.netloc else ""
    return parse.urlunsplit((p.scheme, f"{auth}127.0.0.1:{port}", p.path, p.query, ""))


def safe_route(url: str) -> Traffic:
    """Validate and sanitize a GET-only API route for safe replay."""
    p = parse.urlsplit(url)
    if p.scheme and p.scheme not in {"http", "https"}:
        raise ValueError("Invalid URL scheme")
    if p.path != "/api" and not p.path.startswith("/api/"):
        raise ValueError("Only API GET paths can be replayed")
    if "\r" in url or "\n" in url:
        raise ValueError("Invalid URL")
    # HARs may contain credentials in query strings. Reject, never forward them.
    sensitive = ("token", "password", "secret", "api_key", "auth", "signature",
                 "session", "jwt", "client_secret", "access_key")
    if any(any(part in key.lower() for part in sensitive)
           for key, _ in parse.parse_qsl(p.query, keep_blank_values=True)):
        raise ValueError("Sensitive query parameters may not be replayed")
    return Traffic(p.path + ("?" + p.query if p.query else ""), p.path)


def read_har(filename: Path) -> tuple[list[Traffic], int]:
    """Extract safe, chronological GET requests from a HAR capture."""
    entries = json.loads(filename.read_text(encoding="utf-8"))["log"]["entries"]
    if not isinstance(entries, list) or len(entries) > 5000:
        raise ValueError("Invalid or too-large HAR")
    eligible: list[tuple[datetime, Traffic]] = []
    skipped = 0
    for entry in entries:
        req = entry.get("request", {})
        if req.get("method", "").upper() != "GET":
            skipped += 1
            continue
        try:
            route = safe_route(req["url"])
            when = datetime.fromisoformat(entry["startedDateTime"].replace("Z", "+00:00"))
            if when.tzinfo is None:
                raise ValueError("Timezone missing")
            eligible.append((when, route))
        except (KeyError, ValueError, TypeError):
            skipped += 1
        if len(eligible) > 400:
            raise ValueError("Limit HAR replay to 400 GET /api entries")
    if not eligible:
        raise ValueError("HAR contains no eligible API GET requests")
    eligible.sort(key=lambda item: item[0])
    start = eligible[0][0]
    return [Traffic(item.url, item.route, (when - start).total_seconds())
            for when, item in eligible], skipped


class DelayProxy:
    """Simple PostgreSQL TCP delay injector; delay is per chunk, not per query."""

    def __init__(self, host: str, port: int, delay_ms: int) -> None:
        """Create and start the loopback PostgreSQL TCP delay proxy."""
        self.target = (host, port)
        self.delay = delay_ms / 1000
        self.stop_event = threading.Event()
        self.listener = socket.socket()
        self.listener.bind(("127.0.0.1", 0))
        self.listener.listen(32)
        self.listener.settimeout(0.25)
        self.port = self.listener.getsockname()[1]
        self.thread = threading.Thread(target=self._accept, daemon=True)
        self.thread.start()

    def _accept(self) -> None:
        while not self.stop_event.is_set():
            try:
                client, _ = self.listener.accept()
            except TimeoutError:
                continue
            except OSError:
                break
            threading.Thread(target=self._bridge, args=(client,), daemon=True).start()

    def _forward(self, src: socket.socket, dst: socket.socket) -> None:
        try:
            while not self.stop_event.is_set():
                packet = src.recv(65536)
                if not packet:
                    break
                if self.delay:
                    time.sleep(self.delay)
                dst.sendall(packet)
        except OSError:
            pass
        finally:
            try:
                dst.shutdown(socket.SHUT_WR)
            except OSError:
                pass

    def _bridge(self, client: socket.socket) -> None:
        try:
            upstream = socket.create_connection(self.target, timeout=10)
        except OSError:
            client.close()
            return
        with client, upstream:
            a = threading.Thread(target=self._forward, args=(client, upstream), daemon=True)
            b = threading.Thread(target=self._forward, args=(upstream, client), daemon=True)
            a.start()
            b.start()
            a.join(timeout=35)
            b.join(timeout=35)

    def close(self) -> None:
        """Stop the delay proxy and release its listener."""
        self.stop_event.set()
        self.listener.close()
        self.thread.join(timeout=1)


def cpu_seconds(pid: int) -> float:
    """Read process user+system CPU time (never elapsed/wall time).

    Linux can use /proc without dependencies. macOS requires psutil because
    /proc/PID/stat does not exist there; install it via uv run --with psutil.
    """
    if sys.platform.startswith("linux"):
        stat = Path(f"/proc/{pid}/stat").read_text(encoding="ascii")
        fields = stat[stat.rfind(")") + 2:].split()
        return (int(fields[11]) + int(fields[12])) / os.sysconf("SC_CLK_TCK")
    if sys.platform == "darwin":
        try:
            import psutil
        except ImportError as exc:
            raise RuntimeError(
                "macOS CPU profiling needs psutil: "
                "use uv run --with psutil python scripts/profile_local_traffic.py ..."
            ) from exc
        times = psutil.Process(pid).cpu_times()
        return float(times.user + times.system)
    raise RuntimeError("Only Linux and macOS process CPU measurement is supported")


def free_port() -> int:
    """Reserve and return an available loopback TCP port."""
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return sock.getsockname()[1]


@contextlib.contextmanager
def api_process(db_url: str, output: Path, label: str):
    """Run a fresh single-worker local API process for one measured scenario."""
    port = free_port()
    env = dict(os.environ)
    env.update(DATABASE_URL=db_url, TEST_DATABASE_URL=db_url,
               TEST_ENVIRONMENT="false", ENVIRONMENT="production",
               SECRET_KEY=os.environ["SECRET_KEY"],
               # A production-mode app requires an explicit non-wildcard CORS
               # origin, even for loopback-only profile requests.
               CORS_ORIGINS=f"http://127.0.0.1:{port}",
               NEON_TOKEN="", NEON_PROJECT_ID="",
               PERF_ALARM_GITHUB_ISSUES_ENABLED="false",
               COMICVINE_API_KEY="", GITHUB_TOKEN="")
    log_path = output / (label + ".server.log")
    with log_path.open("wb") as log:
        os.chmod(log_path, 0o600)
        started = time.perf_counter()
        proc = subprocess.Popen(
            [sys.executable, "-m", "uvicorn", "api.index:app", "--host",
             "127.0.0.1", "--port", str(port), "--workers", "1", "--no-access-log"],
            cwd=Path(__file__).resolve().parents[1], env=env,
            stdin=subprocess.DEVNULL, stdout=log, stderr=subprocess.STDOUT,
        )
        try:
            deadline = time.monotonic() + 60
            while time.monotonic() < deadline:
                if proc.poll() is not None:
                    raise RuntimeError("API failed to start; inspect " + str(log_path))
                try:
                    with socket.create_connection(("127.0.0.1", port), timeout=0.2):
                        break  # TCP readiness only; no HTTP request warming
                except OSError:
                    time.sleep(0.08)
            else:
                raise TimeoutError("API startup timed out; inspect " + str(log_path))
            startup = {"wall_ms": round((time.perf_counter() - started) * 1000, 2),
                       "cpu_seconds": round(cpu_seconds(proc.pid), 5)}
            yield proc, "http://127.0.0.1:" + str(port), startup
        finally:
            proc.terminate()
            try:
                proc.wait(timeout=8)
            except subprocess.TimeoutExpired:
                proc.kill()
                proc.wait(timeout=3)


class BlockRedirects(request.HTTPRedirectHandler):
    """Prevent replay authentication and profiling from following redirects."""
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        """Reject redirects so request targets remain on the local API."""
        return None


def http(base: str, path: str, token: str | None,
         method: str = "GET", body: bytes | None = None):
    """Issue a timed local HTTP request without following redirects."""
    headers = {"Accept": "application/json"}
    if token:
        headers["Authorization"] = "Bearer " + token
    if body is not None:
        headers["Content-Type"] = "application/json"
    req = request.Request(base + path, data=body, method=method, headers=headers)
    opener = request.build_opener(request.ProxyHandler({}), BlockRedirects())
    t = time.perf_counter()
    try:
        with opener.open(req, timeout=18) as r:
            return r.status, r.read(), dict(r.headers), (time.perf_counter() - t) * 1000
    except error.HTTPError as exc:
        with exc:
            return exc.code, exc.read(), dict(exc.headers), (time.perf_counter() - t) * 1000


def get(base: str, item: Traffic, token: str) -> dict:
    """Collect a single API request's status, latency, and optional query count."""
    try:
        status, _, headers, ms = http(base, item.url, token)
        queries = headers.get("X-App-DB-Queries")
        return {"route": item.route, "status": status, "wall_ms": round(ms, 2),
                "db_queries": int(queries) if queries and queries.isdigit() else None,
                "cold": headers.get("X-App-Cold-Request") == "1"}
    except (OSError, TimeoutError, ValueError) as exc:
        return {"route": item.route, "status": 0, "wall_ms": None,
                "db_queries": None, "cold": False, "error": type(exc).__name__}


def burst(base: str, items: list[Traffic], token: str, workers: int,
          speed: float) -> tuple[list[dict], float]:
    """Replay concurrent requests at their captured relative offsets."""
    t = time.monotonic()
    with concurrent.futures.ThreadPoolExecutor(max_workers=workers) as pool:
        futures = []
        for item in items:
            wait = t + item.offset / speed - time.monotonic()
            if wait > 0:
                time.sleep(wait)
            futures.append(pool.submit(get, base, item, token))
        responses = [future.result() for future in futures]
    return responses, round(time.monotonic() - t, 3)


def local_token(db_url: str, output: Path, username: str, password: str) -> str:
    """Authenticate against a disposable local API process before profiling."""
    # Setup in a separate local process so authentication does not warm the profiles.
    with api_process(db_url, output, "setup-auth") as (_, base, _):
        status, data, _, _ = http(
            base, "/api/v1/auth/login", None, method="POST",
            body=json.dumps({"username": username, "password": password}).encode(),
        )
        if status != 200:
            raise RuntimeError(f"Local user login returned HTTP {status}")
        token = json.loads(data).get("access_token")
        if not isinstance(token, str) or not token:
            raise RuntimeError("Local login did not provide an access token")
        return token


def profile(db_url: str, delay: int, output: Path, items: list[Traffic],
            token: str, workers: int, speed: float, repeats: int) -> dict:
    """Measure cold, warm, and concurrent API behavior with optional DB latency."""
    db = safe_database_url(db_url)
    proxy = DelayProxy(db.hostname or "127.0.0.1", db.port or 5432, delay) if delay else None
    chosen_url = proxy_url(db, proxy.port) if proxy else db_url
    try:
        with api_process(chosen_url, output, f"delay-{delay}-warm") as (proc, base, startup):
            before = cpu_seconds(proc.pid)
            cold = get(base, Traffic("/api/v1/auth/me", "/api/v1/auth/me"), token)
            cold_cpu = max(0, cpu_seconds(proc.pid) - before)
            sequential = []
            for url in dict.fromkeys(item.url for item in items):
                item = safe_route(url)
                for idx in range(repeats):
                    before = cpu_seconds(proc.pid)
                    response = get(base, item, token)
                    sequential.append({**response, "iteration": idx + 1,
                                       "cpu_seconds": round(max(0, cpu_seconds(proc.pid) - before), 5)})
            before = cpu_seconds(proc.pid)
            responses, wall = burst(base, items, token, workers, speed)
            warm_cpu = max(0, cpu_seconds(proc.pid) - before)
        with api_process(chosen_url, output, f"delay-{delay}-fresh") as (proc, base, fresh):
            before = cpu_seconds(proc.pid)
            first_responses, first_wall = burst(base, items, token, workers, speed)
            fresh_cpu = max(0, cpu_seconds(proc.pid) - before)
        return {
            "delay_ms_per_tcp_chunk": delay, "startup": startup,
            "cold_auth": {**cold, "cpu_seconds": round(cold_cpu, 5)},
            "sequential": sequential,
            "warm_burst": {"cpu_seconds": round(warm_cpu, 5), "wall_seconds": wall,
                           "responses": responses},
            "fresh_burst": {"startup": fresh, "cpu_seconds": round(fresh_cpu, 5),
                            "wall_seconds": first_wall, "responses": first_responses},
        }
    finally:
        if proxy:
            proxy.close()


def report_markdown(data: dict) -> str:
    """Render the measured CPU, wall-time, and request data as Markdown."""
    out = [
        "# Local ComicPile CPU profile",
        "",
        "CPU is process user+system time, not elapsed time or Vercel billed CPU.",
        "The delay proxy adds latency per PostgreSQL TCP packet/chunk, not per SQL query.",
        "Concurrent samples report whole-process CPU only; do not assign it to individual calls.",
        "",
        "| Delay/chunk | Startup CPU | Auth cold CPU | Warm burst CPU | Fresh burst CPU | Warm wall | Failed GETs |",
        "|---:|---:|---:|---:|---:|---:|---:|",
    ]
    for entry in data["profiles"]:
        warm = entry["warm_burst"]
        failed = sum(r["status"] < 200 or r["status"] >= 400 for r in warm["responses"])
        out.append(
            f"| {entry['delay_ms_per_tcp_chunk']}ms | {entry['startup']['cpu_seconds']:.3f}s"
            f" | {entry['cold_auth']['cpu_seconds']:.3f}s"
            f" | {warm['cpu_seconds']:.3f}s | {entry['fresh_burst']['cpu_seconds']:.3f}s"
            f" | {warm['wall_seconds']:.2f}s | {failed} |"
        )
    out.extend(["", "## Isolated last-iteration route samples", "",
                "| Delay/chunk | Route | CPU | Wall | SQL queries | Status |",
                "|---:|---|---:|---:|---:|---:|"])
    for entry in data["profiles"]:
        last = {r["route"]: r for r in entry["sequential"]}
        for route, row in sorted(last.items(), key=lambda x: -x[1]["cpu_seconds"]):
            out.append(
                f"| {entry['delay_ms_per_tcp_chunk']}ms | {route} | {row['cpu_seconds']:.4f}s"
                f" | {row['wall_ms']}ms | {row['db_queries']} | {row['status']} |"
            )
    out.extend(["", "## Limitations", "",
                "- The local single-worker server differs from Vercel's multi-instance scheduling.",
                "- Linux /proc CPU readings are quantized to clock ticks; macOS uses psutil; repeat measurements.",
                "- Startup CPU is measured before the first HTTP request; deferred imports are included in first-hit CPU.",
                "- HAR GETs can return 404 when copied production issue IDs differ on the local database.",
                "- The harness never replays mutating methods, cookies, or authorization headers from a HAR.",
                "- Traffic counts here describe this workload, not total monthly production invocations.",
                "- No production API or PostgreSQL endpoint is contacted."])
    return "\n".join(out) + "\n"


def main() -> int:
    """Parse options, enforce local-only safety constraints, and run profiles."""
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--db-url", default=os.getenv("LOCAL_PROFILE_DATABASE_URL", ""))
    ap.add_argument("--username", help="Existing LOCAL test account name")
    ap.add_argument("--password-env", default="LOCAL_PROFILE_PASSWORD")
    ap.add_argument("--token-env", default="LOCAL_PROFILE_ACCESS_TOKEN")
    ap.add_argument("--har", type=Path, help="HAR file; only GET /api entries are replayed")
    ap.add_argument("--route", action="append", default=[], help="Override default GET route")
    ap.add_argument("--delays", default="0,100,500", help="Comma-separated DB TCP chunk delays, ms")
    ap.add_argument("--workers", type=int, default=8)
    ap.add_argument("--speed", type=float, default=10.0, help="HAR timing acceleration")
    ap.add_argument("--repeats", type=int, default=3)
    ap.add_argument("--output", type=Path, default=Path(".profile-local"))
    args = ap.parse_args()
    try:
        safe_database_url(args.db_url)
        if sys.platform not in {"darwin", "linux"}:
            raise ValueError("This profiler supports macOS or Linux")
        if sys.platform == "darwin":
            try:
                import psutil  # noqa: F401
            except ImportError as exc:
                raise RuntimeError(
                    "On macOS run: uv run --with psutil python "
                    "scripts/profile_local_traffic.py ..."
                ) from exc
        if not 1 <= args.workers <= 16 or args.speed < 1 or args.repeats < 2:
            raise ValueError("workers must be 1-16, speed >=1 and repeats >=2")
        delays = [int(x) for x in args.delays.split(",")]
        if not 1 <= len(delays) <= 5 or any(x < 0 or x > 1000 for x in delays):
            raise ValueError("Provide 1-5 delay values, 0-1000ms each")
        if args.route and args.har:
            raise ValueError("Use --har or --route, not both")
        if args.har:
            items, skipped = read_har(args.har)
        else:
            items = [safe_route(r) for r in (args.route or DEFAULT_ROUTES)]
            skipped = 0
        token = os.getenv(args.token_env, "")
        if not token and (not args.username or not os.getenv(args.password_env)):
            raise ValueError("Supply --username with local password env, or local token env")
        if not token:
            # app.config randomizes development JWT secrets on each start.
            # One ephemeral production-mode signing key must be shared by ALL
            # local subprocesses so setup credentials remain valid in replays.
            os.environ["SECRET_KEY"] = secrets.token_urlsafe(48)
        elif not os.environ.get("SECRET_KEY"):
            raise ValueError("With --token-env, provide its matching LOCAL SECRET_KEY in env")
        args.output.mkdir(mode=0o700, parents=True, exist_ok=True)
        os.chmod(args.output, 0o700)
        output = args.output / datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
        output.mkdir(mode=0o700)
        if not token:
            print("Authenticating against loopback local test account...")
            token = local_token(args.db_url, output, args.username, os.environ[args.password_env])
        result = {"scenario": "HAR" if args.har else "default GET routes",
                  "total_requests_per_burst": len(items), "skipped_har_entries": skipped,
                  "workers": args.workers, "speed": args.speed, "profiles": []}
        for delay in delays:
            print(f"Replaying {len(items)} GET requests with {delay}ms DB-chunk latency...")
            result["profiles"].append(profile(args.db_url, delay, output, items, token,
                                             args.workers, args.speed, args.repeats))
        for name, body in (("report.json", json.dumps(result, indent=2) + "\n"),
                           ("report.md", report_markdown(result))):
            path = output / name
            path.write_text(body, encoding="utf-8")
            os.chmod(path, 0o600)
        print("Reports: " + str(output / "report.md"))
        return 0
    except (ValueError, RuntimeError, TimeoutError, OSError, KeyError,
            json.JSONDecodeError) as exc:
        print("Profiling failed: " + str(exc), file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
