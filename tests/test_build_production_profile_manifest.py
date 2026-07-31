"""Tests for the sanitized production-profile workload manifest builder."""

from __future__ import annotations

import importlib.util
import json
from datetime import datetime, timedelta, timezone
from pathlib import Path


def _load_module():
    path = Path(__file__).parents[1] / "scripts" / "build_production_profile_manifest.py"
    spec = importlib.util.spec_from_file_location("build_production_profile_manifest", path)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


MODULE = _load_module()


def _entry(index: int, method: str = "GET", path: str = "/api/noop") -> dict[str, object]:
    started = datetime(2026, 7, 30, 20, 0, tzinfo=timezone.utc) + timedelta(milliseconds=index * 100)
    return {
        "startedDateTime": started.isoformat(),
        "time": 25 + index,
        "request": {
            "method": method,
            "url": f"https://comic-pile.example{path}",
            "headers": [
                {"name": "Authorization", "value": "Bearer TOP-SECRET"},
                {"name": "Cookie", "value": "refresh_token=TOP-SECRET"},
            ],
            "cookies": [{"name": "refresh_token", "value": "TOP-SECRET"}],
        },
        "response": {
            "status": 200,
            "headers": [{"name": "Set-Cookie", "value": "refresh_token=TOP-SECRET"}],
            "content": {"mimeType": "application/json", "text": "{}"},
        },
    }


def _source_har() -> dict[str, object]:
    entries = [_entry(index) for index in range(198)]
    anchor_urls = {
        0: ("GET", "/api/auth/me"),
        1: ("POST", "/api/auth/refresh"),
        15: ("POST", "/api/rate/"),
        49: ("GET", "/api/v1/threads/123/issues?page_size=100"),
        85: ("POST", "/api/v1/issues/456:markRead"),
        124: ("POST", "/api/v1/threads/123/issues:reorder"),
        137: ("POST", "/api/v1/dependencies/"),
        161: ("POST", "/api/bug-reports/"),
        165: ("POST", "/api/threads/reactivate"),
        173: ("POST", "/api/v1/issues/456:markUnread"),
        180: ("POST", "/api/roll/set-die?die=50"),
        197: ("GET", "/api/threads/stale?days=7"),
    }
    for index, (method, path) in anchor_urls.items():
        entries[index] = _entry(index, method, path)

    entries[0]["response"]["status"] = 401
    entries[4] = _entry(4, "GET", "/api/sessions/current/")
    entries[4]["response"]["content"]["text"] = json.dumps(
        {
            "id": 1000,
            "current_die": 12,
            "manual_die": None,
            "ladder_path": "6 → 8 → 12",
            "active_thread": {"id": 99, "title": "Sensitive title"},
        }
    )
    entries[5] = _entry(5, "GET", "/api/threads/?page_size=200")
    entries[5]["response"]["content"]["text"] = json.dumps(
        {"threads": [{"id": index, "title": f"Secret {index}"} for index in range(68)], "next_page_token": None}
    )
    entries[6] = _entry(6, "GET", "/api/threads/stale?days=7")
    entries[6]["response"]["content"]["text"] = json.dumps([{"id": index} for index in range(15)])
    entries[10] = _entry(10, "GET", "/api/sessions/")
    entries[10]["response"]["content"]["text"] = json.dumps(
        {"sessions": [{"id": index} for index in range(50)], "next_page_token": "SECRET-CURSOR"}
    )
    entries[11] = _entry(11, "GET", "/api/analytics/metrics")
    entries[11]["response"]["content"]["text"] = json.dumps(
        {
            "total_threads": 68,
            "active_threads": 60,
            "completed_threads": 8,
            "event_stats": {"rate": 87, "snooze": 16, "roll": 136},
        }
    )
    entries[15]["request"]["postData"] = {
        "mimeType": "application/json",
        "text": json.dumps(
            {
                "thread_id": 123,
                "rating": 4.5,
                "finish_session": False,
                "issue_number": "7",
                "secret": "TOP-SECRET",
            }
        ),
    }
    entries.insert(3, _entry(999, "GET", "/assets/application.js"))
    entries[3]["request"]["url"] = "https://comic-pile.example/assets/application.js"
    return {"log": {"version": "1.2", "creator": {"name": "test"}, "entries": entries}}


def test_build_manifest_redacts_credentials_and_resource_values(tmp_path: Path) -> None:
    har_path = tmp_path / "source.har"
    har_path.write_text(json.dumps(_source_har()))

    manifest = MODULE.build_manifest(har_path)
    serialized = json.dumps(manifest)

    assert manifest["source"]["apiRequestCount"] == 198
    assert manifest["source"]["totalHarEntries"] == 199
    assert manifest["sourceAccountBaseline"] == {
        "currentSession": {
            "present": True,
            "currentDie": 12,
            "manualDie": None,
            "ladderStepCount": 3,
            "hasActiveThread": True,
        },
        "threadListPageCount": 68,
        "threadListHasNextPage": False,
        "staleThreads": 15,
        "historyFirstPageCount": 50,
        "historyHasNextPage": True,
        "totalThreads": 68,
        "activeThreads": 60,
        "completedThreads": 8,
        "eventCounts": {"rate": 87, "snooze": 16, "roll": 136},
    }
    large_thread = next(group for group in manifest["actionGroups"] if group["id"] == "open-large-thread")
    assert large_thread["initialRequest"] == "GET /api/v1/threads/:id/issues?page_size=100"
    rating_request = next(item for item in manifest["mutationBodyShapes"] if item["route"] == "/api/rate/")
    assert rating_request["requestBodyShape"] == {
        "finish_session": "boolean",
        "issue_number": "string",
        "rating": "number",
        "secret": "string",
        "thread_id": "integer",
    }
    assert len(manifest["actionGroups"]) == 28
    assert len(manifest["coverage"]) == 27
    assert "TOP-SECRET" not in serialized
    assert "Sensitive title" not in serialized
    assert "SECRET-CURSOR" not in serialized


def test_build_manifest_rejects_an_incomplete_source_har(tmp_path: Path) -> None:
    har = _source_har()
    har["log"]["entries"] = har["log"]["entries"][:-1]
    har_path = tmp_path / "incomplete.har"
    har_path.write_text(json.dumps(har))

    try:
        MODULE.build_manifest(har_path)
    except ValueError as error:
        assert "198 API requests" in str(error)
    else:
        raise AssertionError("Expected an incomplete source HAR to be rejected")
