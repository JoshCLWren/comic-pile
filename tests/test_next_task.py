"""Tests for GitHub issue selection."""

from scripts.next_task import select_next


def _issue(number: int, title: str, labels: list[str], body: str = "") -> dict:
    """Build the subset of GitHub issue data used by the selector."""
    return {
        "number": number,
        "title": title,
        "body": body,
        "labels": [{"name": label} for label in labels],
        "url": f"https://github.com/example/repo/issues/{number}",
    }


def test_select_next_prefers_highest_priority_pending_issue() -> None:
    """The selector should choose high priority work before medium work."""
    issues = [
        _issue(20, "Medium", ["ralph-task", "ralph-status:pending", "ralph-priority:medium"]),
        _issue(10, "High", ["ralph-task", "ralph-status:pending", "ralph-priority:high"]),
    ]

    candidate = select_next(issues, set())

    assert candidate is not None
    assert candidate.issue["number"] == 10


def test_select_next_ignores_non_pending_and_epic_issues() -> None:
    """Only executable pending tasks should be selected."""
    issues = [
        _issue(1, "Epic", ["epic", "ralph-status:pending", "ralph-priority:critical"]),
        _issue(2, "Active", ["ralph-task", "ralph-status:in-progress", "ralph-priority:high"]),
        _issue(3, "Ready", ["ralph-task", "ralph-status:pending", "ralph-priority:low"]),
    ]

    candidate = select_next(issues, set())

    assert candidate is not None
    assert candidate.issue["number"] == 3


def test_select_next_skips_issue_with_open_dependency() -> None:
    """An issue should wait until its referenced dependency is closed."""
    issues = [
        _issue(
            20,
            "Blocked task",
            ["ralph-task", "ralph-status:pending", "ralph-priority:critical"],
            "Depends on #19",
        ),
        _issue(21, "Ready task", ["ralph-task", "ralph-status:pending", "ralph-priority:high"]),
    ]

    candidate = select_next(issues, set())

    assert candidate is not None
    assert candidate.issue["number"] == 21


def test_select_next_allows_closed_dependency() -> None:
    """A pending issue becomes eligible when its dependency is closed."""
    issue = _issue(
        20,
        "Unblocked task",
        ["ralph-task", "ralph-status:pending", "ralph-priority:high"],
        "Depends on #19",
    )

    candidate = select_next([issue], {19})

    assert candidate is not None
    assert candidate.issue["number"] == 20
