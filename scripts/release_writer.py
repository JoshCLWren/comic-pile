#!/usr/bin/env python3
"""Validate release-writer payloads and keep credentials outside model prompts."""

from __future__ import annotations

import json
import os
import sys
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime
from typing import NoReturn

_ALLOWED_VISIBILITY = {"public", "internal"}
_ALLOWED_STATUS = {"draft", "published", "retracted"}
_REQUIRED = {
    "source_repository",
    "source_pr_number",
    "source_merge_sha",
    "merged_at",
    "released_at",
    "category",
    "title",
    "summary",
}
_GITHUB_API_BASE = "https://api.github.com"


def _fail(message: str) -> NoReturn:
    print(message, file=sys.stderr)
    raise SystemExit(2)


def _api_base() -> str:
    value = os.getenv("RELEASE_API_URL", "").strip().rstrip("/")
    if not value:
        _fail("RELEASE_API_URL is required")
    return value


def _token() -> str:
    value = os.getenv("RELEASE_WRITER_TOKEN", "").strip()
    if not value:
        _fail("RELEASE_WRITER_TOKEN is required")
    return value


def _request(method: str, url: str, payload: dict[str, object] | None = None) -> dict[str, object]:
    body = None if payload is None else json.dumps(payload, separators=(",", ":")).encode()
    request = urllib.request.Request(
        url,
        data=body,
        method=method,
        headers={
            "Accept": "application/json",
            "Content-Type": "application/json",
            "X-Release-Writer-Token": _token(),
        },
    )
    try:
        with urllib.request.urlopen(request, timeout=20) as response:
            return json.loads(response.read().decode())
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode(errors="replace")
        _fail(f"release API returned HTTP {exc.code}: {detail[:1000]}")
    except urllib.error.URLError as exc:
        _fail(f"release API request failed: {exc.reason}")


def _github_request(url: str) -> object:
    headers = {
        "Accept": "application/vnd.github+json",
        "User-Agent": "ComicPile-release-writer",
        "X-GitHub-Api-Version": "2022-11-28",
    }
    token = os.getenv("GH_TOKEN", "").strip()
    if token:
        headers["Authorization"] = f"Bearer {token}"
    request = urllib.request.Request(url, headers=headers)
    try:
        with urllib.request.urlopen(request, timeout=20) as response:
            return json.loads(response.read().decode())
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode(errors="replace")
        _fail(f"GitHub API returned HTTP {exc.code}: {detail[:1000]}")
    except urllib.error.URLError as exc:
        _fail(f"GitHub API request failed: {exc.reason}")


def _parse_timestamp(value: object, name: str) -> str:
    if not isinstance(value, str):
        _fail(f"{name} must be an ISO-8601 string")
    try:
        datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        _fail(f"{name} must be a valid ISO-8601 timestamp")
    return value


def _validate_release(raw: str) -> dict[str, object]:
    try:
        payload = json.loads(raw)
    except json.JSONDecodeError as exc:
        _fail(f"invalid release JSON: {exc}")
    if not isinstance(payload, dict):
        _fail("release payload must be an object")
    missing = sorted(_REQUIRED - payload.keys())
    if missing:
        _fail(f"missing release fields: {', '.join(missing)}")
    if set(payload) - (_REQUIRED | {"body", "visibility", "status", "sort_order", "provenance_json"}):
        _fail("release payload contains unsupported fields")
    repository = payload["source_repository"]
    if not isinstance(repository, str) or not (1 <= len(repository) <= 255):
        _fail("source_repository must be 1..255 characters")
    pr_number = payload["source_pr_number"]
    if not isinstance(pr_number, int) or pr_number < 1:
        _fail("source_pr_number must be a positive integer")
    merge_sha = payload["source_merge_sha"]
    if not isinstance(merge_sha, str) or not (7 <= len(merge_sha) <= 64):
        _fail("source_merge_sha must be 7..64 characters")
    _parse_timestamp(payload["merged_at"], "merged_at")
    _parse_timestamp(payload["released_at"], "released_at")
    for name, maximum in (("category", 100), ("title", 255), ("summary", 1200)):
        value = payload[name]
        if not isinstance(value, str) or not value.strip() or len(value) > maximum:
            _fail(f"{name} must be non-empty and at most {maximum} characters")
    body = payload.get("body")
    if body is not None and (not isinstance(body, str) or len(body) > 6000):
        _fail("body must be null or at most 6000 characters")
    if payload.get("visibility", "public") not in _ALLOWED_VISIBILITY:
        _fail("unsupported visibility")
    if payload.get("status", "published") not in _ALLOWED_STATUS:
        _fail("unsupported status")
    provenance = payload.get("provenance_json", {})
    if not isinstance(provenance, dict):
        _fail("provenance_json must be an object")
    payload.setdefault("visibility", "public")
    payload.setdefault("status", "published")
    payload.setdefault("sort_order", 0)
    payload.setdefault("provenance_json", {})
    return payload


def _check(repository: str, pr_number: str, merge_sha: str) -> None:
    try:
        pr = int(pr_number)
    except ValueError:
        _fail("PR number must be an integer")
    query = urllib.parse.urlencode(
        {
            "source_repository": repository,
            "source_pr_number": pr,
            "source_merge_sha": merge_sha,
        }
    )
    result = _request("GET", f"{_api_base()}/source?{query}")
    print(json.dumps(result, separators=(",", ":")))


def _recent(repository: str, raw_limit: str) -> None:
    parts = repository.split("/")
    if len(parts) != 2 or not all(parts):
        _fail("repository must use owner/name form")
    try:
        limit = int(raw_limit)
    except ValueError:
        _fail("recent limit must be an integer")
    if not 1 <= limit <= 100:
        _fail("recent limit must be between 1 and 100")

    owner, name = (urllib.parse.quote(part, safe="") for part in parts)
    merged: list[dict[str, object]] = []
    page = 1
    while True:
        query = urllib.parse.urlencode(
            {
                "state": "closed",
                "base": "main",
                "per_page": 100,
                "page": page,
            }
        )
        result = _github_request(f"{_GITHUB_API_BASE}/repos/{owner}/{name}/pulls?{query}")
        if not isinstance(result, list):
            _fail("GitHub pulls response must be a list")
        for item in result:
            if not isinstance(item, dict):
                continue
            number = item.get("number")
            merged_at = item.get("merged_at")
            merge_sha = item.get("merge_commit_sha")
            title = item.get("title")
            if (
                isinstance(number, int)
                and isinstance(merged_at, str)
                and isinstance(merge_sha, str)
                and isinstance(title, str)
            ):
                merged.append(
                    {
                        "number": number,
                        "merged_at": merged_at,
                        "merge_commit_sha": merge_sha,
                        "title": title,
                    }
                )
        if len(result) < 100:
            break
        page += 1
        if page > 100:
            _fail("GitHub pull pagination exceeded safety bound")

    merged.sort(key=lambda item: str(item["merged_at"]), reverse=True)
    print(json.dumps(merged[:limit], separators=(",", ":")))


def _skip(raw: str) -> None:
    try:
        payload = json.loads(raw)
    except json.JSONDecodeError as exc:
        _fail(f"invalid skip JSON: {exc}")
    required = {"source_repository", "source_pr_number", "source_merge_sha", "merged_at", "reason"}
    if not isinstance(payload, dict) or required - payload.keys():
        _fail("skip payload is missing required fields")
    merged_at = _parse_timestamp(payload["merged_at"], "merged_at")
    reason = payload["reason"]
    if not isinstance(reason, str) or not reason.strip() or len(reason) > 500:
        _fail("skip reason must be non-empty and at most 500 characters")

    internal_release = _validate_release(
        json.dumps(
            {
                "source_repository": payload["source_repository"],
                "source_pr_number": payload["source_pr_number"],
                "source_merge_sha": payload["source_merge_sha"],
                "merged_at": merged_at,
                "released_at": merged_at,
                "category": "Internal",
                "title": f"Internal change (PR #{payload['source_pr_number']})",
                "summary": reason,
                "visibility": "internal",
                "status": "published",
                "sort_order": 0,
                "provenance_json": {"classification": "internal", "reason": reason},
            }
        )
    )
    result = _request("PUT", _api_base() + "/", internal_release)
    print(
        json.dumps(
            {"classification": "internal", "skipped": True, "recorded": True, "release": result},
            separators=(",", ":"),
        )
    )


def main() -> None:
    """Run the release-writer command-line interface."""
    if len(sys.argv) < 2:
        _fail("usage: release_writer.py check|recent|publish|skip ...")
    command = sys.argv[1]
    if command == "check" and len(sys.argv) == 5:
        _check(sys.argv[2], sys.argv[3], sys.argv[4])
        return
    if command == "recent" and len(sys.argv) == 4:
        _recent(sys.argv[2], sys.argv[3])
        return
    if command == "publish" and len(sys.argv) == 3:
        payload = _validate_release(sys.argv[2])
        result = _request("PUT", _api_base() + "/", payload)
        print(json.dumps({"published": True, "release": result}, separators=(",", ":")))
        return
    if command == "skip" and len(sys.argv) == 3:
        _skip(sys.argv[2])
        return
    _fail("invalid release_writer.py arguments")


if __name__ == "__main__":
    main()
