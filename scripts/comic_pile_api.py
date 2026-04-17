#!/usr/bin/env python3
"""Shared API utilities for Comic Pile scripts.

This module provides common functions for interacting with the Comic Pile API:
- Authentication and token management
- Thread creation and migration
- Issue tracking and dependencies
- Reading order management and verification

Environment Variables:
    COMIC_PILE_API_BASE: API base URL (default: https://app-production-72b9.up.railway.app)
    COMIC_PILE_USERNAME: Your username (for individual scripts)
    COMIC_PILE_PASSWORD: Your password (for individual scripts)
"""

import os
from typing import NamedTuple, TypedDict

import requests

API_BASE = os.environ.get(
    "COMIC_PILE_API_BASE", "https://app-production-72b9.up.railway.app"
).rstrip("/")
REQUESTS_TIMEOUT = 30


class ThreadSpec(NamedTuple):
    """Specification for creating/updating a thread with issues to mark read."""

    title: str
    total_issues: int
    issues_to_mark_read: list[int]


class ThreadSpecWithLastRead(NamedTuple):
    """Specification for creating a thread with last_issue_read tracking."""

    title: str
    total_issues: int
    last_issue_read: int = 0


def login(username: str, password: str) -> str:
    """Authenticate and return bearer token.

    Args:
        username: Comic Pile username
        password: Comic Pile password

    Returns:
        Bearer token for API authentication
    """
    response = requests.post(
        f"{API_BASE}/api/auth/login",
        json={"username": username, "password": password},
        timeout=REQUESTS_TIMEOUT,
    )
    response.raise_for_status()
    return response.json()["access_token"]


def get_all_threads(token: str) -> dict[str, dict]:
    """Get all threads and return title -> thread mapping.

    Args:
        token: Auth token

    Returns:
        Dictionary mapping thread titles to thread info dicts
    """
    response = requests.get(
        f"{API_BASE}/api/threads/",
        headers={"Authorization": f"Bearer {token}"},
        timeout=REQUESTS_TIMEOUT,
    )
    response.raise_for_status()
    return {thread["title"]: thread for thread in response.json()}


def create_thread(token: str, title: str, issues_count: int, format: str = "Comics") -> int:
    """Create a thread and return its ID.

    Args:
        token: Auth token
        title: Thread title
        issues_count: Number of issues (for old system)
        format: Thread format (default: "Comics")

    Returns:
        Thread ID
    """
    response = requests.post(
        f"{API_BASE}/api/threads/",
        headers={"Authorization": f"Bearer {token}"},
        json={"title": title, "format": format, "issues_remaining": issues_count},
        timeout=REQUESTS_TIMEOUT,
    )
    response.raise_for_status()
    return response.json()["id"]


def migrate_thread(token: str, thread_id: int, last_issue_read: int, total_issues: int) -> None:
    """Migrate a thread to issue tracking.

    Args:
        token: Auth token
        thread_id: Thread ID
        last_issue_read: Number of issues already read
        total_issues: Total issues in the series
    """
    response = requests.post(
        f"{API_BASE}/api/threads/{thread_id}:migrateToIssues",
        headers={"Authorization": f"Bearer {token}"},
        json={"last_issue_read": last_issue_read, "total_issues": total_issues},
        timeout=REQUESTS_TIMEOUT,
    )
    response.raise_for_status()


def mark_issue_read(token: str, thread_id: int, issue_number: str) -> bool:
    """Mark an issue as read.

    Args:
        token: Auth token
        thread_id: Thread ID
        issue_number: Issue number to mark as read

    Returns:
        True if successful, False if already read or issue not found
    """
    page_token = ""
    issue_id = None

    while True:
        url = f"{API_BASE}/api/v1/threads/{thread_id}/issues"
        params = {}
        if page_token:
            params["page_token"] = page_token

        response = requests.get(
            url,
            headers={"Authorization": f"Bearer {token}"},
            params=params,
            timeout=REQUESTS_TIMEOUT,
        )
        response.raise_for_status()
        data = response.json()

        for issue in data.get("issues", []):
            if issue["issue_number"] == issue_number:
                issue_id = issue["id"]
                if issue.get("status") == "read":
                    return False
                break

        if issue_id:
            break

        page_token = data.get("next_page_token")
        if not page_token:
            break

    if not issue_id:
        print(f"  ⚠️  Could not find issue #{issue_number}")
        return False

    try:
        response = requests.post(
            f"{API_BASE}/api/v1/issues/{issue_id}:markRead",
            headers={"Authorization": f"Bearer {token}"},
            timeout=REQUESTS_TIMEOUT,
        )
        response.raise_for_status()
        return True
    except requests.HTTPError as e:
        if e.response is not None and e.response.status_code == 409:
            return False
        raise


def get_thread_issues(token: str, thread_id: int) -> dict[str, int]:
    """Get issue_number -> issue_id mapping for a thread.

    Args:
        token: Auth token
        thread_id: Thread ID

    Returns:
        Dictionary mapping issue numbers to issue IDs
    """
    page_token = ""
    issues = {}

    while True:
        url = f"{API_BASE}/api/v1/threads/{thread_id}/issues"
        params = {}
        if page_token:
            params["page_token"] = page_token

        response = requests.get(
            url,
            headers={"Authorization": f"Bearer {token}"},
            params=params,
            timeout=REQUESTS_TIMEOUT,
        )
        response.raise_for_status()
        data = response.json()

        for issue in data.get("issues", []):
            issues[issue["issue_number"]] = issue["id"]

        page_token = data.get("next_page_token")
        if not page_token:
            break

    return issues


def create_dependency(token: str, source_issue_id: int, target_issue_id: int) -> bool:
    """Create an issue-level dependency.

    Args:
        token: Auth token
        source_issue_id: Source issue ID
        target_issue_id: Target issue ID

    Returns:
        True if created, False if already exists or circular
    """
    response = requests.post(
        f"{API_BASE}/api/v1/dependencies/",
        headers={"Authorization": f"Bearer {token}"},
        json={
            "source_type": "issue",
            "source_id": source_issue_id,
            "target_type": "issue",
            "target_id": target_issue_id,
        },
        timeout=REQUESTS_TIMEOUT,
    )

    if response.status_code == 201:
        return True
    elif response.status_code == 400:
        error = response.json()
        detail = error.get("detail", "")
        if "already exists" in detail.lower() or "circular" in detail.lower():
            return False
        print(f"  ❌ Bad Request: {error}")
        return False
    else:
        print(f"  ❌ Server error {response.status_code}: {response.text}")
        return False


class DepEdge(NamedTuple):
    """Human-readable representation of a dependency edge."""

    source_title: str
    source_issue: str
    target_title: str
    target_issue: str


class VerificationResult(TypedDict):
    """Result of verifying reading order chains against actual dependencies."""

    present: list[DepEdge]
    missing: list[DepEdge]
    unexpected: list[DepEdge]
    not_found: list[DepEdge]


def verify_reading_order(
    spec_chains: list[list[tuple[str, str]]],
    token: str,
    base_url: str = API_BASE,
) -> VerificationResult:
    """Verify that expected reading order dependencies exist in the database.

    Compares the dependency edges implied by consecutive pairs in each chain
    against the actual dependencies stored in the API.

    Args:
        spec_chains: List of chains, where each chain is a list of
            (title, issue_number) tuples defining expected reading order.
        token: Auth token.
        base_url: API base URL (defaults to module-level API_BASE).

    Returns:
        Dictionary with four lists of DepEdge tuples:
        - present: edges that exist as expected
        - missing: edges that should exist but don't
        - unexpected: edges that exist but aren't in the spec
        - not_found: edges referencing issue numbers not present in the database

    Raises:
        ValueError: If a thread title in a chain doesn't exist in the database.
    """
    all_titles: set[str] = set()
    for chain in spec_chains:
        for title, _ in chain:
            all_titles.add(title)

    all_threads = get_all_threads(token)
    title_to_thread_id: dict[str, int] = {}
    for title in all_titles:
        if title not in all_threads:
            raise ValueError(f"Thread not found: {title}")
        title_to_thread_id[title] = all_threads[title]["id"]

    title_to_issues: dict[str, dict[str, int]] = {}
    issue_id_to_label: dict[int, tuple[str, str]] = {}
    for title in all_titles:
        issues = get_thread_issues(token, title_to_thread_id[title])
        title_to_issues[title] = issues
        for issue_number, issue_id in issues.items():
            issue_id_to_label[issue_id] = (title, issue_number)

    expected_edges: dict[DepEdge, tuple[int, int]] = {}
    not_found_edges: list[DepEdge] = []
    for chain in spec_chains:
        for i in range(len(chain) - 1):
            src_title, src_issue = chain[i]
            tgt_title, tgt_issue = chain[i + 1]
            edge = DepEdge(src_title, src_issue, tgt_title, tgt_issue)
            src_id = title_to_issues[src_title].get(src_issue)
            tgt_id = title_to_issues[tgt_title].get(tgt_issue)
            if src_id is None or tgt_id is None:
                not_found_edges.append(edge)
            else:
                expected_edges[edge] = (src_id, tgt_id)

    actual_edge_ids: set[tuple[int, int]] = set()
    seen_thread_ids: set[int] = set()
    for thread_id in title_to_thread_id.values():
        if thread_id in seen_thread_ids:
            continue
        seen_thread_ids.add(thread_id)
        response = requests.get(
            f"{base_url}/api/v1/threads/{thread_id}/dependencies",
            headers={"Authorization": f"Bearer {token}"},
            timeout=REQUESTS_TIMEOUT,
        )
        response.raise_for_status()
        data = response.json()
        for dep in data.get("blocking", []) + data.get("blocked_by", []):
            src_id = dep.get("source_issue_id")
            tgt_id = dep.get("target_issue_id")
            if src_id is not None and tgt_id is not None:
                actual_edge_ids.add((src_id, tgt_id))

    expected_ids = set(expected_edges.values())
    present_ids = expected_ids & actual_edge_ids
    missing_ids = expected_ids - actual_edge_ids

    our_issue_ids: set[int] = set()
    for issues in title_to_issues.values():
        for issue_id in issues.values():
            our_issue_ids.add(issue_id)
    unexpected_ids = {
        (s, t)
        for s, t in actual_edge_ids - expected_ids
        if s in our_issue_ids and t in our_issue_ids
    }

    present = sorted([edge for edge, ids in expected_edges.items() if ids in present_ids])
    missing = sorted([edge for edge, ids in expected_edges.items() if ids in missing_ids])
    unexpected = sorted(
        DepEdge(
            issue_id_to_label[s][0],
            issue_id_to_label[s][1],
            issue_id_to_label[t][0],
            issue_id_to_label[t][1],
        )
        for s, t in unexpected_ids
        if s in issue_id_to_label and t in issue_id_to_label
    )

    return {
        "present": present,
        "missing": missing,
        "unexpected": unexpected,
        "not_found": sorted(not_found_edges),
    }
