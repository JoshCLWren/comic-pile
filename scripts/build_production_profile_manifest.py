#!/usr/bin/env python3
"""Build the sanitized production-profile workload manifest from a browser HAR.

The generated manifest intentionally contains no cookies, authorization headers,
raw request bodies, response bodies, captured resource IDs, or account names.
"""

from __future__ import annotations

import argparse
import base64
import hashlib
import json
import math
import re
from collections import Counter, defaultdict
from datetime import datetime
from pathlib import Path
from urllib.parse import parse_qsl, urlencode, urlparse

SCHEMA_VERSION = 1
CONCURRENCY_WINDOW_MS = 25
DYNAMIC_QUERY_KEYS = {
    "collection_id",
    "issue_id",
    "page_token",
    "session_id",
    "snapshot_id",
    "thread_id",
}
PRESERVED_QUERY_KEYS = {"days", "die", "page_size", "search", "status"}

# These ranges are indexes in the API-only request stream. Anchors make the
# source-HAR assumption explicit and fail generation if the recording changes.
ACTION_GROUPS = [
    ("cold-authenticated-start", 0, 7, "cold-start", "Cold application start and refresh-token bootstrap"),
    ("home-revisit", 8, 9, "navigation", "Return to queue and current session"),
    ("session-history", 10, 10, "navigation", "Open session history"),
    ("analytics-first", 11, 11, "navigation", "Open analytics"),
    ("rating-first", 12, 18, "rating", "Return home and submit the first rating"),
    ("roll-rate", 19, 25, "rating", "Roll, load context, and rate"),
    ("roll-snooze", 26, 31, "rating", "Roll, load context, and snooze"),
    ("roll-dismiss-pending", 32, 37, "rating", "Roll and dismiss pending"),
    ("roll-set-pending", 38, 43, "rating", "Roll and set a previous thread pending"),
    ("queue-front", 44, 48, "queue", "Move a thread to the front and refresh queue state"),
    ("open-large-thread", 49, 84, "thread", "Open a 35-issue thread and load issue dependencies"),
    ("mark-read", 85, 85, "thread", "Mark an issue read"),
    ("add-issue", 86, 123, "thread", "Add an issue and refresh issue dependency state"),
    ("reorder-issues", 124, 124, "thread", "Reorder issues"),
    ("delete-issue", 125, 125, "thread", "Delete an issue"),
    ("edit-thread", 126, 127, "thread", "Edit thread metadata and refresh the queue"),
    ("queue-back-dependencies", 128, 130, "queue", "Move a thread back and open dependency management"),
    ("progressive-search", 131, 134, "search", "Run progressive thread searches"),
    ("create-dependency", 135, 139, "dependency", "Load dependency candidates and create a dependency"),
    ("dependency-management", 140, 160, "dependency", "Inspect blocked state and delete dependencies"),
    ("bug-report", 161, 161, "bug-report", "Submit a bug report"),
    ("analytics-second", 162, 162, "navigation", "Revisit analytics"),
    ("reactivation", 163, 170, "reactivation", "Reactivate a completed thread and refresh account state"),
    ("mark-unread", 171, 175, "thread", "Open issue data and mark an issue unread"),
    ("rating-second", 176, 179, "rating", "Submit another rating and capture refetches"),
    ("dice-changes", 180, 183, "rating", "Change the manual die several times"),
    ("roll-dismiss-second", 184, 189, "rating", "Roll, load context, and dismiss pending again"),
    ("final-roll-rate", 190, 197, "rating", "Change die, roll, load context, and rate"),
]


POST_FIX_REQUEST_COUNT_RANGES = {
    "open-large-thread": [2, 6],
    "add-issue": [3, 8],
}

ANCHORS = {
    0: ("GET", "/api/auth/me"),
    1: ("POST", "/api/auth/refresh"),
    15: ("POST", "/api/rate/"),
    49: ("GET", "/api/v1/threads/:id/issues?page_size=100"),
    85: ("POST", "/api/v1/issues/:id:markRead"),
    124: ("POST", "/api/v1/threads/:id/issues:reorder"),
    137: ("POST", "/api/v1/dependencies/"),
    161: ("POST", "/api/bug-reports/"),
    165: ("POST", "/api/threads/reactivate"),
    173: ("POST", "/api/v1/issues/:id:markUnread"),
    180: ("POST", "/api/roll/set-die?die=50"),
    197: ("GET", "/api/threads/stale?days=7"),
}

COVERAGE = [
    ("authentication refresh", "reproduced exactly", "Start with a refresh cookie and no in-memory access token."),
    ("collections load", "reproduced exactly", "Account-wide read."),
    ("startup current session, thread list, stale threads, and auth reads", "reproduced exactly", "Preserve the concurrent startup burst."),
    ("session history navigation", "reproduced exactly", "Account-wide read with pagination metadata."),
    ("analytics navigation", "reproduced exactly", "Account-wide read."),
    ("repeated ratings", "reproduced with dynamic IDs", "Rate eligible fixture threads and capture automatic refetches."),
    ("repeated rolls", "reproduced with dynamic IDs", "Resolve rolled thread IDs at runtime."),
    ("reading orders and connected threads after rolls", "reproduced with dynamic IDs", "Use runtime roll results."),
    ("snoozing", "reproduced with a safe disposable fixture inside the real account", "Fixture state is restored."),
    ("dismissing pending", "reproduced with a safe disposable fixture inside the real account", "Fixture state is restored."),
    ("setting a pending thread", "reproduced with a safe disposable fixture inside the real account", "Fixture state is restored."),
    ("queue movement to front and back", "reproduced with a safe disposable fixture inside the real account", "Snapshot and restore queue positions."),
    ("open a roughly 35-issue thread", "reproduced with a safe disposable fixture inside the real account", "Fixture contains 35 to 50 issues."),
    ("issue data and dependency batch", "reproduced with dynamic IDs", "Expect one thread batch request and zero legacy per-issue calls."),
    ("mark an issue read", "reproduced with a safe disposable fixture inside the real account", "Restore exact read state."),
    ("add an issue", "reproduced with a safe disposable fixture inside the real account", "Delete the added issue during cleanup."),
    ("reorder issues", "reproduced with a safe disposable fixture inside the real account", "Restore original order."),
    ("delete an issue", "reproduced with a safe disposable fixture inside the real account", "Delete only the issue created by the run."),
    ("edit thread title, format, or notes", "reproduced with a safe disposable fixture inside the real account", "Restore original metadata."),
    ("progressive thread searches", "reproduced exactly", "Preserve the AAS, AA, SP, and sp query sequence."),
    ("dependency management views", "reproduced with dynamic IDs", "Use fixture-owned dependency resources."),
    ("create and delete dependencies", "reproduced with a safe disposable fixture inside the real account", "Verify cleanup."),
    ("load blocked dependencies", "reproduced exactly", "Account-wide read after fixture mutation."),
    ("reactivate a thread", "reproduced with a safe disposable fixture inside the real account", "Use a fixture completed thread where supported."),
    ("mark an issue unread", "reproduced with a safe disposable fixture inside the real account", "Restore exact read state."),
    ("change dice values", "reproduced exactly", "Preserve 50, 100, 4, 20, then 100."),
    ("bug-report submission", "intentionally excluded", "No supported production cleanup path exists; request construction is tested without sending."),
]


def _decode_content(entry: dict[str, object]) -> str | None:
    content = entry.get("response", {}).get("content", {})
    text = content.get("text")
    if not isinstance(text, str):
        return None
    if content.get("encoding") == "base64":
        try:
            return base64.b64decode(text).decode("utf-8", errors="replace")
        except (ValueError, UnicodeDecodeError):
            return None
    return text


def _json_response(entry: dict[str, object]) -> object | None:
    text = _decode_content(entry)
    if not text:
        return None
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        return None


def _shape(value: object) -> object:
    if isinstance(value, dict):
        return {str(key): _shape(child) for key, child in sorted(value.items())}
    if isinstance(value, list):
        return [] if not value else [_shape(value[0])]
    if isinstance(value, bool):
        return "boolean"
    if isinstance(value, int):
        return "integer"
    if isinstance(value, float):
        return "number"
    if isinstance(value, str):
        return "string"
    if value is None:
        return "null"
    return type(value).__name__


def _request_body_shape(entry: dict[str, object]) -> object | None:
    post_data = entry.get("request", {}).get("postData")
    if not isinstance(post_data, dict):
        return None
    text = post_data.get("text")
    if not isinstance(text, str) or not text:
        return None
    try:
        return _shape(json.loads(text))
    except json.JSONDecodeError:
        return {"mimeType": str(post_data.get("mimeType", "unknown")), "kind": "opaque"}


def _normalize_path(path: str) -> str:
    return re.sub(r"/\d+(?=/|:|$)", "/:id", path)


def _normalize_url(raw_url: str) -> tuple[str, dict[str, list[str]]]:
    parsed = urlparse(raw_url)
    path = _normalize_path(parsed.path)
    query_shape: dict[str, list[str]] = defaultdict(list)
    rendered: list[tuple[str, str]] = []
    for key, value in sorted(parse_qsl(parsed.query, keep_blank_values=True)):
        if key in PRESERVED_QUERY_KEYS:
            normalized = value
        elif key in DYNAMIC_QUERY_KEYS or key.endswith("_id"):
            normalized = ":id" if key != "page_token" else ":cursor"
        else:
            normalized = ":value"
        query_shape[key].append(normalized)
        rendered.append((key, normalized))
    query = urlencode(rendered)
    return (f"{path}?{query}" if query else path, dict(query_shape))


def _mutation_category(method: str, normalized_url: str) -> str | None:
    if method == "GET":
        return None
    if normalized_url.startswith("/api/rate/"):
        return "rating"
    if normalized_url.startswith("/api/roll"):
        return "roll"
    if normalized_url.startswith("/api/snooze"):
        return "snooze"
    if "/queue/" in normalized_url:
        return "queue"
    if "/dependencies" in normalized_url:
        return "dependency"
    if "/issues" in normalized_url:
        return "issue"
    if normalized_url.startswith("/api/threads"):
        return "thread"
    if normalized_url.startswith("/api/bug-reports"):
        return "bug-report"
    if normalized_url.startswith("/api/auth"):
        return "authentication"
    return "other"


def _percentile(values: list[float], quantile: float) -> float:
    if not values:
        return 0.0
    ordered = sorted(values)
    index = min(len(ordered) - 1, math.ceil(len(ordered) * quantile) - 1)
    return round(ordered[index], 3)


def _started_ms(value: str) -> float:
    return datetime.fromisoformat(value).timestamp() * 1000


def _account_baseline(entries: list[dict[str, object]]) -> dict[str, object]:
    baseline: dict[str, object] = {}
    for entry in entries:
        path = urlparse(str(entry["request"]["url"])).path
        payload = _json_response(entry)
        if path == "/api/analytics/metrics" and isinstance(payload, dict):
            baseline.setdefault("totalThreads", payload.get("total_threads"))
            baseline.setdefault("activeThreads", payload.get("active_threads"))
            baseline.setdefault("completedThreads", payload.get("completed_threads"))
            baseline.setdefault("eventCounts", payload.get("event_stats"))
        elif path == "/api/threads/stale" and isinstance(payload, list):
            baseline.setdefault("staleThreads", len(payload))
        elif path == "/api/threads/" and isinstance(payload, dict) and "threads" in payload:
            threads = payload.get("threads")
            if isinstance(threads, list):
                baseline.setdefault("threadListPageCount", len(threads))
                baseline.setdefault("threadListHasNextPage", bool(payload.get("next_page_token")))
        elif path == "/api/sessions/" and isinstance(payload, dict):
            sessions = payload.get("sessions")
            if isinstance(sessions, list):
                baseline.setdefault("historyFirstPageCount", len(sessions))
                baseline.setdefault("historyHasNextPage", bool(payload.get("next_page_token")))
        elif path == "/api/sessions/current/" and isinstance(payload, dict):
            ladder_path = payload.get("ladder_path")
            baseline.setdefault(
                "currentSession",
                {
                    "present": True,
                    "currentDie": payload.get("current_die"),
                    "manualDie": payload.get("manual_die"),
                    "ladderStepCount": len(str(ladder_path).split("→")) if ladder_path else 0,
                    "hasActiveThread": payload.get("active_thread") is not None,
                },
            )
    return baseline


def build_manifest(har_path: Path) -> dict[str, object]:
    raw = har_path.read_bytes()
    har = json.loads(raw)
    all_entries = har["log"]["entries"]
    entries = [
        entry
        for entry in all_entries
        if urlparse(str(entry["request"]["url"])).path.startswith("/api/")
    ]
    if len(entries) != 198:
        raise ValueError(f"Expected the source HAR to contain 198 API requests, found {len(entries)}")

    first_started = _started_ms(str(entries[0]["startedDateTime"]))
    sanitized_requests: list[dict[str, object]] = []
    for index, entry in enumerate(entries):
        request = entry["request"]
        response = entry["response"]
        normalized_url, query_shape = _normalize_url(str(request["url"]))
        sanitized_requests.append(
            {
                "index": index,
                "offsetMs": round(_started_ms(str(entry["startedDateTime"])) - first_started),
                "method": request["method"],
                "route": normalized_url,
                "queryShape": query_shape,
                "requestBodyShape": _request_body_shape(entry),
                "status": response["status"],
                "durationMs": round(float(entry.get("time", 0)), 3),
                "mutationCategory": _mutation_category(str(request["method"]), normalized_url),
                "coldWarmClassification": "unclassified",
            }
        )

    for index, expected in ANCHORS.items():
        request = sanitized_requests[index]
        actual = (request["method"], request["route"])
        if actual != expected:
            raise ValueError(f"Source HAR anchor {index} changed: expected {expected}, found {actual}")

    action_groups: list[dict[str, object]] = []
    previous_request_start = first_started
    for action_id, start, end, phase, label in ACTION_GROUPS:
        action_requests = sanitized_requests[start : end + 1]
        concurrency_groups: list[dict[str, object]] = []
        current: list[int] = []
        group_start = 0
        for request in action_requests:
            offset = int(request["offsetMs"])
            if not current or offset - group_start <= CONCURRENCY_WINDOW_MS:
                if not current:
                    group_start = offset
                current.append(int(request["index"]))
            else:
                concurrency_groups.append({"requestIndexes": current})
                current = [int(request["index"])]
                group_start = offset
        if current:
            concurrency_groups.append({"requestIndexes": current})

        action_start = _started_ms(str(entries[start]["startedDateTime"]))
        follow_ups = []
        seen = set()
        for request in action_requests[1:]:
            key = f'{request["method"]} {request["route"]}'
            if key not in seen:
                seen.add(key)
                follow_ups.append(key)

        expected_range = POST_FIX_REQUEST_COUNT_RANGES.get(
            action_id,
            [max(1, len(action_requests) - 2), len(action_requests) + 3],
        )
        action_groups.append(
            {
                "id": action_id,
                "phase": phase,
                "label": label,
                "requestRange": [start, end],
                "requestCount": len(action_requests),
                "expectedRequestCountRange": expected_range,
                "coldWarmClassification": "unclassified",
                "pauseAfterPreviousActionMs": round(max(0, action_start - previous_request_start)),
                "concurrencyGroups": concurrency_groups,
                "initialRequest": f'{action_requests[0]["method"]} {action_requests[0]["route"]}',
                "expectedFollowUps": follow_ups,
            }
        )
        previous_request_start = _started_ms(str(entries[end]["startedDateTime"]))

    route_values: dict[tuple[str, str], list[dict[str, object]]] = defaultdict(list)
    for request in sanitized_requests:
        route_values[(str(request["method"]), str(request["route"]))].append(request)
    route_summaries = []
    for (method, route), requests in sorted(route_values.items()):
        durations = [float(request["durationMs"]) for request in requests]
        route_summaries.append(
            {
                "method": method,
                "route": route,
                "count": len(requests),
                "statuses": dict(sorted(Counter(int(request["status"]) for request in requests).items())),
                "p50Ms": _percentile(durations, 0.50),
                "p90Ms": _percentile(durations, 0.90),
                "p95Ms": _percentile(durations, 0.95),
                "p99Ms": _percentile(durations, 0.99),
                "maxMs": round(max(durations), 3),
            }
        )

    starts = [_started_ms(str(entry["startedDateTime"])) for entry in entries]
    ends = [start + float(entry.get("time", 0)) for start, entry in zip(starts, entries)]
    duplicate_bursts = []
    last_get: dict[str, tuple[int, float]] = {}
    for request, started in zip(sanitized_requests, starts):
        if request["method"] != "GET":
            continue
        route = str(request["route"])
        previous = last_get.get(route)
        if previous and started - previous[1] <= 250:
            duplicate_bursts.append(
                {
                    "route": route,
                    "previousRequestIndex": previous[0],
                    "requestIndex": request["index"],
                    "gapMs": round(started - previous[1]),
                }
            )
        last_get[route] = (int(request["index"]), started)

    duplicate_summary: list[dict[str, object]] = []
    for route in sorted({str(item["route"]) for item in duplicate_bursts}):
        route_items = [item for item in duplicate_bursts if item["route"] == route]
        duplicate_summary.append(
            {
                "route": route,
                "count": len(route_items),
                "minimumGapMs": min(int(item["gapMs"]) for item in route_items),
                "maximumGapMs": max(int(item["gapMs"]) for item in route_items),
            }
        )

    method_counts = Counter(str(request["method"]) for request in sanitized_requests)
    status_counts = Counter(int(request["status"]) for request in sanitized_requests)
    durations = [float(request["durationMs"]) for request in sanitized_requests]
    mutation_shapes = []
    seen_mutations = set()
    for request in sanitized_requests:
        if request["method"] == "GET":
            continue
        signature = (
            str(request["method"]),
            str(request["route"]),
            json.dumps(request["requestBodyShape"], sort_keys=True),
        )
        if signature in seen_mutations:
            continue
        seen_mutations.add(signature)
        mutation_shapes.append(
            {
                "method": request["method"],
                "route": request["route"],
                "requestBodyShape": request["requestBodyShape"],
                "mutationCategory": request["mutationCategory"],
            }
        )

    return {
        "schemaVersion": SCHEMA_VERSION,
        "manifestVersion": "2026-07-30-real-user-har-v1",
        "source": {
            "fileName": har_path.name,
            "sha256": hashlib.sha256(raw).hexdigest(),
            "capturedAt": entries[0]["startedDateTime"],
            "durationMs": round(max(ends) - min(starts)),
            "totalHarEntries": len(all_entries),
            "apiRequestCount": len(entries),
        },
        "sanitization": {
            "credentialsRetained": False,
            "rawHeadersRetained": False,
            "rawBodiesRetained": False,
            "responseBodiesRetained": False,
            "resourceIdsRetained": False,
            "notes": [
                "Numeric path identifiers become :id.",
                "Dynamic query identifiers and cursors are normalized.",
                "Request bodies retain key/type shape only.",
            ],
        },
        "sourceAccountBaseline": _account_baseline(entries),
        "baseline": {
            "methodCounts": dict(sorted(method_counts.items())),
            "statusCounts": {str(key): value for key, value in sorted(status_counts.items())},
            "latencyMs": {
                "p50": _percentile(durations, 0.50),
                "p90": _percentile(durations, 0.90),
                "p95": _percentile(durations, 0.95),
                "p99": _percentile(durations, 0.99),
                "max": round(max(durations), 3),
            },
            "duplicateGetBurstsWithin250Ms": duplicate_summary,
            "expectedEquivalentWorkloadRequestCountRange": [115, 150],
            "routeSummaries": route_summaries,
        },
        "actionGroups": action_groups,
        "mutationBodyShapes": mutation_shapes,
        "coverage": [
            {"action": action, "classification": classification, "reason": reason}
            for action, classification, reason in COVERAGE
        ],
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--har", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args()
    manifest = build_manifest(args.har)
    args.output.parent.mkdir(parents=True, exist_ok=True)

    routes_path = args.output.with_name(f"{args.output.stem}.routes.json")
    actions_path = args.output.with_name(f"{args.output.stem}.actions.json")
    routes = manifest["baseline"].pop("routeSummaries")
    actions = manifest.pop("actionGroups")
    mutations = manifest.pop("mutationBodyShapes")
    manifest["sidecars"] = {
        "actions": actions_path.name,
        "routes": routes_path.name,
    }
    manifest["actionGroupIds"] = [action["id"] for action in actions]

    args.output.write_text(json.dumps(manifest, separators=(",", ":"), sort_keys=False) + "\n")
    actions_path.write_text(
        json.dumps(
            {
                "manifestVersion": manifest["manifestVersion"],
                "actionGroups": actions,
                "mutationBodyShapes": mutations,
            },
            separators=(",", ":"),
            sort_keys=False,
        )
        + "\n"
    )
    routes_path.write_text(
        json.dumps(
            {
                "manifestVersion": manifest["manifestVersion"],
                "routeSummaries": routes,
            },
            separators=(",", ":"),
            sort_keys=False,
        )
        + "\n"
    )


if __name__ == "__main__":
    main()
