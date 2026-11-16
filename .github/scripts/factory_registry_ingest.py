#!/usr/bin/env python3
"""Bounded trusted GitHub registry delta ingestion; never persists a body cache."""
from __future__ import annotations

import json
import os
import re
import subprocess
from datetime import datetime, timedelta, timezone
from urllib.parse import quote

from factory_state_ledger import record_heartbeat_comments
from factory_state_operations import (
    REPO_RE, checkpoint, registry_ingest_checkpoint, remember_verified_markers,
)
from factory_work_policy import comment_is_trusted

MARKER = re.compile(
    r"^<!-- factory-(heartbeat|attempt-outcome):v1 "
    r"worker=opencode-free-model-factory-(\d+) -->"
)
WORKER = re.compile(r"(?m)^Worker:\s*opencode-free-model-factory-(\d+)\s*$")

def since_timestamp(repo: str, now: datetime) -> str:
    """Limit any stale cursor to two hours; use one-minute overlap."""
    floor = now - timedelta(hours=2)
    stamp = registry_ingest_checkpoint(repo)
    if stamp:
        try:
            old = datetime.fromisoformat(stamp.replace("Z", "+00:00"))
            if old.tzinfo is not None:
                floor = max(floor, old.astimezone(timezone.utc) - timedelta(minutes=1))
        except ValueError:
            pass
    return floor.isoformat().replace("+00:00", "Z")

def marker_ids(changes: list[dict[str, object]]) -> list[dict[str, str]]:
    """A trusted canonical marker can only claim its own worker ID."""
    verified: list[dict[str, str]] = []
    for item in changes:
        if not comment_is_trusted(item):
            continue
        issue_url = str(item.get("issue_url") or "")
        if issue_url != "https://api.github.com/repos/JoshCLWren/comic-pile/issues/1093":
            continue
        body = str(item.get("body") or "")
        marker = MARKER.match(body)
        worker = WORKER.search(body)
        comment_id = str(item.get("id") or "")
        if (not marker or not worker or marker.group(2) != worker.group(1)
                or not comment_id.isdecimal() or int(comment_id) <= 0):
            continue
        verified.append({
            "worker": marker.group(2),
            "kind": "heartbeat" if marker.group(1) == "heartbeat" else "attempt",
            "id": comment_id,
        })
    return verified

def flatten(value: object) -> list[dict[str, object]]:
    if not isinstance(value, list):
        raise ValueError("GitHub registry delta must be a list of pages")
    return [
        comment for page in value
        for comment in (page if isinstance(page, list) else [page])
        if isinstance(comment, dict)
    ]

def ingest(repo: str) -> tuple[int, int, int]:
    if not REPO_RE.fullmatch(repo):
        raise ValueError("invalid repository")
    now = datetime.now(timezone.utc)
    since = since_timestamp(repo, now)
    endpoint = f"repos/{repo}/issues/1093/comments?per_page=100&since={quote(since, safe='')}"
    response = subprocess.run(
        ["gh", "api", "--paginate", "--slurp", endpoint],
        check=True, capture_output=True, text=True, timeout=90,
    )
    changes = flatten(json.loads(response.stdout))
    events = record_heartbeat_comments(repo, changes)
    ids = remember_verified_markers(repo, marker_ids(changes))
    # Commit only after successful fetch and durable writes; never jump over
    # an uncommitted event due to a failed upstream API request.
    checkpoint(repo, "registry-event-ingest-v2", now.isoformat(), events)
    return len(changes), events, ids

def main() -> int:
    repo = os.environ.get("GITHUB_REPOSITORY", "JoshCLWren/comic-pile")
    changes, events, ids = ingest(repo)
    print(f"[factory-registry] delta comments={changes}, events={events}, updated marker IDs={ids}")
    return 0

if __name__ == "__main__":
    raise SystemExit(main())
