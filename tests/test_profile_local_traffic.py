"""Pure, offline guardrail tests for local HTTP CPU replay (#4277)."""

import json
import os
from pathlib import Path
import socket
import threading
import time

import pytest

from scripts.profile_local_traffic import (
    DelayProxy,
    proxy_url,
    read_har,
    safe_database_url,
    safe_route,
    server_environment,
    response_header,
)


@pytest.mark.parametrize(
    "url",
    [
        "",
        "postgresql+asyncpg://user:pw@some-neon-host.neon.tech/db",
        "postgresql://user:pw@10.0.0.5:5432/copy",
        "postgresql://user:pw@127.0.0.1/db",
        "postgresql://user:pw@127.0.0.1:5432/",
        "postgresql://user:pw@127.0.0.1:5432/db?host=neon.example",
        "postgresql://user:pw@127.0.0.1:5432/db?service=prod",
        "sqlite:///test.db",
    ],
)
def test_refuse_non_local_database_targets(url: str) -> None:
    """Reject non-local PostgreSQL targets before starting a profiler."""
    with pytest.raises(ValueError):
        safe_database_url(url)


def test_accept_loopback_and_keep_database_identity_through_proxy() -> None:
    """Keep a local database's identity when routing through the delay proxy."""
    original = safe_database_url(
        "postgresql+asyncpg://user:local_pw@localhost:5435/comicpile_profile"
    )
    assert proxy_url(original, 5555) == (
        "postgresql+asyncpg://user:local_pw@127.0.0.1:5555/comicpile_profile"
    )


def test_har_strips_host_and_refuses_secret_bearing_query_parameters(tmp_path: Path) -> None:
    """Remove untrusted origins and deny query strings that could leak secrets."""
    har = {
        "log": {
            "entries": [
                {
                    "startedDateTime": "2026-10-28T12:00:01Z",
                    "request": {
                        "method": "GET",
                        "url": "https://comic-pile.vercel.app/api/v1/roll/bootstrap",
                        "headers": [{"name": "Authorization", "value": "secret-access"}],
                    },
                },
                {
                    "startedDateTime": "2026-10-28T12:00:02Z",
                    "request": {
                        "method": "POST",
                        "url": "https://comic-pile.vercel.app/api/v1/rate/",
                    },
                },
                {
                    "startedDateTime": "2026-10-28T12:00:03Z",
                    "request": {
                        "method": "GET",
                        "url": "https://comic-pile.vercel.app/api/v1/auth/me?token=secret",
                    },
                },
                {
                    "startedDateTime": "2026-10-28T12:00:04Z",
                    "request": {
                        "method": "GET",
                        "url": "https://comic-pile.vercel.app/api/v1/threads/?page_size=20",
                    },
                },
                {
                    "startedDateTime": "2026-10-28T12:00:05Z",
                    "request": {
                        "method": "GET",
                        "url": "https://third-party.example/not-an-api",
                    },
                },
            ]
        }
    }
    filename = tmp_path / "captured.har"
    filename.write_text(json.dumps(har), encoding="utf-8")
    requests, skipped = read_har(filename)
    assert skipped == 3
    assert [(req.url, req.route, req.offset) for req in requests] == [
        ("/api/v1/roll/bootstrap", "/api/v1/roll/bootstrap", 0.0),
        ("/api/v1/threads/?page_size=20", "/api/v1/threads/", 3.0),
    ]
    assert "secret-access" not in str(requests)
    assert "comic-pile.vercel.app" not in str(requests)


@pytest.mark.parametrize(
    "url",
    [
        "/api/v1/auth/refresh?refresh_token=secret",
        "/api/v1/auth/me?client_secret=something",
        "/api/v1/sessions/?sessionId=1",
        "file:///api/v1/roll/bootstrap",
        "https://example.com/not-api",
    ],
)
def test_reject_sensitive_or_unrelated_routes(url: str) -> None:
    """Exclude unauthorized and unrelated API routes from traffic replay."""
    with pytest.raises(ValueError):
        safe_route(url)


def test_linux_cpu_counter_parses_proc_stat_on_any_platform(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Mock the /proc read so the Linux counter is verified on both platforms."""
    from scripts import profile_local_traffic as module

    class FakeStatPath:
        def __init__(self, raw: str) -> None:
            assert raw == "/proc/777/stat"

        def read_text(self, encoding: str) -> str:
            assert encoding == "ascii"
            return "777 (uvicorn) R 1 2 3 4 5 6 7 8 9 10 120 40 0 0 0"

    monkeypatch.setattr(module, "Path", FakeStatPath)
    monkeypatch.setattr(module.sys, "platform", "linux")
    # utime=120 and stime=40 ticks after the comm field.
    assert module.cpu_seconds(777) == 160 / os.sysconf("SC_CLK_TCK")


def test_cpu_seconds_uses_psutil_on_macos(monkeypatch: pytest.MonkeyPatch) -> None:
    """Mac CPU time is user+system, never wall-clock elapsed time."""
    import sys
    from types import SimpleNamespace

    from scripts import profile_local_traffic as module

    monkeypatch.setattr(module.sys, "platform", "darwin")
    class FakeProcess:
        def __init__(self, pid: int) -> None:
            assert pid == 777
        def cpu_times(self) -> SimpleNamespace:
            return SimpleNamespace(user=1.25, system=0.75)

    monkeypatch.setitem(sys.modules, "psutil", SimpleNamespace(Process=FakeProcess))
    assert module.cpu_seconds(777) == 2.0


def test_production_profile_sets_non_wildcard_loopback_cors(monkeypatch: pytest.MonkeyPatch) -> None:
    """Production startup requires CORS_ORIGINS even without a browser client."""
    monkeypatch.setenv("SECRET_KEY", "ephemeral-local-signing-key")
    monkeypatch.setenv("DATABASE_URL", "postgresql://untrusted.example/prod")
    monkeypatch.setenv("CORS_ORIGINS", "*")
    env = server_environment(
        "postgresql+asyncpg://comicpile:local_password@127.0.0.1:55435/comicpile_profile",
        8999,
    )
    assert env["ENVIRONMENT"] == "production"
    assert env["CORS_ORIGINS"] == "http://127.0.0.1:8999"
    assert env["DATABASE_URL"].endswith(":55435/comicpile_profile")
    assert env["TEST_DATABASE_URL"] == env["DATABASE_URL"]
    assert env["TEST_ENVIRONMENT"] == "false"
    assert env["NEON_TOKEN"] == ""
    assert env["NEON_PROJECT_ID"] == ""
    assert env["SECRET_KEY"] == "ephemeral-local-signing-key"


def test_seeder_converts_plain_postgres_schemes_to_the_async_driver() -> None:
    """URLs accepted by safe_database_url must create an asyncpg engine."""
    from scripts.seed_profile_fixture import async_database_url

    assert async_database_url(
        "postgresql://local_user:local_pw@127.0.0.1:55435/comicpile_profile"
    ) == "postgresql+asyncpg://local_user:local_pw@127.0.0.1:55435/comicpile_profile"
    assert async_database_url(
        "postgres://local_user:local_pw@localhost:5437/profile_fixture"
    ) == "postgresql+asyncpg://local_user:local_pw@localhost:5437/profile_fixture"
    assert async_database_url(
        "postgresql+asyncpg://local_user:local_pw@localhost:5435/comicpile_profile"
    ) == "postgresql+asyncpg://local_user:local_pw@localhost:5435/comicpile_profile"


def test_seeder_refuses_non_local_targets_for_the_async_driver() -> None:
    """Scheme conversion keeps the local-only database guard active."""
    from scripts.seed_profile_fixture import async_database_url

    with pytest.raises(ValueError):
        async_database_url("postgres://local_user:pw@neon.example:5432/profile")


class _EchoServer:
    """Loopback server that echoes every message over one held connection."""

    def __init__(self) -> None:
        self.sock = socket.socket()
        self.sock.bind(("127.0.0.1", 0))
        self.sock.listen(8)
        self.sock.settimeout(0.25)
        self.stopped = threading.Event()
        self.thread = threading.Thread(target=self._serve, daemon=True)
        self.thread.start()

    @property
    def port(self) -> int:
        return self.sock.getsockname()[1]

    def _serve(self) -> None:
        while not self.stopped.is_set():
            try:
                conn, _ = self.sock.accept()
            except TimeoutError:
                continue
            except OSError:
                break
            threading.Thread(target=self._echo, args=(conn,), daemon=True).start()

    def _echo(self, conn: socket.socket) -> None:
        try:
            conn.settimeout(0.5)
            while not self.stopped.is_set():
                try:
                    data = conn.recv(65536)
                except TimeoutError:
                    continue
                if not data:
                    break
                conn.sendall(data)
        except OSError:
            pass
        finally:
            conn.close()

    def close(self) -> None:
        self.stopped.set()
        self.sock.close()
        self.thread.join(timeout=2)


def test_delay_proxy_keeps_idle_connections_connected() -> None:
    """Accept/connect timeouts must not sever pooled idle database links."""
    echo = _EchoServer()
    proxy = DelayProxy("127.0.0.1", echo.port, 0)
    try:
        with socket.create_connection(("127.0.0.1", proxy.port), timeout=5) as client:
            client.settimeout(5)
            client.sendall(b"first")
            assert client.recv(5) == b"first"
            # Idle longer than the 0.25s listener and 10s connect timeouts;
            # those used to leak into reads and disconnect pooled sessions.
            time.sleep(1.0)
            client.sendall(b"second")
            assert client.recv(6) == b"second"
            client.shutdown(socket.SHUT_WR)
    finally:
        proxy.close()
        echo.close()


def test_response_header_case_normalization() -> None:
    """Header lookup must not depend on the server's response header casing."""
    for key in ('x-app-db-queries', 'X-App-Db-Queries', 'X-APP-DB-QUERIES'):
        assert response_header({key: '27'}, 'X-App-DB-Queries') == '27'
    assert response_header({}, 'X-App-DB-Queries') is None


def _profile_entry(warm_statuses: list[int], fresh_statuses: list[int]) -> dict:
    """Build one delay profile with distinct warm and fresh burst results."""
    def row(status: int) -> dict:
        return {"route": "/api/v1/auth/me", "status": status}

    return {
        "delay_ms_per_tcp_chunk": 0,
        "startup": {"cpu_seconds": 0.5, "wall_ms": 400.0},
        "cold_auth": {"status": 200, "cpu_seconds": 0.2},
        "sequential": [{"route": "/api/v1/threads/", "cpu_seconds": 0.01,
                        "wall_ms": 12.0, "db_queries": 3, "status": 200}],
        "warm_burst": {"cpu_seconds": 0.1, "wall_seconds": 1.5,
                       "responses": [row(status) for status in warm_statuses]},
        "fresh_burst": {"startup": {"cpu_seconds": 0.4, "wall_ms": 300.0},
                        "cpu_seconds": 0.3, "wall_seconds": 2.0,
                        "responses": [row(status) for status in fresh_statuses]},
    }


def test_report_markdown_keeps_fresh_burst_failures_visible() -> None:
    """Failed cold concurrent requests must not read as successful low CPU."""
    from scripts.profile_local_traffic import report_markdown

    data = {"profiles": [_profile_entry([200, 200], [0, 500, 404])]}
    report = report_markdown(data)
    assert "Failed warm GETs | Failed fresh GETs" in report
    # Warm burst succeeded; the fresh burst failed all three requests.
    assert "| 0ms | 0.500s | 0.200s | 0.100s | 0.300s | 1.50s | 0 | 3 |" in report
