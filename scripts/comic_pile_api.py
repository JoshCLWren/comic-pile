#!/usr/bin/env python3
"""Shared API utilities for Comic Pile scripts.

This module provides common functions for interacting with the Comic Pile API:
- Authentication and token management
- Thread creation and migration
- Issue tracking and dependencies
- Reading order management

Environment Variables:
    COMIC_PILE_API_BASE: API base URL (default: https://app-production-72b9.up.railway.app)
    COMIC_PILE_USERNAME: Your username (for individual scripts)
    COMIC_PILE_PASSWORD: Your password (for individual scripts)
"""

import os
from typing import NamedTuple

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
