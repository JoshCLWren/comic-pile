"""No-network regression coverage for Neon-first GitHub factory reads."""
from __future__ import annotations

import importlib.util
import json
import os
import subprocess
import sys
import types
from pathlib import Path
from unittest.mock import Mock

import pytest

ROOT = Path(__file__).resolve().parents[1]
PATH = ROOT / ".github/scripts/factory_gh_read_through.py"
SPEC = importlib.util.spec_from_file_location("factory_gh_read_through", PATH)
assert SPEC and SPEC.loader
read_through = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = read_through
SPEC.loader.exec_module(read_through)

REPO = "JoshCLWren/comic-pile"


@pytest.mark.parametrize(
    ("args", "expected"),
    [
        (["--paginate", "--slurp", f"repos/{REPO}/pulls?state=all&per_page=100"], 120),
        ([f"repos/{REPO}/pulls?state=open&per_page=100"], 45),
        ([f"repos/{REPO}/issues?state=open&per_page=100"], 45),
        ([f"repos/{REPO}/issues/comments?since=2026-11-14T00:00:00Z"], 60),
        ([f"repos/{REPO}/issues/1093/comments?per_page=100"], 90),
        ([f"repos/{REPO}/pulls/5000"], None),
        ([f"repos/{REPO}/issues/5000/labels"], None),
        ([f"repos/{REPO}/pulls/5000/reviews"], None),
        ([f"repos/{REPO}/commits/abc/check-runs"], None),
        ([f"repos/{REPO}/actions/runs?status=in_progress"], None),
        (["--method", "POST", f"repos/{REPO}/issues/1/labels"], None),
        (["-f", "body=value", f"repos/{REPO}/issues/1/comments"], None),
        (["graphql", "-f", "query={viewer{login}}"], None),
        (["--include", f"repos/{REPO}/pulls?state=all"], None),
        (["-H", "Authorization: Bearer secret", f"repos/{REPO}/pulls?state=all"], None),
    ],
)
def test_cache_allowlist_only_covers_safe_discovery(args: list[str], expected: int | None) -> None:
    assert read_through.allowed_read(args, REPO) == expected


def test_no_cross_repository_cache_sharing() -> None:
    assert read_through.allowed_read(
        ["repos/another-owner/another-repo/pulls?state=all"], REPO
    ) is None


def test_fresh_target_projection_returns_without_github(monkeypatch, capsys) -> None:
    monkeypatch.setenv("GITHUB_REPOSITORY", REPO)
    monkeypatch.setenv("FACTORY_STATE_DSN_FILE", "/trusted/connection-file")
    monkeypatch.setitem(
        sys.modules,
        "factory_state_projection",
        types.SimpleNamespace(projected_json=lambda repo, kind: [{"number": 19}]),
    )
    assert read_through.projected(REPO, "pr") == 0
    assert json.loads(capsys.readouterr().out) == [{"number": 19}]


def test_stale_target_projection_requests_live_fallback(monkeypatch, capsys) -> None:
    monkeypatch.setenv("GITHUB_REPOSITORY", REPO)
    monkeypatch.setenv("FACTORY_STATE_DSN_FILE", "/trusted/connection-file")
    monkeypatch.setitem(
        sys.modules,
        "factory_state_projection",
        types.SimpleNamespace(projected_json=lambda repo, kind: None),
    )
    assert read_through.projected(REPO, "pr") == 2
    assert capsys.readouterr().out == ""


def test_safe_api_cache_hit_does_not_call_github(monkeypatch, capsys) -> None:
    monkeypatch.setenv("GITHUB_REPOSITORY", REPO)
    monkeypatch.setenv("FACTORY_STATE_DSN_FILE", "/trusted/connection-file")
    monkeypatch.setenv("FACTORY_REAL_GH", "/usr/bin/gh")
    cached = Mock(return_value=[{"stdout": "[{\"number\":42}]\n"}])
    monkeypatch.setitem(sys.modules, "factory_state_cache", types.SimpleNamespace(cached_json=cached))
    called = Mock(side_effect=AssertionError("GitHub must not be queried on a cache hit"))
    monkeypatch.setattr(subprocess, "run", called)
    args = [f"repos/{REPO}/pulls?state=all&per_page=100"]
    assert read_through.api(args) == 0
    assert json.loads(capsys.readouterr().out) == [{"number": 42}]
    assert cached.call_args.kwargs["ttl_seconds"] == 120
    called.assert_not_called()


def test_stale_api_cache_refreshes_once_from_github(monkeypatch, capsys) -> None:
    monkeypatch.setenv("GITHUB_REPOSITORY", REPO)
    monkeypatch.setenv("FACTORY_STATE_DSN_FILE", "/trusted/connection-file")
    monkeypatch.setenv("FACTORY_REAL_GH", "/usr/bin/gh")
    def refresh(key, fetch, *, ttl_seconds):
        return fetch([])
    monkeypatch.setitem(sys.modules, "factory_state_cache", types.SimpleNamespace(cached_json=refresh))
    run = Mock(return_value=types.SimpleNamespace(returncode=0, stdout="[]\n", stderr=""))
    monkeypatch.setattr(subprocess, "run", run)
    args = ["--paginate", "--slurp", f"repos/{REPO}/pulls?state=all"]
    assert read_through.api(args) == 0
    assert capsys.readouterr().out == "[]\n"
    assert run.call_args.args[0] == ["/usr/bin/gh", "api", *args]


def test_mutation_always_calls_github_live(monkeypatch) -> None:
    monkeypatch.setenv("GITHUB_REPOSITORY", REPO)
    monkeypatch.setenv("FACTORY_STATE_DSN_FILE", "/trusted/connection-file")
    monkeypatch.setenv("FACTORY_REAL_GH", "/usr/bin/gh")
    live = Mock(return_value=0)
    monkeypatch.setattr(subprocess, "call", live)
    args = ["--method", "PUT", f"repos/{REPO}/issues/42/labels", "-f", "labels[]=factory"]
    assert read_through.api(args) == 0
    live.assert_called_once_with(["/usr/bin/gh", "api", *args])


def test_github_403_is_not_cached_as_empty_success(monkeypatch, capsys) -> None:
    monkeypatch.setenv("GITHUB_REPOSITORY", REPO)
    monkeypatch.setenv("FACTORY_STATE_DSN_FILE", "/trusted/connection-file")
    monkeypatch.setenv("FACTORY_REAL_GH", "/usr/bin/gh")
    monkeypatch.setitem(
        sys.modules,
        "factory_state_cache",
        types.SimpleNamespace(cached_json=lambda key, fetch, *, ttl_seconds: fetch([])),
    )
    monkeypatch.setattr(
        subprocess, "run",
        Mock(return_value=types.SimpleNamespace(returncode=22, stdout="", stderr="HTTP 403\n")),
    )
    assert read_through.api([f"repos/{REPO}/pulls?state=all"]) == 22
    assert "HTTP 403" in capsys.readouterr().err
