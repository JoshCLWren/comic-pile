"""Regression tests for webhook-fed Neon issue/PR projections (no network)."""
from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / ".github/scripts"))
SPEC = importlib.util.spec_from_file_location(
    "factory_state_projection_test", ROOT / ".github/scripts/factory_state_projection.py"
)
assert SPEC is not None and SPEC.loader is not None
projection = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(projection)


def test_issue_event_normalization_preserves_queue_fields() -> None:
    event = {"action": "labeled", "issue": {
        "number": 501, "title": "Fix it", "body": "Something broke",
        "state": "open", "created_at": "2026-11-12T00:00:00Z",
        "updated_at": "2026-11-13T00:00:00Z",
        "labels": [{"name": "factory:unowned"}, {"name": "bug"}],
    }}
    kind, number, item, state = projection.normalize_event(event)
    assert (kind, number, state) == ("issue", 501, "open")
    assert item["number"] == 501
    assert item["labels"] == [{"name": "factory:unowned"}, {"name": "bug"}]
    assert item["updatedAt"] == "2026-11-13T00:00:00Z"


def test_pr_webhook_normalization_preserves_current_head_and_stage() -> None:
    event = {"action": "synchronize", "pull_request": {
        "number": 900, "state": "open", "title": "Fix", "body": "Closes #501",
        "draft": False,
        "created_at": "2026-11-12T00:00:00Z",
        "updated_at": "2026-11-13T00:00:00Z",
        "mergeable": None, "mergeable_state": "unknown",
        "head": {"ref": "fix/issue", "sha": "a"*40,
                 "repo": {"full_name": "JoshCLWren/comic-pile"}},
        "base": {"repo": {"full_name": "JoshCLWren/comic-pile"}},
        "labels": [{"name": "factory:review"}],
    }}
    kind, number, item, state = projection.normalize_event(event)
    assert (kind, number, state) == ("pr", 900, "open")
    assert item["headRefOid"] == "a"*40
    assert item["headRefName"] == "fix/issue"
    assert item["mergeStateStatus"] == "UNKNOWN"
    assert not item["isCrossRepository"]


def test_closed_event_marks_projection_non_executable() -> None:
    kind, number, item, state = projection.normalize_event({
        "action": "closed", "issue": {
            "number": 44, "state": "closed", "labels": [], "title": "Done",
        }
    })
    assert (kind, number, state) == ("issue", 44, "closed")


def test_does_not_accept_malformed_issues_or_prs() -> None:
    assert projection.normalize_event({}) is None
    assert projection.normalize_event({"issue": {"number": "44"}}) is None


def test_projection_read_defers_to_github_without_trusted_connection(monkeypatch) -> None:
    monkeypatch.delenv("FACTORY_STATE_DSN_FILE", raising=False)
    assert projection.projected_json("JoshCLWren/comic-pile", "issue") is None


def test_live_event_ingestion_requires_neon(monkeypatch) -> None:
    monkeypatch.delenv("FACTORY_STATE_DSN_FILE", raising=False)
    with pytest.raises(RuntimeError, match="requires trusted Neon"):
        projection.ingest_event("JoshCLWren/comic-pile", "123", {"issue": {"number": 1}})


def test_invalid_projection_kind_fails_closed() -> None:
    with pytest.raises(ValueError):
        projection._prefix("owner/repo", "worker")


def test_trusted_webhook_does_not_checkout_pr_branch_or_expose_write_token() -> None:
    workflow = (ROOT / ".github/workflows/factory-target-projections.yml").read_text()
    assert "pull_request_target:" in workflow
    assert "issues:" in workflow
    assert "ref: main" in workflow
    assert "persist-credentials: false" in workflow
    assert "permissions:\n  contents: read" in workflow
    assert "  issues: read\n" in workflow
    assert "  pull-requests: read\n" in workflow
    assert ": write" not in workflow
    assert "github.event.repository.full_name == github.repository" in workflow
    assert "factory_state_projection.py ingest" in workflow
    assert "secrets.NEON_API_KEY" in workflow
    assert "GH_TOKEN: ${{ github.token }}" in workflow
    assert "if: env.FACTORY_STATE_DSN_FILE != ''" in workflow
    assert "github.event.pull_request.head" not in workflow


def test_controller_uses_projection_with_30_minute_reconciliation() -> None:
    source = (ROOT / ".github/scripts/factory-work-controller.py").read_text()
    assert 'projected_json(REPO, "issue")' in source
    assert 'projected_json(REPO, "pr")' in source
    assert 'reconcile_snapshot(REPO, "issue", issues, started)' in source
    assert 'return cached_json(f"{REPO}:open-issues", fetch_issues, ttl_seconds=45)' in source
    assert 'reconcile_snapshot(REPO, "pr", prs, started)' in source
    assert projection.RECONCILE_SECONDS == 1800

def test_delayed_open_event_uses_live_closed_state(monkeypatch: pytest.MonkeyPatch) -> None:
    import json
    import subprocess

    def live(args: list[str], **kwargs: object) -> subprocess.CompletedProcess[str]:
        return subprocess.CompletedProcess(args, 0, json.dumps({
            "number": 44, "state": "closed", "updated_at": "2026-11-13T04:25:00Z",
            "labels": [], "title": "Closed",
        }), "")

    monkeypatch.setattr(projection.subprocess, "run", live)
    original = {"issue": {"number": 44, "state": "open", "updated_at": "2026-11-13T04:00:00Z"}}
    record = projection.normalize_event(projection._authoritative_event("owner/repo", original))
    assert record is not None and record[3] == "closed"


def test_equal_timestamp_event_uses_live_reopen(monkeypatch: pytest.MonkeyPatch) -> None:
    import json
    import subprocess

    def live(args: list[str], **kwargs: object) -> subprocess.CompletedProcess[str]:
        return subprocess.CompletedProcess(args, 0, json.dumps({
            "number": 44, "state": "open", "updated_at": "2026-11-13T04:25:00Z",
            "labels": [], "title": "Reopened",
        }), "")

    monkeypatch.setattr(projection.subprocess, "run", live)
    original = {"issue": {"number": 44, "state": "closed", "updated_at": "2026-11-13T04:25:00Z"}}
    record = projection.normalize_event(projection._authoritative_event("owner/repo", original))
    assert record is not None and record[3] == "open"


def test_missing_target_rejects_obsolete_open_event() -> None:
    import inspect
    statement = inspect.getsource(projection._ingest_event)
    assert "WHERE NOT EXISTS" in statement
    assert "_marker(repo, kind)" in statement


def test_live_event_is_read_only_after_acquiring_projection_lock() -> None:
    import inspect

    source = inspect.getsource(projection._ingest_event)
    assert source.index("pg_advisory_xact_lock") < source.index(
        "normalize_event(_authoritative_event(repo, event))"
    )


def test_snapshot_marker_uses_beginning_of_github_listing() -> None:
    import inspect

    source = inspect.getsource(projection._snapshot)
    assert "jsonb_build_object('started_at',$2::text)" in source
    assert "_marker(repo,kind), started" in source
    assert "payload=EXCLUDED.payload" in source


def test_bootstrap_is_one_time_and_safe_under_concurrent_webhooks() -> None:
    import inspect

    source = inspect.getsource(projection._bootstrap_kind)
    assert 'prefix + "bootstrap"' in source
    assert "SELECT 1 FROM public.factory_state_kv WHERE cache_key=$1" in source
    assert "len(items) >= limit" in source
    assert "await _snapshot(repo, kind, items, started)" in source
    assert "bootstrap_missing(args.repo)" in inspect.getsource(projection.main)


def test_snapshot_uses_native_datetimes_for_asyncpg_timestamptz(monkeypatch: pytest.MonkeyPatch) -> None:
    """Both reconciliation queries bind Python datetimes to asyncpg timestamptz."""
    import asyncio
    from datetime import datetime
    from types import SimpleNamespace

    calls: list[tuple[str, tuple[object, ...]]] = []

    class FakeTransaction:
        async def __aenter__(self) -> None:
            return None

        async def __aexit__(self, *_args: object) -> None:
            return None

    class FakeConnection:
        def transaction(self) -> FakeTransaction:
            return FakeTransaction()

        async def execute(self, *_args: object) -> str:
            return "OK"

        async def fetch(self, query: str, *args: object) -> list[object]:
            calls.append((query, args))
            return []

        async def close(self) -> None:
            return None

    async def connect(**_kwargs: object) -> FakeConnection:
        return FakeConnection()

    monkeypatch.setitem(sys.modules, "asyncpg", SimpleNamespace(connect=connect))
    monkeypatch.setattr(projection, "_dsn", lambda: "test-postgres-dsn")
    result = asyncio.run(projection._snapshot("owner/repo", "issue", [], "2026-11-13T13:07:00Z"))
    assert result == (0, 0)
    assert len(calls) == 2
    assert isinstance(calls[0][1][1], datetime)
    assert isinstance(calls[1][1][2], datetime)
    assert calls[1][1][4] == "2026-11-13T13:07:00Z"
    assert "to_jsonb($5::text)" in calls[1][0]
