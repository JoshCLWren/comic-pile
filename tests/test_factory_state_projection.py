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
    assert item["labels"] == [{"name": "bug"}, {"name": "factory:unowned"}]
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


@pytest.mark.parametrize("rate_limited", [True, False])
def test_failed_live_read_reports_quota_without_exposing_output(
    monkeypatch: pytest.MonkeyPatch, rate_limited: bool,
) -> None:
    import subprocess

    error = "API rate limit exceeded for installation" if rate_limited else "HTTP 403"

    def failed(args: list[str], **kwargs: object) -> subprocess.CompletedProcess[str]:
        return subprocess.CompletedProcess(args, 1, "private response", error + " private detail")

    monkeypatch.setattr(projection.subprocess, "run", failed)
    with pytest.raises(RuntimeError) as caught:
        projection._authoritative_event("owner/repo", {"pull_request": {"number": 44}})
    assert "private" not in str(caught.value)
    expected = (
        "GitHub API rate limit exceeded while verifying pull_request #44"
        if rate_limited else "GitHub could not verify pull_request #44"
    )
    assert str(caught.value) == expected


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


def test_ingest_cli_defers_unverified_github_target_without_writing(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, capsys: pytest.CaptureFixture[str],
) -> None:
    """A failed live read keeps Neon untouched and leaves a visible warning."""
    event = tmp_path / "event.json"
    event.write_text('{"pull_request":{"number":4976}}', encoding="utf-8")
    called: list[str] = []

    def unavailable(*_args: object) -> bool:
        raise projection.GitHubTargetVerificationError("GitHub could not verify pull_request #4976")

    monkeypatch.setattr(projection, "ingest_event", unavailable)
    monkeypatch.setattr(projection, "bootstrap_missing", lambda *_args: called.append("bootstrap"))
    monkeypatch.setattr(sys, "argv", [
        "factory_state_projection.py", "ingest", "--file", str(event),
        "--event-id", "run-1", "--repo", "JoshCLWren/comic-pile",
    ])
    assert projection.main() == 0
    assert called == []
    assert "ingest deferred" in capsys.readouterr().err


def test_ingest_cli_does_not_hide_neon_write_failures(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
) -> None:
    """Database errors remain fatal; only GitHub verification may defer."""
    event = tmp_path / "event.json"
    event.write_text('{"pull_request":{"number":4976}}', encoding="utf-8")

    def broken_db(*_args: object) -> bool:
        raise RuntimeError("Neon transaction failed")

    monkeypatch.setattr(projection, "ingest_event", broken_db)
    monkeypatch.setattr(sys, "argv", [
        "factory_state_projection.py", "ingest", "--file", str(event),
        "--event-id", "run-1", "--repo", "JoshCLWren/comic-pile",
    ])
    with pytest.raises(RuntimeError, match="Neon transaction failed"):
        projection.main()

def test_rest_webhook_and_graphql_inventory_have_identical_stable_issue_fields() -> None:
    rest = {"number": 44, "title": "Same", "body": "Body", "state": "open",
            "created_at": "2026-11-13T00:00:00Z", "updated_at": "2026-11-14T00:00:00Z",
            "labels": [{"name": "factory", "id": 5, "url": "https://api.github.com/a"},
                       {"name": "bug", "color": "red"}]}
    graphql = {"number": 44, "title": "Same", "body": "Body",
               "createdAt": rest["created_at"], "updatedAt": rest["updated_at"],
               "labels": [{"name": "bug", "id": "LA_999", "description": "Unimportant"},
                          {"name": "factory", "id": "LA_111"}]}
    webhook = projection.normalize_event({"issue": rest})
    assert webhook is not None
    expected = projection.canonical_item("issue", graphql)
    assert webhook[2] == expected
    assert projection.canonical_item("issue", graphql) == expected
    # Two consecutive unchanged authoritative listings produce identical JSONB items.
    assert projection.canonical_item("issue", dict(graphql)) == expected
    assert projection.canonical_item("issue", {**graphql, "title": "Changed"}) != expected
    assert projection.canonical_item("issue", {**graphql, "labels": []}) != expected


def test_rest_pr_and_inventory_share_head_and_mergeability() -> None:
    same = {"number": 66, "title": "PR", "body": "", "state": "open",
            "created_at": "2026-11-13T00:00:00Z", "updated_at": "2026-11-14T00:00:00Z",
            "draft": False, "mergeable": True, "mergeable_state": "clean",
            "head": {"ref": "fix", "sha": "a"*40,
                     "repo": {"full_name": "owner/repo"}},
            "base": {"repo": {"full_name": "owner/repo"}},
            "labels": [{"name": "factory", "color": "purple"}]}
    graph = {"number": 66, "title": "PR", "body": "",
             "createdAt": same["created_at"], "updatedAt": same["updated_at"],
             "headRefName": "fix", "headRefOid": "a"*40, "isDraft": False,
             "mergeable": "MERGEABLE", "mergeStateStatus": "CLEAN",
             "isCrossRepository": False,
             "labels": [{"name": "factory", "id": "LA_123"}]}
    webhook = projection.normalize_event({"pull_request": same})
    assert webhook is not None and webhook[2] == projection.canonical_item("pr", graph)
    assert projection.canonical_item("pr", {**graph, "headRefOid": "b"*40}) != webhook[2]

def test_canonical_projection_preserves_controller_state_and_author() -> None:
    issue = projection.canonical_item("issue", {"number": 1, "state": "open"})
    assert issue["state"] == "OPEN"
    closed = projection.canonical_item("issue", {"number": 1, "state": "closed"})
    assert closed["state"] == "CLOSED"
    rest_pr = projection.canonical_item("pr", {
        "number": 2, "state": "open", "user": {"login": "trusted-author"},
    })
    cli_pr = projection.canonical_item("pr", {
        "number": 2, "state": "OPEN", "author": {"login": "trusted-author"},
    })
    assert rest_pr == cli_pr
    assert rest_pr["author"] == {"login": "trusted-author"}



def test_rest_snapshot_timestamp_is_not_dropped_by_source_watermark(monkeypatch):
    """A REST updated_at must survive the same DB CAS guard as GraphQL updatedAt."""
    import asyncio
    import json
    from types import SimpleNamespace

    observed = []

    class Tx:
        async def __aenter__(self):
            return None

        async def __aexit__(self, *args):
            return None

    class Conn:
        def transaction(self):
            return Tx()

        async def execute(self, *args):
            return "OK"

        async def fetch(self, query, *args):
            observed.append((query, args))
            return []

        async def close(self):
            pass

    async def connect(**kwargs):
        return Conn()

    monkeypatch.setitem(sys.modules, "asyncpg", SimpleNamespace(connect=connect))
    monkeypatch.setattr(projection, "_dsn", lambda: "test-postgres-dsn")
    entry = {"number": 4737, "state": "open", "title": "Live item", "labels": [],
             "created_at": "2026-11-13T07:10:00Z",
             "updated_at": "2026-11-14T14:38:05Z"}
    assert asyncio.run(projection._snapshot(
        "owner/repo", "issue", [entry], "2026-11-14T15:00:00Z"
    )) == (0, 0)
    payload = json.loads(observed[0][1][0])[0]
    assert payload["source_updated_at"] == entry["updated_at"]
    assert payload["item"]["updatedAt"] == entry["updated_at"]


def test_finite_projection_ttls_and_expired_row_fallback() -> None:
    """Open target rows and snapshot markers must have bounded freshness."""
    import inspect
    snap = inspect.getsource(projection._snapshot)
    ingest = inspect.getsource(projection._ingest_event)
    read = inspect.getsource(projection._read_projection)
    assert projection.RECONCILE_SECONDS == 1800
    assert projection.TARGET_TTL_SECONDS == 7200
    assert "2100-01-01" not in snap
    assert "2100-01-01" not in ingest
    assert "expires_at=EXCLUDED.expires_at" in snap
    assert "expires_at=EXCLUDED.expires_at" in ingest
    assert "if any(row[\"live\"] is not True for row in rows)" in read
    assert "source timestamps" in snap


def test_trusted_label_refresh_uses_exact_target(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The controller's trusted write is not an unverified webhook replay."""
    calls: list[tuple[str, str, dict[str, object], str]] = []

    async def fake_ingest(
        repo: str, event_id: str, event: dict[str, object], *,
        source: str = "github-webhook",
    ) -> bool:
        calls.append((repo, event_id, event, source))
        return True

    monkeypatch.setenv("FACTORY_STATE_DSN_FILE", "/trusted/dsn")
    monkeypatch.setenv("GITHUB_RUN_ID", "43617062837")
    monkeypatch.setattr(projection, "_ingest_event", fake_ingest)

    assert projection.refresh_trusted_label_write(
        "JoshCLWren/comic-pile", 5060, is_pr=True
    )
    assert projection.refresh_trusted_label_write(
        "JoshCLWren/comic-pile", 4843, is_pr=False
    )
    assert calls[0][2] == {"action": "labels", "pull_request": {"number": 5060}}
    assert calls[1][2] == {"action": "labels", "issue": {"number": 4843}}
    assert all(call[3] == "github-trusted-write" for call in calls)
    assert all("43617062837" in call[1] for call in calls)
