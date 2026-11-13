"""Regression tests for the shared Neon discovery cache (no network)."""
from __future__ import annotations

import importlib.util
from pathlib import Path

import pytest

MODULE_PATH = Path(__file__).resolve().parents[1] / ".github/scripts/factory_state_cache.py"
SPEC = importlib.util.spec_from_file_location("factory_state_cache_test", MODULE_PATH)
assert SPEC is not None and SPEC.loader is not None
cache = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(cache)


def test_cache_is_transparent_without_trusted_neon_connection(monkeypatch):
    monkeypatch.delenv("FACTORY_STATE_DSN_FILE", raising=False)
    calls = []
    assert cache.cached_json("open-prs", lambda prior: calls.append(prior) or [{"number": 1}]) == [{"number": 1}]
    assert calls == [[]]


def test_neon_dsn_preserves_tls_and_removes_unsupported_channel_binding(monkeypatch, tmp_path):
    dsn = tmp_path / "dsn"
    dsn.write_text("postgresql://factory_state_rw:example@ep.example.neon.tech/factory_state?sslmode=require&channel_binding=require")
    monkeypatch.setenv("FACTORY_STATE_DSN_FILE", str(dsn))
    parsed = cache._dsn()
    assert "sslmode=require" in parsed
    assert "channel_binding" not in parsed
    assert "/factory_state?" in parsed


def test_cache_hit_does_not_call_github_or_refresh(monkeypatch, tmp_path):
    monkeypatch.setenv("FACTORY_STATE_DSN_FILE", str(tmp_path / "connection"))
    monkeypatch.setattr(cache, "_read", lambda _: ([{"number": 43}], True))
    monkeypatch.setattr(cache, "_claim", lambda *_: pytest.fail("fresh snapshots must not acquire refresh locks"))
    assert cache.cached_json("open-prs", lambda _: pytest.fail("fresh snapshots must not read GitHub")) == [{"number": 43}]


def test_cold_cache_fetches_once_and_publishes(monkeypatch, tmp_path):
    monkeypatch.setenv("FACTORY_STATE_DSN_FILE", str(tmp_path / "connection"))
    monkeypatch.setattr(cache, "_read", lambda _: (None, False))
    monkeypatch.setattr(cache, "_claim", lambda *_: True)
    published = []
    monkeypatch.setattr(cache, "_publish", lambda *args: published.append(args))
    result = cache.cached_json("issues", lambda last: [{"number": len(last) + 1}], ttl_seconds=45)
    assert result == [{"number": 1}]
    assert len(published) == 1
    assert published[0][0] == "issues"
    assert published[0][2] == result
    assert published[0][3] == 45


def test_contended_refresh_observes_winners_snapshot_without_calling_github(monkeypatch, tmp_path):
    monkeypatch.setenv("FACTORY_STATE_DSN_FILE", str(tmp_path / "connection"))
    hits = iter([([{"number": 3}], False), ([{"number": 4}], True)])
    monkeypatch.setattr(cache, "_read", lambda _: next(hits))
    monkeypatch.setattr(cache, "_claim", lambda *_: False)
    monkeypatch.setattr(cache.time, "sleep", lambda _: None)
    assert cache.cached_json("issues", lambda _: pytest.fail("fresh winner must prevent duplicate calls")) == [{"number": 4}]


def test_database_unavailable_uses_original_github_loader(monkeypatch, tmp_path):
    monkeypatch.setenv("FACTORY_STATE_DSN_FILE", str(tmp_path / "connection"))
    def unavailable(_):
        raise OSError("database offline")
    monkeypatch.setattr(cache, "_read", unavailable)
    assert cache.cached_json("issues", lambda _: [{"number": 1}]) == [{"number": 1}]


def test_github_failure_releases_refresh_claim_and_propagates(monkeypatch, tmp_path):
    monkeypatch.setenv("FACTORY_STATE_DSN_FILE", str(tmp_path / "connection"))
    monkeypatch.setattr(cache, "_read", lambda _: (None, False))
    monkeypatch.setattr(cache, "_claim", lambda *_: True)
    releases = []
    monkeypatch.setattr(cache, "_release", lambda *args: releases.append(args))
    with pytest.raises(RuntimeError, match="GitHub API unavailable"):
        cache.cached_json("issues", lambda _: (_ for _ in ()).throw(RuntimeError("GitHub API unavailable")))
    assert len(releases) == 1


def test_incremental_comments_fetches_since_latest_updated_timestamp():
    existing = [
        {"id": 1, "created_at": "2026-11-12T09:00:00Z", "updated_at": "2026-11-12T09:00:00Z", "body": "old"},
        {"id": 2, "created_at": "2026-11-12T10:00:00Z", "updated_at": "2026-11-12T10:00:00Z", "body": "before"},
    ]
    calls = []
    def since(value):
        calls.append(value)
        return [
            {"id": 2, "created_at": "2026-11-12T10:00:00Z", "updated_at": "2026-11-12T11:00:00Z", "body": "edited"},
            {"id": 3, "created_at": "2026-11-12T11:00:00Z", "updated_at": "2026-11-12T11:00:00Z", "body": "new"},
        ]
    result = cache.incremental_comments(existing, since)
    assert calls == ["2026-11-12T09:59:00Z"]
    assert [item["id"] for item in result] == [1, 2, 3]
    assert result[1]["body"] == "edited"


def test_first_registry_fill_uses_full_history_and_rejects_bad_events():
    calls = []
    assert cache.incremental_comments([], lambda since: calls.append(since) or [{"id": 1}]) == [{"id": 1}]
    assert calls == [None]
    with pytest.raises(ValueError, match="malformed issue comment"):
        cache.incremental_comments([], lambda _: [{"body": "no id"}])


def test_invalid_cache_ttl_fails_fast():
    with pytest.raises(ValueError, match="TTL"):
        cache.cached_json("issues", lambda _: [], ttl_seconds=0)


def test_workflows_inject_database_only_into_trusted_jobs():
    root = Path(__file__).resolve().parents[1]
    action = (root / ".github/actions/factory-state-cache/action.yml").read_text()
    assert "database_name=factory_state&role_name=factory_state_rw" in action
    assert '::add-mask::$uri' in action
    assert 'FACTORY_STATE_DSN_FILE=$dsn_file' in action
    for filename in (
        "fixed-model-factory-dispatch.yml",
        "factory-completion-drain.yml",
        "factory-status-pages.yml",
        "fixed-model-factory-capacity-refill.yml",
        "fixed-model-factory-dispatch-recovery.yml",
    ):
        workflow = (root / ".github/workflows" / filename).read_text()
        assert "uses: ./.github/actions/factory-state-cache" in workflow
        assert "secrets.NEON_API_KEY" in workflow
    for filename in ("free-model-factory-run.yml", "free-model-factory-entry.yml", "local-ollama-review.yml"):
        workflow = (root / ".github/workflows" / filename).read_text()
        assert "factory-state-cache" not in workflow
        assert "FACTORY_STATE_DSN_FILE" not in workflow


def test_recovery_watchdog_loads_paginated_compatible_neon_registry() -> None:
    workflow = (Path(__file__).resolve().parents[1] / ".github/workflows/fixed-model-factory-dispatch-recovery.yml").read_text()
    assert "from factory_completion_controller import registry_comments" in workflow
    assert "json.dumps([registry_comments()])" in workflow
    assert "issues/1093/comments?per_page=100" not in workflow
    assert "factory_heartbeat_health.py" in workflow
    assert "uses: ./.github/actions/factory-state-cache" in workflow
