"""Pure, offline guardrail tests for local HTTP CPU replay (#4277)."""

import json
import os
from pathlib import Path

import pytest

from scripts.profile_local_traffic import (
    cpu_seconds,
    proxy_url,
    read_har,
    safe_database_url,
    safe_route,
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
    with pytest.raises(ValueError):
        safe_database_url(url)


def test_accept_loopback_and_keep_database_identity_through_proxy() -> None:
    original = safe_database_url(
        "postgresql+asyncpg://user:local_pw@localhost:5435/comicpile_profile"
    )
    assert proxy_url(original, 5555) == (
        "postgresql+asyncpg://user:local_pw@127.0.0.1:5555/comicpile_profile"
    )


def test_har_strips_host_and_refuses_secret_bearing_query_parameters(tmp_path: Path) -> None:
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
    with pytest.raises(ValueError):
        safe_route(url)


@pytest.mark.skipif(not os.path.exists("/proc/self/stat"), reason="Linux only")
def test_linux_cpu_counter_is_available() -> None:
    assert cpu_seconds(os.getpid()) >= 0
