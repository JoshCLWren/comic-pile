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




def test_contended_refresh_serves_only_bounded_recent_shared_snapshot(monkeypatch, tmp_path):
    monkeypatch.setenv("FACTORY_STATE_DSN_FILE", str(tmp_path / "connection"))
    monkeypatch.setattr(cache, "_read", lambda _: ([{"number": 43}], False))
    monkeypatch.setattr(cache, "_claim", lambda *_: False)
    calls = []
    monkeypatch.setattr(cache, "_recent_contended", lambda key, grace: calls.append((key, grace)) or [{"number": 43}])
    monkeypatch.setattr(cache.time, "sleep", lambda _: pytest.fail("stale shared discovery should not wait"))
    result = cache.cached_json("issues", lambda _: pytest.fail("contended refresh must not stampede GitHub"), ttl_seconds=45)
    assert result == [{"number": 43}]
    assert calls == [("issues", 45)]


def test_contended_cache_does_not_trust_stale_record_without_refresh_owner(monkeypatch, tmp_path):
    monkeypatch.setenv("FACTORY_STATE_DSN_FILE", str(tmp_path / "connection"))
    reads = iter([([{"number": 43}], False), ([{"number": 44}], True)])
    monkeypatch.setattr(cache, "_read", lambda _: next(reads))
    monkeypatch.setattr(cache, "_claim", lambda *_: False)
    monkeypatch.setattr(cache, "_recent_contended", lambda *_: None)
    monkeypatch.setattr(cache.time, "sleep", lambda _: None)
    assert cache.cached_json("issues", lambda _: pytest.fail("winner's fresh data should be used")) == [{"number": 44}]

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
    # The local independent reviewer must never receive database credentials.
    local_review = (root / ".github/workflows/local-ollama-review.yml").read_text()
    assert "factory-state-cache" not in local_review
    assert "FACTORY_STATE_DSN_FILE" not in local_review

    # In the reusable workflow only the separate trusted cleanup runner can
    # connect to Neon, not the agent/model execution job.
    import yaml

    reusable = yaml.safe_load(
        (root / ".github/workflows/free-model-factory-run.yml").read_text()
    )
    model_job = reusable["jobs"]["factory"]
    cleanup_job = reusable["jobs"]["release_pre_session_lease"]
    completed_cleanup_job = reusable["jobs"]["release_post_session_lease"]
    assert "factory-state-cache" not in str(model_job)
    assert "FACTORY_STATE_DSN_FILE" not in str(model_job)
    assert "NEON_API_KEY" not in str(model_job)
    for trusted_job in (cleanup_job, completed_cleanup_job):
        assert any(
            step.get("uses") == "./.github/actions/factory-state-cache"
            for step in trusted_job["steps"]
        )

    # The trusted Entry snapshot job reads Neon; the reusable worker never does.
    entry = (root / ".github/workflows/free-model-factory-entry.yml").read_text()
    snapshot, collector = entry.split("\n  persist_outcome:", 1)
    assert "model_health_snapshot:" in snapshot
    assert "factory-state-cache" in snapshot
    assert "model_exclusions: ${{ needs.model_health_snapshot.outputs.exclusions }}" in snapshot
    assert "FACTORY_STATE_DSN_FILE" not in snapshot
    assert "factory-state-cache" in collector
    # The collector always waits for the worker. After #5137 it also needs
    # the trusted Neon snapshot to use the existing attempt comment ID.
    # Check the dependency graph, not a YAML spelling that changed from a
    # scalar to a list when that second dependency was introduced.
    entry_jobs = yaml.safe_load(entry)["jobs"]
    collector_job = entry_jobs["persist_outcome"]
    needs = collector_job["needs"]
    needs_set = {needs} if isinstance(needs, str) else set(needs)
    assert "run" in needs_set
    assert collector_job["if"] == "${{ always() }}"
    assert collector_job["permissions"]["actions"] == "read"
    # The separate trusted collector can now publish recovery drafts and retire
    # incorporated refs. Its checkout remains main and never executes model code.
    assert collector_job["permissions"]["contents"] == "write"
    assert collector_job["permissions"]["pull-requests"] == "write"
    checkout = next(step for step in collector_job["steps"]
                    if step.get("uses", "").startswith("actions/checkout@"))
    assert checkout["with"]["ref"] == "main"
    assert checkout["with"]["persist-credentials"] is False
    assert "factory_checkpoint_handoff.py" in collector
    if "ATTEMPT_COMMENT_ID:" in collector:
        assert "model_health_snapshot" in needs_set
        assert collector_job["permissions"]["issues"] == "write"
        assert "needs.model_health_snapshot.outputs.attempt_id" in collector
        assert "issues/comments/$ATTEMPT_COMMENT_ID" in collector
    assert "run / factory" in collector


def test_recovery_watchdog_loads_paginated_compatible_neon_registry() -> None:
    workflow = (Path(__file__).resolve().parents[1] / ".github/workflows/fixed-model-factory-dispatch-recovery.yml").read_text()
    assert "from factory_completion_controller import registry_comments" in workflow
    assert "json.dumps([registry_comments()])" in workflow
    assert "issues/1093/comments?per_page=100" not in workflow
    assert "factory_heartbeat_health.py" in workflow
    assert "uses: ./.github/actions/factory-state-cache" in workflow


def test_unchanged_snapshot_extends_ttl_without_rewriting_payload(monkeypatch, tmp_path):
    monkeypatch.setenv("FACTORY_STATE_DSN_FILE", str(tmp_path / "connection"))
    data = [{"number": 3, "body": "large stable response" * 1000}]
    monkeypatch.setattr(cache, "_read", lambda _: (data, False))
    monkeypatch.setattr(cache, "_claim", lambda *_: True)
    monkeypatch.setattr(cache, "_publish", lambda *_: pytest.fail("unchanged payload must not be rewritten"))
    extended = []
    monkeypatch.setattr(cache, "_refresh_without_rewrite", lambda *args: extended.append(args))
    assert cache.cached_json("cache-key", lambda _: data, ttl_seconds=450) == data
    assert len(extended) == 1
    assert extended[0][0] == "cache-key"
    assert extended[0][2:] == (450, 1)


def test_changed_snapshot_still_persists_new_content(monkeypatch, tmp_path):
    monkeypatch.setenv("FACTORY_STATE_DSN_FILE", str(tmp_path / "connection"))
    monkeypatch.setattr(cache, "_read", lambda _: ([{"number": 3}], False))
    monkeypatch.setattr(cache, "_claim", lambda *_: True)
    monkeypatch.setattr(cache, "_refresh_without_rewrite", lambda *_: pytest.fail("changed payload must be saved"))
    published = []
    monkeypatch.setattr(cache, "_publish", lambda *args: published.append(args))
    assert cache.cached_json("cache-key", lambda _: [{"number": 4}], ttl_seconds=450) == [{"number": 4}]
    assert published[0][2] == [{"number": 4}]


def test_prune_is_bounded_and_cannot_delete_leases_or_projections(monkeypatch):
    executed = []
    def fake_run(statement, *args, one=False):
        executed.append((statement, args, one))
        return {"deleted": 4}
    monkeypatch.setattr(cache, "_run", fake_run)
    assert cache._prune_expired_github_cache(200) == 4
    query, args, one = executed[0]
    assert args == (200,) and one is True
    assert "DELETE FROM public.factory_state_kv" in query
    assert "factory-github-get-v1:%" in query
    assert "expires_at < now() - interval '30 minutes'" in query
    assert "refresh_until IS NULL OR" in query
    with pytest.raises(ValueError, match="batch"):
        cache._prune_expired_github_cache(1001)


def test_prune_cli_cleans_in_batches_with_upper_limit(monkeypatch, tmp_path):
    monkeypatch.setenv("FACTORY_STATE_DSN_FILE", str(tmp_path / "connection"))
    calls = []
    def prune():
        calls.append(True)
        return 200 if len(calls) < 3 else 12
    monkeypatch.setattr(cache, "_prune_expired_github_cache", prune)
    assert cache.main(["prune-expired"]) == 0
    assert len(calls) == 3


def test_regular_status_job_prunes_only_in_trusted_controller():
    root = Path(__file__).resolve().parents[1]
    workflow = (root / ".github/workflows/factory-status-pages.yml").read_text()
    assert "cron: '*/5 * * * *'" in workflow
    assert "Prune expired generic GitHub discovery snapshots" in workflow
    assert "factory_state_cache.py prune-expired" in workflow
    assert workflow.index("uses: ./.github/actions/factory-state-cache") < workflow.index("factory_state_cache.py prune-expired")
    assert workflow.index("factory_state_cache.py prune-expired") < workflow.index("Generate factory dashboard")
    # Cleanup no longer depends on a large scheduled PR-history recovery sweep.
    reconciliation = (root / ".github/workflows/factory-issue-pr-state-reconciler.yml").read_text()
    assert "factory_state_cache.py prune-expired" not in reconciliation


def test_compacted_registry_retains_essential_evidence_without_old_history():
    from datetime import datetime, timezone

    def comment(id, updated, body, association="OWNER"):
        return {
            "id": id, "created_at": updated, "updated_at": updated,
            "body": body, "author_association": association,
        }

    records = [
        comment(1, "2026-10-01T00:00:00Z", "<!-- factory-attempt-outcome:v1 worker=opencode-free-model-factory-7 -->\\nWorker: opencode-free-model-factory-7\\nAttempt outcome: provider_failure\\nUpdated: 2026-10-01T00:00:00Z"),
        comment(2, "2026-10-02T00:00:00Z", "Source: kilo-auto\\nModel: free/test\\nAttempt outcome: model_unavailable\\nUpdated: 2026-10-02T00:00:00Z"),
        comment(3, "2026-10-03T00:00:00Z", "<!-- factory-model-retired-410:v1 -->\\nSource: kilo-auto\\nModel: free/test\\nUpdated: 2026-10-03T00:00:00Z"),
        comment(4, "2026-10-04T00:00:00Z", "<!-- factory-attempt-outcome:v1 worker=opencode-free-model-factory-7 -->\\nWorker: opencode-free-model-factory-7\\nAttempt outcome: success\\nUpdated: 2026-10-04T00:00:00Z"),
        comment(5, "2026-10-05T00:00:00Z", "Source: kilo-auto\\nModel: free/test\\nAttempt outcome: success\\nUpdated: 2026-10-05T00:00:00Z"),
        comment(6, "2026-11-14T23:00:00Z", "Run: 555\\nWorker: opencode-free-model-factory-8"),
        comment(7, "2026-10-06T00:00:00Z", "untrusted ancient filler", "NONE"),
        comment(8, "2026-11-15T00:00:00Z", "untrusted fresh observation", "NONE"),
        comment(9, "2026-10-07T00:00:00Z", "<!-- factory-completion-funnel:v1 -->\\nUpdated: 2026-10-07T00:00:00Z"),
    ]
    compacted = cache.compact_registry_comments(
        records,
        trusted=lambda row: row.get("author_association") == "OWNER",
        now=datetime(2026, 11, 15, 12, tzinfo=timezone.utc),
    )
    assert {row["id"] for row in compacted} == {3, 4, 5, 6, 8, 9}
    assert [row["id"] for row in compacted] == [3, 4, 5, 9, 6, 8]
    # Preserve the freshest GitHub update so the incremental cursor never
    # starts paging all the old registry comments again.
    since = []
    merged = cache.incremental_comments(compacted, lambda cursor: since.append(cursor) or [])
    assert since == ["2026-11-14T23:59:00Z"]
    assert merged == compacted


def test_compacted_registry_has_bounded_growth_and_honors_edited_old_comment():
    from datetime import datetime, timezone

    now = datetime(2026, 11, 15, 12, tzinfo=timezone.utc)
    historic = [
        {"id": i, "created_at": f"2026-10-{(i % 28) + 1:02d}T00:00:00Z",
         "updated_at": f"2026-10-{(i % 28) + 1:02d}T00:00:00Z",
         "body": "unrelated historical comment", "author_association": "OWNER"}
        for i in range(1, 1001)
    ]
    fresh = {"id": 1001, "created_at": "2026-11-15T11:00:00Z",
             "updated_at": "2026-11-15T11:00:00Z",
             "body": "current", "author_association": "OWNER"}
    slim = cache.compact_registry_comments(
        [*historic, fresh], trusted=lambda _: True, now=now,
    )
    assert [item["id"] for item in slim] == [1001]
    edited = {**historic[0], "updated_at": "2026-11-15T11:30:00Z",
              "body": "edited historical observation"}
    merged = cache.incremental_comments(slim, lambda _: [edited])
    again = cache.compact_registry_comments(merged, trusted=lambda _: True, now=now)
    assert {item["id"] for item in again} == {1, 1001}
