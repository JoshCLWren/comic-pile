"""GitHub Task Client for Ralph mode task management."""

import logging
import os
import time
from datetime import UTC, datetime
from typing import Any

from github import Github, GithubException, Issue
from github.Rate import Rate

logger = logging.getLogger(__name__)

GITHUB_TOKEN = os.getenv("GITHUB_TOKEN")
GITHUB_REPO = os.getenv("GITHUB_REPO", "anomalyco/comic-pile")

VALID_STATUSES = {"pending", "in-progress", "done", "blocked", "in-review"}
VALID_PRIORITIES = {"critical", "high", "medium", "low"}

STATUS_LABELS = {
    "pending": "ralph-status:pending",
    "in-progress": "ralph-status:in-progress",
    "done": "ralph-status:done",
    "blocked": "ralph-status:blocked",
    "in-review": "ralph-status:in-review",
}

PRIORITY_LABELS = {
    "critical": "ralph-priority:critical",
    "high": "ralph-priority:high",
    "medium": "ralph-priority:medium",
    "low": "ralph-priority:low",
}


class GitHubRateLimitError(Exception):
    """Raised when GitHub API rate limit is exceeded."""

    def __init__(self, rate_limit: Rate):
        """Initialize the error with rate limit details.

        Args:
            rate_limit: GitHub rate limit object
        """
        self.rate_limit = rate_limit
        reset_time = datetime.fromtimestamp(rate_limit.reset_timestamp, UTC)
        wait_time = (reset_time - datetime.now(UTC)).total_seconds()
        super().__init__(f"Rate limit exceeded. Reset at {reset_time}. Wait {wait_time:.0f}s")


class GitHubTaskClient:
    """Client for managing Ralph tasks via GitHub Issues API."""

    def __init__(self, token: str | None = None, repo: str | None = None) -> None:
        """Initialize the GitHub task client."""
        self.token = token or GITHUB_TOKEN
        self.repo_name = repo or GITHUB_REPO

        if not self.token:
            raise ValueError("GITHUB_TOKEN environment variable is required")

        self._github = None
        self._repo = None
        self._initialize_github()

    def _initialize_github(self) -> None:
        """Initialize GitHub client and repository."""
        self._github = Github(self.token)
        self._repo = self._github.get_repo(self.repo_name)
        logger.info(f"Connected to GitHub repository: {self.repo_name}")

    def _check_rate_limit(self) -> None:
        """Check GitHub API rate limit and raise error if exceeded."""
        rate_limit = self._github.get_rate_limit().core
        remaining = rate_limit.remaining
        reset_time = datetime.fromtimestamp(rate_limit.reset_timestamp, UTC)

        logger.debug(f"GitHub API rate limit: {remaining} remaining, resets at {reset_time}")

        if remaining == 0:
            raise GitHubRateLimitError(rate_limit)

    def _wait_for_rate_limit_reset(self, max_wait: int = 600) -> None:
        """Wait for GitHub API rate limit to reset.

        Args:
            max_wait: Maximum time to wait in seconds (default: 10 minutes)
        """
        try:
            rate_limit = self._github.get_rate_limit().core
            reset_time = datetime.fromtimestamp(rate_limit.reset_timestamp, UTC)
            now = datetime.now(UTC)
            wait_time = (reset_time - now).total_seconds()

            if wait_time <= 0:
                return

            if wait_time > max_wait:
                logger.warning(
                    f"Rate limit reset too far in the future ({wait_time:.0f}s), "
                    f"not waiting (max: {max_wait}s)"
                )
                return

            logger.info(f"Rate limit exceeded, waiting {wait_time:.0f}s for reset...")
            time.sleep(wait_time)
        except GithubException as e:
            logger.error(f"Error checking rate limit: {e}")

    def _get_ralph_tasks(self) -> list[Issue.Issue]:
        """Get all issues labeled as Ralph tasks.

        Returns:
            List of GitHub issues with ralph-task label
        """
        self._check_rate_limit()
        issues = self._repo.get_issues(labels=["ralph-task"], state="all")
        return list(issues)

    def _parse_issue_to_task(self, issue: Issue.Issue) -> dict[str, Any]:
        """Parse a GitHub issue into a task dictionary.

        Args:
            issue: GitHub issue object

        Returns:
            Task dictionary with standard fields
        """
        labels = {label.name for label in issue.labels}

        status = "pending"
        for status_label, label_name in STATUS_LABELS.items():
            if label_name in labels:
                status = status_label
                break

        priority = "medium"
        for priority_label, label_name in PRIORITY_LABELS.items():
            if label_name in labels:
                priority = priority_label
                break

        return {
            "id": issue.number,
            "title": issue.title,
            "description": issue.body or "",
            "status": status,
            "priority": priority,
            "task_type": self._extract_field_from_body(issue.body or "", "type", "feature"),
            "dependencies": self._extract_field_from_body(issue.body or "", "dependencies"),
            "blocked_reason": self._extract_field_from_body(issue.body or "", "blocked_reason"),
            "created_at": issue.created_at.isoformat(),
            "updated_at": issue.updated_at.isoformat(),
            "url": issue.html_url,
            "github_issue": issue,
        }

    def _extract_field_from_body(
        self, body: str, field: str, default: str | None = None
    ) -> str | None:
        """Extract a field value from issue body.

        Args:
            body: Issue body text
            field: Field name to extract
            default: Default value if field not found

        Returns:
            Field value or default
        """
        for line in body.split("\n"):
            if line.strip().startswith(f"**{field}:**"):
                return line.split(":", 1)[1].strip()
        return default

    def find_pending_task(self) -> dict[str, Any] | None:
        """Find the first pending Ralph task.

        Returns:
            Task dictionary or None if no pending tasks found
        """
        try:
            issues = self._get_ralph_tasks()

            for issue in issues:
                labels = {label.name for label in issue.labels}

                if STATUS_LABELS["pending"] in labels or STATUS_LABELS["in-progress"] in labels:
                    task = self._parse_issue_to_task(issue)

                    if task.get("dependencies"):
                        if not self._are_dependencies_resolved(task):
                            continue

                    return task

            return None
        except GithubException as e:
            if e.status == 403:
                logger.warning("Rate limit hit when finding pending task")
                self._wait_for_rate_limit_reset()
                return self.find_pending_task()
            raise

    def find_blocked_task(self) -> dict[str, Any] | None:
        """Find a blocked Ralph task that might be unblockable.

        Returns:
            Task dictionary or None if no blocked tasks found
        """
        try:
            issues = self._get_ralph_tasks()

            for issue in issues:
                labels = {label.name for label in issue.labels}

                if STATUS_LABELS["blocked"] in labels:
                    task = self._parse_issue_to_task(issue)
                    return task

            return None
        except GithubException as e:
            if e.status == 403:
                logger.warning("Rate limit hit when finding blocked task")
                self._wait_for_rate_limit_reset()
                return self.find_blocked_task()
            raise

    def update_status(
        self, task_id: int, status: str, comment: str | None = None
    ) -> dict[str, Any] | None:
        """Update the status of a Ralph task.

        Args:
            task_id: GitHub issue number
            status: New status (pending, in-progress, done, blocked, in-review)
            comment: Optional comment to add

        Returns:
            Updated task dictionary or None if task not found

        Raises:
            ValueError: If status is not valid
        """
        if status not in VALID_STATUSES:
            raise ValueError(f"Invalid status: {status}. Valid values: {VALID_STATUSES}")

        try:
            self._check_rate_limit()
            issue = self._repo.get_issue(task_id)

            labels = {label.name for label in issue.labels}

            for status_label in STATUS_LABELS.values():
                if status_label in labels:
                    issue.remove_from_labels(status_label)

            issue.add_to_labels(STATUS_LABELS[status])

            if comment:
                self.add_comment(task_id, comment)

            updated_issue = self._repo.get_issue(task_id)
            return self._parse_issue_to_task(updated_issue)
        except GithubException as e:
            if e.status == 404:
                logger.error(f"Task {task_id} not found")
                return None
            if e.status == 403:
                logger.warning(f"Rate limit hit when updating status for task {task_id}")
                self._wait_for_rate_limit_reset()
                return self.update_status(task_id, status, comment)
            raise

    def add_comment(self, task_id: int, comment: str) -> None:
        """Add a comment to a Ralph task.

        Args:
            task_id: GitHub issue number
            comment: Comment text to add
        """
        try:
            self._check_rate_limit()
            issue = self._repo.get_issue(task_id)
            issue.create_comment(comment)
            logger.info(f"Added comment to task {task_id}")
        except GithubException as e:
            if e.status == 404:
                logger.error(f"Task {task_id} not found")
                return
            if e.status == 403:
                logger.warning(f"Rate limit hit when adding comment to task {task_id}")
                self._wait_for_rate_limit_reset()
                self.add_comment(task_id, comment)
                return
            raise

    def create_task(
        self,
        title: str,
        description: str,
        priority: str = "medium",
        task_type: str = "feature",
        dependencies: str | None = None,
    ) -> dict[str, Any]:
        """Create a new Ralph task as a GitHub issue.

        Args:
            title: Task title
            description: Task description
            priority: Task priority (critical, high, medium, low)
            task_type: Task type (feature, bug, infrastructure, etc.)
            dependencies: Comma-separated list of task IDs

        Returns:
            Created task dictionary

        Raises:
            ValueError: If priority or task_type is not valid
        """
        if priority not in VALID_PRIORITIES:
            raise ValueError(f"Invalid priority: {priority}. Valid values: {VALID_PRIORITIES}")

        try:
            self._check_rate_limit()

            body = f"""## Description

{description}

## Metadata

**Type:** {task_type}
**Priority:** {priority}
**Dependencies:** {dependencies or "none"}
"""

            labels = ["ralph-task", STATUS_LABELS["pending"], PRIORITY_LABELS[priority]]

            issue = self._repo.create_issue(title=title, body=body, labels=labels)

            logger.info(f"Created task {issue.number}: {title}")
            return self._parse_issue_to_task(issue)
        except GithubException as e:
            if e.status == 403:
                logger.warning("Rate limit hit when creating task")
                self._wait_for_rate_limit_reset()
                return self.create_task(title, description, priority, task_type, dependencies)
            raise

    def get_task(self, task_id: int) -> dict[str, Any] | None:
        """Get a Ralph task by ID.

        Args:
            task_id: GitHub issue number

        Returns:
            Task dictionary or None if not found
        """
        try:
            self._check_rate_limit()
            issue = self._repo.get_issue(task_id)
            return self._parse_issue_to_task(issue)
        except GithubException as e:
            if e.status == 404:
                logger.error(f"Task {task_id} not found")
                return None
            if e.status == 403:
                logger.warning(f"Rate limit hit when getting task {task_id}")
                self._wait_for_rate_limit_reset()
                return self.get_task(task_id)
            raise

    def are_dependencies_resolved(self, task: dict[str, Any]) -> bool:
        """Check if all task dependencies are done.

        Args:
            task: Task dictionary

        Returns:
            True if all dependencies are done or no dependencies, False otherwise
        """
        dependencies = task.get("dependencies")
        if not dependencies or dependencies == "none":
            return True

        dep_ids = [dep.strip() for dep in dependencies.split(",") if dep.strip()]

        for dep_id in dep_ids:
            try:
                dep_task = self.get_task(int(dep_id))
                if not dep_task or dep_task["status"] != "done":
                    logger.debug(
                        f"Dependency {dep_id} not done (status: {dep_task['status'] if dep_task else 'not found'})"
                    )
                    return False
            except (ValueError, GithubException):
                logger.error(f"Error checking dependency {dep_id}")
                return False

        return True

    def _are_dependencies_resolved(self, task: dict[str, Any]) -> bool:
        """Internal alias for are_dependencies_resolved."""
        return self.are_dependencies_resolved(task)

    def create_labels_if_needed(self) -> None:
        """Create Ralph task labels in the GitHub repository if they don't exist."""
        all_labels = ["ralph-task"]
        all_labels.extend(STATUS_LABELS.values())
        all_labels.extend(PRIORITY_LABELS.values())

        existing_labels = {label.name for label in self._repo.get_labels()}

        for label_name in all_labels:
            if label_name not in existing_labels:
                color = self._get_label_color(label_name)
                try:
                    self._repo.create_label(name=label_name, color=color)
                    logger.info(f"Created label: {label_name}")
                except GithubException as e:
                    if e.status == 422:
                        logger.warning(f"Label {label_name} may already exist")
                    else:
                        raise

    def _get_label_color(self, label_name: str) -> str:
        """Get color for a label based on its type.

        Args:
            label_name: Label name

        Returns:
            6-character hex color code
        """
        if label_name == "ralph-task":
            return "7057ff"
        if label_name.startswith("ralph-status:"):
            colors = {
                "pending": "fef2c0",
                "in-progress": "84b6eb",
                "done": "006b75",
                "blocked": "d93f0b",
                "in-review": "e99695",
            }
            status = label_name.split(":")[1]
            return colors.get(status, "cccccc")
        if label_name.startswith("ralph-priority:"):
            colors = {
                "critical": "b60205",
                "high": "e11d21",
                "medium": "fbca04",
                "low": "414141",
            }
            priority = label_name.split(":")[1]
            return colors.get(priority, "cccccc")
        return "cccccc"
