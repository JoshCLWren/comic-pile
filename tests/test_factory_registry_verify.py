"""Canonical issue/author/worker validation before using a cached comment ID."""
from __future__ import annotations
import importlib
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / ".github/scripts"))
verification = importlib.import_module("factory_registry_verify")

def test_wrong_issue_and_forged_app_never_become_marker_locator():
    trusted = {"id": 123, "body": "<!-- factory-heartbeat:v1 worker=opencode-free-model-factory-43 -->\nWorker: opencode-free-model-factory-43",
               "issue_url": "https://api.github.com/repos/JoshCLWren/comic-pile/issues/1093",
               "user": {"login": "github-actions[bot]"}, "performed_via_github_app": {"slug": "github-actions"}}
    copied = {**trusted, "id": 124, "issue_url": "https://api.github.com/repos/JoshCLWren/comic-pile/issues/6"}
    forged = {**trusted, "id": 125, "user": {"login": "agent-bot"},
              "performed_via_github_app": {"slug": "untrusted"}}
    assert verification.select([[trusted,copied,forged]], "43", "heartbeat") == "123"
    assert verification.select(trusted, "43", "heartbeat", "123") == "123"
    assert verification.select(trusted, "44", "heartbeat", "123") == ""
    assert verification.select(trusted, "43", "attempt", "123") == ""
