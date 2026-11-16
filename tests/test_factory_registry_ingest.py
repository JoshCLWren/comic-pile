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
            "id": 13, "author_association": "OWNER"}
    evil = {**good, "author_association": "NONE"}
    mismatch = {**good, "body": marker + "\nWorker: opencode-free-model-factory-44"}
    assert ingest.marker_ids([good, evil, mismatch]) == [
        {"worker": "43", "kind": "heartbeat", "id": "13"}
    ]

def test_stale_cursor_cannot_trigger_unbounded_history_scan(monkeypatch):
    now = datetime(2026, 11, 16, 3, tzinfo=UTC)
    monkeypatch.setattr(ingest, "registry_ingest_checkpoint",
                        lambda repo: (now - timedelta(days=12)).isoformat())
    assert ingest.since_timestamp("JoshCLWren/comic-pile", now).startswith("2026-11-16T01:00")
