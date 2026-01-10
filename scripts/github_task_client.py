"""GitHub Task Client for Ralph mode task management.

Uses gh CLI commands exclusively for all GitHub operations.
"""

import json
import logging
import os
import subprocess
from typing import TYPE_CHECKING

logger = logging.getLogger(__name__)

if TYPE_CHECKING:
    pass


TaskDict = dict[str, object]


GITHUB_REPO = os.getenv("GITHUB_REPO", "JoshCLWren/comic-pile")

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
    """Raised when gh CLI rate limit is exceeded."""


class GitHubTaskClient:
    """Client for managing Ralph tasks via gh CLI."""

    def __init__(self, repo: str | None = None) -> None:
        """Initialize GitHub task client using gh CLI."""
        self.repo_name = repo or GITHUB_REPO
        logger.info("Using gh CLI for GitHub operations")
        logger.info(f"Target repository: {self.repo_name}")
        self._verify_gh_cli()

    def _verify_gh_cli(self) -> None:
        """Verify gh CLI is installed and authenticated."""
        try:
            result = subprocess.run(
                ["gh", "auth", "status"],
                capture_output=True,
                text=True,
                timeout=10,
                check=False,
            )
            if result.returncode != 0:
                raise ValueError("gh CLI not authenticated. Run: gh auth login")
            if result.returncode != 0:
                raise ValueError("gh CLI not authenticated. Run: gh auth login")
            logger.info("gh CLI authenticated and ready")
        except FileNotFoundError as e:
            raise ValueError("gh CLI not found. Install from: https://cli.github.com/") from e
        except subprocess.TimeoutExpired as e:
            raise ValueError("gh CLI timeout during authentication check") from e

    def _run_gh_command(
        self, args: list[str], capture: bool = True, check: bool = True
    ) -> subprocess.CompletedProcess[str]:
        """Run a gh CLI command.

        Args:
            args: Command arguments (excluding 'gh')
            capture: Whether to capture stdout/stderr
            check: Whether to raise on non-zero exit code

        Returns:
            CompletedProcess result
        """
        cmd = ["gh"] + args
        logger.debug(f"Running: {' '.join(cmd)}")

        try:
            result = subprocess.run(
                cmd,
                capture_output=capture,
                text=True,
                check=check,
                timeout=60,
            )
            return result
        except subprocess.TimeoutExpired:
            logger.error(f"gh CLI timeout: {cmd}")
            raise
        except subprocess.CalledProcessError as e:
            logger.error(f"gh CLI error: {e}")
            raise

    def _get_ralph_tasks(self) -> list[TaskDict]:
        """Get all issues labeled as Ralph tasks.

        Returns:
            List of task dictionaries with ralph-task label
        """
        result = self._run_gh_command(
            [
                "issue",
                "list",
                "--repo",
                self.repo_name,
                "--label",
                "ralph-task",
                "--state",
                "all",
                "--json",
                "number,title,body,labels,createdAt,updatedAt,url",
            ]
        )
        issues = json.loads(result.stdout)
        return [self._parse_issue_to_task(issue) for issue in issues]

    def _parse_issue_to_task(self, issue: dict) -> TaskDict:
        """Parse a GitHub issue JSON into a task dictionary.

        Args:
            issue: GitHub issue object from gh CLI JSON output

        Returns:
            Task dictionary with standard fields
        """
        labels = {label["name"] for label in issue.get("labels", [])}

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

        body = issue.get("body", "")

        return {
            "id": issue["number"],
            "title": issue["title"],
            "description": body,
            "status": status,
            "priority": priority,
            "task_type": self._extract_field_from_body(body, "type", "feature"),
            "dependencies": self._extract_field_from_body(body, "dependencies"),
            "blocked_reason": self._extract_field_from_body(body, "blocked_reason"),
            "created_at": issue.get("createdAt", ""),
            "updated_at": issue.get("updatedAt", ""),
            "url": issue.get("url", ""),
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
        field_pattern = f"**{field}:**"
        for line in body.split("\n"):
            if field_pattern.lower() in line.lower():
                idx = line.lower().find(field_pattern.lower())
                value = line[idx + len(field_pattern) :].strip()
                return value
        return default

    def find_pending_task(self) -> TaskDict | None:
        """Find the first pending Ralph task.

        Returns:
            Task dictionary or None if no pending tasks found
        """
        tasks = self._get_ralph_tasks()

        for task in tasks:
            status = task.get("status", "pending")

            if status in ("pending", "in-progress"):
                if task.get("dependencies"):
                    if not self.are_dependencies_resolved(task):
                        continue

                return task

        return None

    def find_blocked_task(self) -> TaskDict | None:
        """Find a blocked Ralph task that might be unblockable.

        Returns:
            Task dictionary or None if no blocked tasks found
        """
        tasks = self._get_ralph_tasks()

        for task in tasks:
            if task.get("status") == "blocked":
                return task

        return None

    def find_in_review_task(self) -> TaskDict | None:
        """Find a task in review status.

        Returns:
            Task dictionary or None if no in-review tasks found
        """
        tasks = self._get_ralph_tasks()

        for task in tasks:
            if task.get("status") == "in-review":
                return task

        return None

    def update_status(
        self, task_id: int, status: str, comment: str | None = None
    ) -> TaskDict | None:
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

        result = self._run_gh_command(
            [
                "issue",
                "view",
                str(task_id),
                "--repo",
                self.repo_name,
                "--json",
                "labels",
            ]
        )

        issue_data = json.loads(result.stdout)
        current_labels = {label["name"] for label in issue_data.get("labels", [])}

        args = [
            "issue",
            "edit",
            str(task_id),
            "--repo",
            self.repo_name,
        ]

        for status_label in STATUS_LABELS.values():
            if status_label in current_labels:
                args.extend(["--remove-label", status_label])

        args.extend(["--add-label", STATUS_LABELS[status]])

        self._run_gh_command(args, check=False)

        if comment:
            self.add_comment(task_id, comment)

        return self.get_task(task_id)

    def add_comment(self, task_id: int, comment: str) -> None:
        """Add a comment to a Ralph task.

        Args:
            task_id: GitHub issue number
            comment: Comment text to add
        """
        self._run_gh_command(
            ["issue", "comment", str(task_id), "--body", comment],
            check=False,
        )
        logger.info(f"Added comment to task {task_id}")

    def create_task(
        self,
        title: str,
        description: str,
        priority: str = "medium",
        task_type: str = "feature",
        dependencies: str | None = None,
    ) -> TaskDict:
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

        body = f"""## Description

{description}

## Metadata

**Type:** {task_type}
**Priority:** {priority}
**Dependencies:** {dependencies or "none"}
"""

        labels = ["ralph-task", STATUS_LABELS["pending"], PRIORITY_LABELS[priority]]

        result = self._run_gh_command(
            [
                "issue",
                "create",
                "--repo",
                self.repo_name,
                "--title",
                title,
                "--body",
                body,
                *[arg for label in labels for arg in ("--label", label)],
            ]
        )

        issue_url = result.stdout.strip()
        task_id = int(issue_url.split("/")[-1])

        logger.info(f"Created task {task_id}: {title}")
        task = self.get_task(task_id)
        if task is None:
            raise RuntimeError(f"Failed to retrieve created task {task_id}")
        return task

    def get_task(self, task_id: int) -> TaskDict | None:
        """Get a Ralph task by ID.

        Args:
            task_id: GitHub issue number

        Returns:
            Task dictionary or None if not found
        """
        try:
            result = self._run_gh_command(
                [
                    "issue",
                    "view",
                    str(task_id),
                    "--repo",
                    self.repo_name,
                    "--json",
                    "number,title,body,labels,createdAt,updatedAt,url",
                ]
            )
            issue = json.loads(result.stdout)
            return self._parse_issue_to_task(issue)
        except subprocess.CalledProcessError:
            logger.error(f"Task {task_id} not found")
            return None

    def are_dependencies_resolved(self, task: TaskDict) -> bool:
        """Check if all task dependencies are done.

        Args:
            task: Task dictionary

        Returns:
            True if all dependencies are done or no dependencies, False otherwise
        """
        dependencies = task.get("dependencies")
        if dependencies is None or dependencies == "none":
            return True

        dep_ids = [dep.strip() for dep in str(dependencies).split(",") if dep.strip()]

        for dep_id in dep_ids:
            try:
                dep_task = self.get_task(int(dep_id))
                if not dep_task or dep_task.get("status") != "done":
                    status_str = dep_task.get("status") if dep_task else "not found"
                    logger.debug(f"Dependency {dep_id} not done (status: {status_str})")
                    return False
            except (ValueError, subprocess.CalledProcessError):
                logger.error(f"Error checking dependency {dep_id}")
                return False

        return True

    def _are_dependencies_resolved(self, task: TaskDict) -> bool:
        """Internal alias for are_dependencies_resolved."""
        return self.are_dependencies_resolved(task)

    def create_labels_if_needed(self) -> None:
        """Create Ralph task labels in the GitHub repository if they don't exist."""
        all_labels = ["ralph-task"]
        all_labels.extend(STATUS_LABELS.values())
        all_labels.extend(PRIORITY_LABELS.values())
        all_labels.append("qc-issue")

        result = self._run_gh_command(["label", "list", "--repo", self.repo_name, "--json", "name"])
        existing_labels = {label["name"] for label in json.loads(result.stdout)}

        for label_name in all_labels:
            if label_name not in existing_labels:
                color = self._get_label_color(label_name)
                try:
                    self._run_gh_command(
                        ["label", "create", label_name, "--color", color, "--repo", self.repo_name],
                        check=False,
                    )
                    logger.info(f"Created label: {label_name}")
                except subprocess.CalledProcessError:
                    logger.warning(f"Label {label_name} may already exist")

    def _get_label_color(self, label_name: str) -> str:
        """Get color for a label based on its type.

        Args:
            label_name: Label name

        Returns:
            6-character hex color code
        """
        if label_name == "ralph-task":
            return "7057ff"
        if label_name == "qc-issue":
            return "d93f0b"
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
