#!/usr/bin/env python3
"""Migrate active tasks from tasks.json to GitHub Issues.

Only migrates in_progress and in_review tasks.
Does not migrate done, pending, or blocked tasks.
"""

import json
import os
import subprocess
from pathlib import Path


def load_tasks() -> list[dict]:
    """Load tasks from tasks.json."""
    tasks_file = Path(__file__).parent.parent / "tasks.json"
    with open(tasks_file) as f:
        data = json.load(f)
    return data.get("tasks", [])


def get_active_tasks(tasks: list[dict]) -> list[dict]:
    """Filter tasks that need migration."""
    active_statuses = {"in_progress", "in_review"}
    return [t for t in tasks if t.get("status") in active_statuses]


def priority_to_github(priority: str) -> str:
    """Convert task priority to GitHub label."""
    mapping = {
        "HIGH": "ralph-priority:high",
        "MEDIUM": "ralph-priority:medium",
        "LOW": "ralph-priority:low",
        "CRITICAL": "ralph-priority:critical",
    }
    return mapping.get(priority, "ralph-priority:medium")


def status_to_github(status: str) -> str:
    """Convert task status to GitHub label."""
    mapping = {
        "in_progress": "ralph-status:in-progress",
        "in_review": "ralph-status:in-review",
    }
    return mapping.get(status, "ralph-status:pending")


def create_github_issue(task: dict, dry_run: bool = False) -> str | None:
    """Create GitHub issue for a task.

    Returns issue URL if successful, None otherwise.
    """
    title = f"{task.get('task_id', 'NO-ID')}: {task.get('title', 'No title')}"
    priority_label = priority_to_github(task.get("priority", "MEDIUM"))
    status_label = status_to_github(task.get("status", "pending"))

    labels = ["ralph-task", priority_label, status_label]

    # Build issue body
    body_parts = [
        f"**Task ID:** `{task.get('task_id', 'N/A')}`",
        f"**Priority:** {task.get('priority', 'MEDIUM')}",
        f"**Status:** {task.get('status', 'pending')}",
        "",
        f"**Description:**\n{task.get('description', 'No description')}",
        "",
        f"**Instructions:**\n{task.get('instructions', 'No instructions')}",
        "",
        f"**Estimated Effort:** {task.get('estimated_effort', 'Unknown')}",
    ]

    if task.get("dependencies"):
        body_parts.append(f"**Dependencies:** {task.get('dependencies')}")

    body = "\n".join(body_parts)

    if dry_run:
        print("[DRY RUN] Would create issue:")
        print(f"  Title: {title}")
        print(f"  Labels: {', '.join(labels)}")
        print()
        return None

    # Create issue using gh CLI
    cmd = [
        "gh",
        "issue",
        "create",
        "--title",
        title,
        "--body",
        body,
        "--repo",
        os.getenv("GITHUB_REPO", "JoshCLWren/comic-pile"),
    ]
    for label in labels:
        cmd.extend(["--label", label])

    try:
        result = subprocess.run(cmd, capture_output=True, text=True, check=True)
        issue_url = result.stdout.strip()
        print(f"✓ Created: {title}")
        print(f"  URL: {issue_url}")
        return issue_url
    except subprocess.CalledProcessError as e:
        print(f"✗ Failed to create: {title}")
        print(f"  Error: {e.stderr}")
        return None


def main() -> None:
    """Main migration function."""
    import argparse

    parser = argparse.ArgumentParser(
        description="Migrate active tasks from tasks.json to GitHub Issues"
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Show what would be created without creating issues",
    )
    parser.add_argument(
        "--repo",
        type=str,
        default="JoshCLWren/comic-pile",
        help="GitHub repository (default: JoshCLWren/comic-pile)",
    )
    args = parser.parse_args()

    os.environ["GITHUB_REPO"] = args.repo

    print("Loading tasks from tasks.json...")
    all_tasks = load_tasks()
    print(f"Total tasks: {len(all_tasks)}")

    active_tasks = get_active_tasks(all_tasks)
    print(f"Active tasks to migrate: {len(active_tasks)}\n")

    if not active_tasks:
        print("No active tasks found. Nothing to migrate.")
        return

    print("=" * 60)
    for task in active_tasks:
        print(f"Task: {task.get('task_id')} - {task.get('title')}")
        print(f"  Status: {task.get('status')}")
        print(f"  Priority: {task.get('priority')}")
        create_github_issue(task, dry_run=args.dry_run)
        print("-" * 60)

    print("\n" + "=" * 60)
    if not args.dry_run:
        print("Migration complete!")
        print(f"Created {len(active_tasks)} issues on GitHub")
        print("\nNext steps:")
        print("  1. Verify issues at: https://github.com/JoshCLWren/comic-pile/issues")
        print("  2. Update task statuses in tasks.json to 'done' if desired")
        print("  3. Delete old issues from GitHub if needed")
    else:
        print("Dry run complete. No issues created.")
        print("Run without --dry-run to create issues.")


if __name__ == "__main__":
    main()
