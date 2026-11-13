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


def test_issue_event_normalization_preserves_queue_fields():
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


def test_pr_webhook_normalization_preserves_current_head_and_stage():
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


def test_closed_event_marks_projection_non_executable():
    kind, number, item, state = projection.normalize_event({
        "action": "closed", "issue": {
            "number": 44, "state": "closed", "labels": [], "title": "Done",
        }
    })
    assert (kind, number, state) == ("issue", 44, "closed")


def test_does_not_accept_malformed_issues_or_prs():
    assert projection.normalize_event({}) is None
    assert projection.normalize_event({"issue": {"number": "44"}}) is None


def test_projection_read_defers_to_github_without_trusted_connection(monkeypatch):
    monkeypatch.delenv("FACTORY_STATE_DSN_FILE", raising=False)
    assert projection.projected_json("JoshCLWren/comic-pile", "issue") is None


def test_live_event_ingestion_requires_neon(monkeypatch):
    monkeypatch.delenv("FACTORY_STATE_DSN_FILE", raising=False)
    with pytest.raises(RuntimeError, match="requires trusted Neon"):
        projection.ingest_event("JoshCLWren/comic-pile", "123", {"issue": {"number": 1}})


def test_invalid_projection_kind_fails_closed():
    with pytest.raises(ValueError):
        projection._prefix("owner/repo", "worker")


def test_trusted_webhook_does_not_checkout_pr_branch_or_expose_write_token():
    workflow = (ROOT / ".github/workflows/factory-target-projections.yml").read_text()
    assert "pull_request_target:" in workflow
    assert "issues:" in workflow
    assert "ref: main" in workflow
    assert "persist-credentials: false" in workflow
    assert "permissions:\n  contents: read" in workflow
    assert "github.event.repository.full_name == github.repository" in workflow
    assert "factory_state_projection.py ingest" in workflow
    assert "secrets.NEON_API_KEY" in workflow
    assert "github.event.pull_request.head" not in workflow


def test_controller_uses_projection_with_30_minute_reconciliation():
    source = (ROOT / ".github/scripts/factory-work-controller.py").read_text()
    assert 'projected_json(REPO, "issue")' in source
    assert 'projected_json(REPO, "pr")' in source
    assert 'reconcile_snapshot(REPO, "issue", issues, started)' in source
    assert 'reconcile_snapshot(REPO, "pr", prs, started)' in source
    assert projection.RECONCILE_SECONDS == 1800
