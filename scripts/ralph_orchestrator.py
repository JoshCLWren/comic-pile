#!/usr/bin/env python3
"""Ralph Orchestrator - Autonomous task iteration using Ralph mode and OpenCodeClient."""

import argparse
import json
import sys
import time
from pathlib import Path

sys.path.insert(0, "/home/josh/code/journal")
from opencode_client import OpenCodeClient  # type: ignore


def load_tasks(tasks_file: Path) -> dict:
    """Load tasks from JSON file."""
    with open(tasks_file) as f:
        return json.load(f)


def save_tasks(tasks_file: Path, tasks_data: dict) -> None:
    """Save tasks to JSON file."""
    with open(tasks_file, "w") as f:
        json.dump(tasks_data, f, indent=2)


def find_pending_task(tasks_data: dict) -> dict | None:
    """Find the first pending task."""
    for task in tasks_data["tasks"]:
        if task["status"] in ["pending", "ready"]:
            return task
    return None


def update_task_status(tasks_data: dict, task_id: str, status: str) -> dict | None:
    """Update task status and return the task."""
    for task in tasks_data["tasks"]:
        if task["id"] == task_id:
            task["status"] = status
            return task
    return None


def generate_ralph_prompt(task: dict) -> str:
    """Generate a Ralph mode prompt for the agent."""
    prompt = f"""# Ralph Mode Task

You are working in Ralph mode. Read docs/RALPH_MODE.md.

## Task
**ID:** {task["id"]}
**Title:** {task["title"]}
**Priority:** {task["priority"]}
**Type:** {task["task_type"]}

## Description
{task["description"] or "No description provided."}

## Instructions
1. Read docs/RALPH_MODE.md for Ralph mode philosophy
2. Work autonomously to complete this task
3. Follow AGENTS.md for code style guidelines
4. Run tests (pytest) until all pass
5. Run linting (make lint) until clean
6. Commit changes with conventional format
7. When complete, output: <complete>Task done</complete>

Do NOT:
- Ask for approval on anything
- Create tasks for sub-work
- Delegate to other workers
- Wait for instructions

DO:
- Iterate until complete
- Fix failures yourself
- Test everything
"""
    return prompt


def print_task_details(task: dict, verbose: bool = False) -> None:
    """Print task details."""
    print(f"\n{'=' * 60}")
    print(f"Task: {task['id']} - {task['title']}")
    print(f"{'=' * 60}")
    print(f"Status: {task['status']}")
    print(f"Priority: {task['priority']}")
    print(f"Type: {task['task_type']}")
    if task["description"]:
        print(f"Description: {task['description']}")
    if task.get("blocked_reason"):
        print(f"Blocked: {task['blocked_reason']}")
    if verbose:
        if task.get("dependencies"):
            print(f"Dependencies: {task['dependencies']}")
    print(f"{'=' * 60}\n")


def process_task_with_client(
    client: OpenCodeClient,
    task: dict,
    verbose: bool = False,
) -> bool:
    """Process a single task using OpenCodeClient."""
    print("\n" + "=" * 60)
    print(f"Creating opencode session for task {task['id']}...")
    print("=" * 60)

    session_id = client.create_session()
    print(f"Session created: {session_id}")

    ralph_prompt = generate_ralph_prompt(task)
    print("\n" + "=" * 60)
    print("Sending Ralph mode prompt to agent...")
    print("=" * 60)

    if verbose:
        print("\n--- RALPH MODE PROMPT ---")
        print(ralph_prompt)
        print("--- END PROMPT ---\n")

    print("[RALPH] Sending prompt to opencode...")
    response = client.chat(ralph_prompt)

    print("\n" + "=" * 60)
    print("AI Response:")
    print("=" * 60)
    print(response["content"])
    print("=" * 60)

    is_complete = "<complete>" in response["content"] or "<promise>" in response["content"]

    return is_complete


def main() -> None:
    """Main orchestrator loop."""
    parser = argparse.ArgumentParser(description="Ralph Orchestrator - Autonomous task iteration")
    parser.add_argument(
        "--tasks-file",
        type=Path,
        default=Path("tasks.json"),
        help="Path to tasks.json file (default: tasks.json)",
    )
    parser.add_argument("--verbose", "-v", action="store_true", help="Enable verbose output")
    parser.add_argument(
        "--dry-run", action="store_true", help="Show what would do without executing"
    )
    parser.add_argument(
        "--base-url",
        type=str,
        default="http://127.0.0.1:4096",
        help="opencode base URL (default: http://127.0.0.1:4096)",
    )
    args = parser.parse_args()

    tasks_file = args.tasks_file
    if not tasks_file.exists():
        print(f"Error: {tasks_file} not found", file=sys.stderr)
        sys.exit(1)

    if args.dry_run:
        print("DRY RUN MODE - No actual changes will be made\n")

    iteration_count = 0

    client = None
    if not args.dry_run:
        print(f"\nConnecting to opencode at {args.base_url}...")
        try:
            client = OpenCodeClient(base_url=args.base_url)
        except Exception as e:
            print(f"Error creating OpenCodeClient: {e}", file=sys.stderr)
            sys.exit(1)

        print("Checking opencode health...")
        try:
            health = client.health()
            if not health.get("healthy"):
                print(f"OpenCode not healthy: {health}", file=sys.stderr)
                sys.exit(1)
            print(f"✓ OpenCode healthy (version: {health.get('version', 'unknown')})")
        except Exception as e:
            print(f"Error checking health: {e}", file=sys.stderr)
            sys.exit(1)

    while True:
        try:
            tasks_data = load_tasks(tasks_file)
        except Exception as e:
            print(f"Error loading tasks from {tasks_file}: {e}", file=sys.stderr)
            sys.exit(1)

        pending_task = find_pending_task(tasks_data)

        if not pending_task:
            print("\n" + "=" * 60)
            print("All tasks completed!")
            print(f"Total iterations: {iteration_count}")
            print("=" * 60 + "\n")
            break

        if args.verbose:
            print_task_details(pending_task, verbose=True)
        else:
            print(f"\n[Task {pending_task['id']}] {pending_task['title']}")

        if args.dry_run:
            print(f"[DRY RUN] Would mark task {pending_task['id']} as in_progress")
            ralph_prompt = generate_ralph_prompt(pending_task)
            print("\n--- RALPH MODE PROMPT ---")
            print(ralph_prompt)
            print("--- END PROMPT ---\n")
            print("[DRY RUN] Would create opencode session and stream responses")
            print("[DRY RUN] Would wait for completion and mark as done")
            break

        print("\nMarking task as in_progress...")
        update_task_status(tasks_data, pending_task["id"], "in_progress")
        save_tasks(tasks_file, tasks_data)

        try:
            assert client is not None, "Client should be initialized outside of dry-run mode"
            completed = process_task_with_client(client, pending_task, args.verbose)

            if completed:
                print(f"\n✓ Task {pending_task['id']} completed!")
                print(f"Marking task {pending_task['id']} as done...")
                tasks_data = load_tasks(tasks_file)
                update_task_status(tasks_data, pending_task["id"], "done")
                save_tasks(tasks_file, tasks_data)

                iteration_count += 1
                print(f"Completed iteration {iteration_count}\n")
            else:
                print(f"\n⚠ Task {pending_task['id']} not complete, will retry later")
                tasks_data = load_tasks(tasks_file)
                update_task_status(tasks_data, pending_task["id"], "pending")
                save_tasks(tasks_file, tasks_data)
                print("Task marked as pending (will retry on next iteration)")
                break

            print("Waiting 2 seconds before next task...")
            time.sleep(2)

        except Exception as e:
            print(f"\nError processing task {pending_task['id']}: {e}", file=sys.stderr)
            if args.verbose:
                import traceback

                traceback.print_exc()
            tasks_data = load_tasks(tasks_file)
            update_task_status(tasks_data, pending_task["id"], "pending")
            save_tasks(tasks_file, tasks_data)
            print("Task marked as pending (will retry on next iteration)")
            break


if __name__ == "__main__":
    main()
