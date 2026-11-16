"""Trust boundaries and bounded cursors for registry delta ingestion."""
from __future__ import annotations
import importlib
import sys
from datetime import UTC, datetime, timedelta
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / ".github/scripts"))
ingest = importlib.import_module("factory_registry_ingest")

def test_untrusted_and_mismatched_markers_never_seed_ids():
    marker = "<!-- factory-heartbeat:v1 worker=opencode-free-model-factory-43 -->"
    good = {"body": marker + "\nWorker: opencode-free-model-factory-43\n",
            "id": 13, "author_association": "OWNER",
            "issue_url": "https://api.github.com/repos/JoshCLWren/comic-pile/issues/1093"}
    evil = {**good, "author_association": "NONE"}
    mismatch = {**good, "body": marker + "\nWorker: opencode-free-model-factory-44"}
    wrong_issue = {**good, "issue_url": "https://api.github.com/repos/JoshCLWren/comic-pile/issues/6"}
    assert ingest.marker_ids([good, evil, mismatch, wrong_issue]) == [
        {"worker": "43", "kind": "heartbeat", "id": "13"}
    ]

def test_stale_cursor_cannot_trigger_unbounded_history_scan(monkeypatch):
    now = datetime(2026, 11, 16, 3, tzinfo=UTC)
    monkeypatch.setattr(ingest, "registry_ingest_checkpoint",
                        lambda repo: (now - timedelta(days=12)).isoformat())
    assert ingest.since_timestamp("JoshCLWren/comic-pile", now).startswith("2026-11-16T01:00")

def test_installation_quota_error_is_explicit_and_does_not_advance_cursor(monkeypatch):
    import subprocess
    import pytest
    monkeypatch.setattr(ingest, "since_timestamp", lambda *_: "2026-11-16T02:00:00Z")
    monkeypatch.setattr(ingest.subprocess, "run", lambda *args, **kwargs: subprocess.CompletedProcess(
        args[0], 1, "", "gh: API rate limit exceeded for installation (HTTP 403); secret=not-for-logs"
    ))
    monkeypatch.setattr(ingest, "checkpoint", lambda *_: pytest.fail("failed fetch must not advance checkpoint"))
    with pytest.raises(RuntimeError, match="installation API quota exhausted; checkpoint unchanged") as error:
        ingest.ingest("JoshCLWren/comic-pile")
    assert "secret=not-for-logs" not in str(error.value)


def test_timeout_does_not_advance_registry_checkpoint(monkeypatch):
    import subprocess
    import pytest
    monkeypatch.setattr(ingest, "since_timestamp", lambda *_: "2026-11-16T02:00:00Z")
    def timeout(*args, **kwargs):
        raise subprocess.TimeoutExpired(args[0], 90)
    monkeypatch.setattr(ingest.subprocess, "run", timeout)
    monkeypatch.setattr(ingest, "checkpoint", lambda *_: pytest.fail("timeout must not advance checkpoint"))
    with pytest.raises(RuntimeError, match="timed out; checkpoint unchanged"):
        ingest.ingest("JoshCLWren/comic-pile")
