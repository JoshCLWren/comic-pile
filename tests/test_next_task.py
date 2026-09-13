"""Tests for GitHub issue selection."""

from unittest.mock import Mock

import pytest

import scripts.next_task as next_task
from scripts.next_task import _issue_context, select_next


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


def test_select_next_ignores_non_pending_and_parent_issues() -> None:
    """Only executable pending child tasks should be selected."""
    issues = [
        _issue(1, "Epic", ["epic", "ralph-status:pending", "ralph-priority:critical"]),
        _issue(2, "PRD", ["prd", "ralph-status:pending", "ralph-priority:critical"]),
        _issue(3, "Active", ["ralph-task", "ralph-status:in-progress", "ralph-priority:high"]),
        _issue(4, "Ready", ["ralph-task", "ralph-status:pending", "ralph-priority:low"]),
    ]

    candidate = select_next(issues, set())

    assert candidate is not None
    assert candidate.issue["number"] == 4


def test_select_next_ignores_manual_only_issue() -> None:
    """A manual-only issue must never enter autonomous selection."""
    issues = [
        _issue(
            10,
            "Production acceptance gate",
            ["ralph-task", "ralph-status:pending", "ralph-priority:critical"],
            "<!-- factory-execution:manual-only -->\nHuman-controlled gate.",
        ),
        _issue(20, "Ready task", ["ralph-task", "ralph-status:pending", "ralph-priority:low"]),
    ]

    candidate = select_next(issues, set())

    assert candidate is not None
    assert candidate.issue["number"] == 20


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


def test_issue_context_reports_scope_dependencies_and_files() -> None:
    """The selector output should provide enough bounded context to begin work."""
    issue = _issue(
        42,
        "Document workflow",
        ["ralph-task", "ralph-status:pending", "ralph-priority:high"],
        """## Goal

Make agents productive.

Depends on #41.

Update `scripts/next_task.py` and `docs/ISSUE_EXECUTION_PROTOCOL.md`.
""",
    )

    context = _issue_context(issue, {41})

    assert "Make agents productive." in context
    assert "Dependencies: #41 (closed)" in context
    assert "scripts/next_task.py" in context
    assert "Required verification:" in context


def test_start_task_updates_label_and_posts_comment(monkeypatch: pytest.MonkeyPatch) -> None:
    """A valid task should update its label and post the start comment."""
    monkeypatch.setattr(
        next_task,
        "_gh_issue",
        lambda issue_number: _issue(
            issue_number,
            "Ready task",
            ["ralph-task", "ralph-status:pending", "ralph-priority:high"],
        ),
    )
    monkeypatch.setattr(next_task, "_gh_issue_list", lambda state: [])
    gh_runner = Mock(return_value="")
    monkeypatch.setattr(next_task, "_run_gh", gh_runner)

    assert next_task._start_task(42) == 0

    assert gh_runner.call_count == 2
    assert gh_runner.call_args_list[0].args[0][1:3] == ["issue", "edit"]
    assert gh_runner.call_args_list[1].args[0][1:3] == ["issue", "comment"]


def test_start_task_rejects_non_pending_issue(monkeypatch: pytest.MonkeyPatch) -> None:
    """A task that is not pending must not trigger GitHub writes."""
    monkeypatch.setattr(
        next_task,
        "_gh_issue",
        lambda issue_number: _issue(
            issue_number,
            "Active task",
            ["ralph-task", "ralph-status:in-progress", "ralph-priority:high"],
        ),
    )
    gh_runner = Mock()
    monkeypatch.setattr(next_task, "_run_gh", gh_runner)

    with pytest.raises(RuntimeError, match="is not pending"):
        next_task._start_task(42)

    gh_runner.assert_not_called()


def test_start_task_rejects_parent_issue(monkeypatch: pytest.MonkeyPatch) -> None:
    """Explicit start cannot bypass the parent-selection fence."""
    monkeypatch.setattr(
        next_task,
        "_gh_issue",
        lambda issue_number: _issue(
            issue_number,
            "Parent epic",
            ["ralph-task", "ralph-status:pending", "ralph-priority:high", "epic"],
        ),
    )
    gh_runner = Mock()
    monkeypatch.setattr(next_task, "_run_gh", gh_runner)

    with pytest.raises(RuntimeError, match="parent PRD/epic"):
        next_task._start_task(42)

    gh_runner.assert_not_called()


def test_start_task_rejects_manual_only_issue(monkeypatch: pytest.MonkeyPatch) -> None:
    """Explicit start cannot bypass the manual-only marker."""
    monkeypatch.setattr(
        next_task,
        "_gh_issue",
        lambda issue_number: _issue(
            issue_number,
            "Human gate",
            ["ralph-task", "ralph-status:pending", "ralph-priority:high"],
            "<!-- factory-execution:manual-only -->",
        ),
    )
    gh_runner = Mock()
    monkeypatch.setattr(next_task, "_run_gh", gh_runner)

    with pytest.raises(RuntimeError, match="manual-only"):
        next_task._start_task(42)

    gh_runner.assert_not_called()


def test_start_task_rejects_unresolved_dependency(monkeypatch: pytest.MonkeyPatch) -> None:
    """A task with an open dependency must not update its status."""
    monkeypatch.setattr(
        next_task,
        "_gh_issue",
        lambda issue_number: _issue(
            issue_number,
            "Blocked task",
            ["ralph-task", "ralph-status:pending", "ralph-priority:high"],
            "Depends on #41",
        ),
    )
    monkeypatch.setattr(next_task, "_gh_issue_list", lambda state: [])
    gh_runner = Mock()
    monkeypatch.setattr(next_task, "_run_gh", gh_runner)

    with pytest.raises(RuntimeError, match="unresolved dependency"):
        next_task._start_task(42)

    gh_runner.assert_not_called()


def test_start_task_succeeds_when_comment_fails(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """A completed label transition remains successful if commenting fails."""
    monkeypatch.setattr(
        next_task,
        "_gh_issue",
        lambda issue_number: _issue(
            issue_number,
            "Ready task",
            ["ralph-task", "ralph-status:pending", "ralph-priority:high"],
        ),
    )
    monkeypatch.setattr(next_task, "_gh_issue_list", lambda state: [])

    gh_runner = Mock()

    def run_github(command: list[str], failure_message: str) -> str:
        if command[1:3] == ["issue", "comment"]:
            raise RuntimeError("temporary GitHub outage")
        return ""

    gh_runner.side_effect = run_github
    monkeypatch.setattr(next_task, "_run_gh", gh_runner)

    assert next_task._start_task(42) == 0

    assert gh_runner.call_count == 2
    assert "label updated, but comment failed" in capsys.readouterr().err
