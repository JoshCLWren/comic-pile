#!/usr/bin/env python3
"""Select the next executable GitHub issue for an agent."""

from __future__ import annotations

import json
import re
import subprocess
import sys
from dataclasses import dataclass
from typing import TypedDict


class IssueLabel(TypedDict):
    """GitHub issue label payload."""

    name: str


class IssuePayload(TypedDict):
    """Subset of GitHub issue data used by the selector."""

    number: int
    title: str
    body: str
    labels: list[IssueLabel]
    url: str


@dataclass(frozen=True)
class Candidate:
    """An eligible issue and its selection metadata."""

    issue: IssuePayload
    priority: int


PRIORITY_RANKS = {
    "ralph-priority:critical": 0,
    "ralph-priority:high": 1,
    "ralph-priority:medium": 2,
    "ralph-priority:low": 3,
}
EXCLUDED_LABELS = {
    "duplicate",
    "epic",
    "ralph-status:blocked",
    "ralph-status:done",
    "ralph-status:in-progress",
    "ralph-status:in-review",
}


def _labels(issue: IssuePayload) -> set[str]:
    """Return the issue's label names."""
    return {label["name"] for label in issue["labels"]}


def _priority(issue: IssuePayload) -> int:
    """Return the explicit priority rank, placing unprioritized issues last."""
    return min((PRIORITY_RANKS.get(label, 99) for label in _labels(issue)), default=99)


def _has_unresolved_dependency(issue: IssuePayload, closed_numbers: set[int]) -> bool:
    """Return whether a referenced issue number is not known to be closed."""
    body = issue.get("body") or ""
    references = {
        int(number)
        for number in re.findall(r"(?:Depends on|depends on) #([0-9]+)", body)
    }
    return bool(references - closed_numbers)


def select_next(issues: list[IssuePayload], closed_numbers: set[int]) -> Candidate | None:
    """Select the highest-priority pending issue without unresolved dependencies."""
    candidates: list[Candidate] = []
    for issue in issues:
        labels = _labels(issue)
        if "ralph-status:pending" not in labels or labels & EXCLUDED_LABELS:
            continue
        if _has_unresolved_dependency(issue, closed_numbers):
            continue
        candidates.append(Candidate(issue=issue, priority=_priority(issue)))

    return min(candidates, key=lambda item: (item.priority, item.issue["number"])) if candidates else None


def _gh_issue_list(state: str) -> list[IssuePayload]:
    """Load issues from GitHub using the gh CLI."""
    command = [
        "gh",
        "issue",
        "list",
        "--state",
        state,
        "--limit",
        "200",
        "--json",
        "number,title,body,labels,url",
    ]
    try:
        result = subprocess.run(command, check=True, capture_output=True, text=True)
    except FileNotFoundError as error:
        raise RuntimeError("gh CLI is required; install it and authenticate first") from error
    except subprocess.CalledProcessError as error:
        detail = error.stderr.strip() or "GitHub issue query failed"
        raise RuntimeError(detail) from error
    return json.loads(result.stdout)


def main() -> int:
    """Print the next issue in an agent-readable format."""
    try:
        open_issues = _gh_issue_list("open")
        closed_issues = _gh_issue_list("closed")
    except (RuntimeError, json.JSONDecodeError) as error:
        print(f"next-task: {error}", file=sys.stderr)
        return 1

    closed_numbers = {issue["number"] for issue in closed_issues}
    candidate = select_next(open_issues, closed_numbers)
    if candidate is None:
        print("No eligible pending GitHub issue found.")
        return 0

    issue = candidate.issue
    labels = ", ".join(sorted(_labels(issue)))
    print(f"Next issue: #{issue['number']} — {issue['title']}")
    print(f"URL: {issue['url']}")
    print(f"Priority rank: {candidate.priority}")
    print(f"Labels: {labels}")
    print()
    print("Agent instruction:")
    print(f"Read AGENTS.md, docs/ISSUE_EXECUTION_PROTOCOL.md, and issue #{issue['number']}.")
    print("If the issue has a linked local plan, read that plan before editing.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
