#!/usr/bin/env python3
"""Ralph Orchestrator - Autonomous task iteration using Ralph mode and OpenCodeClient."""

import argparse
import datetime
import json
import sys
import time
from pathlib import Path

sys.path.insert(0, "/home/josh/code/journal")
from opencode_client import OpenCodeClient  # type: ignore


def get_timestamp() -> str:
    """Get current timestamp in HH:MM:SS format."""
    return datetime.datetime.now(datetime.UTC).strftime("%H:%M:%S")


def log_info(message: str) -> None:
    """Log info message with timestamp."""
    print(f"[{get_timestamp()}] INFO: {message}")


def log_success(message: str) -> None:
    """Log success message with timestamp."""
    print(f"[{get_timestamp()}] ✓ {message}")


def log_error(message: str) -> None:
    """Log error message with timestamp."""
    print(f"[{get_timestamp()}] ✗ {message}", file=sys.stderr)


def log_step(step: int, message: str) -> None:
    """Log step with step number."""
    print(f"[{get_timestamp()}] [STEP {step}] {message}")


def log_section(title: str) -> None:
    """Log section header."""
    print(f"\n{'=' * 60}")
    print(f"  {title}")
    print(f"{'=' * 60}\n")


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
    timeout: int = 600,
) -> bool:
    """Process a single task using OpenCodeClient."""
    log_section(f"TASK: {task['id']} - {task['title']}")
    log_step(1, "Initializing OpenCode session")

    log_info(f"Connecting to opencode at {client.base_url} (timeout: {timeout}s)")
    try:
        session_id = client.create_session()
        log_success(f"Creating session: {session_id}")
    except Exception as e:
        log_error(f"Failed to create session: {e}")
        raise

    log_step(2, "Generating Ralph mode prompt")
    ralph_prompt = generate_ralph_prompt(task)
    log_info("Generating Ralph mode prompt")

    if verbose:
        print("\n--- RALPH MODE PROMPT ---")
        print(ralph_prompt)
        print("--- END PROMPT ---\n")

    log_step(3, "Sending prompt to opencode session (no timeout - let AI take as long as needed)")
    log_info("Sending prompt to opencode")

    try:
        response = client.chat(ralph_prompt, timeout=None)
        content = response.get("content", "")

        # Ralph mode task should include completion signal when done
        # Don't validate content length - let AI work until complete
        if not content:
            log_error("Received empty response from opencode")
            log_error("AI may have failed to start or complete task")
            log_error("Retrying task on next iteration...")
            return False

        log_success(f"Received response ({len(content)} chars)")
    except Exception as e:
        log_error(f"Failed to get response: {e}")
        log_error("Retrying task on next iteration...")
        return False

    log_step(4, "Parsing AI response for completion detection")
    is_complete = "<complete>" in content or "<promise>" in content
    log_info(f"Completion detection: {'COMPLETE' if is_complete else 'NOT COMPLETE'}")

    if not is_complete:
        log_info("Note: AI response received but completion signal not found")
        log_info("This is expected in Ralph mode - AI continues working in background")
        log_info("Task will be retried on next iteration if not complete")

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
    parser.add_argument(
        "--timeout",
        type=int,
        default=600,
        help="opencode request timeout in seconds (default: 600 = 10 minutes)",
    )
    args = parser.parse_args()

    tasks_file = args.tasks_file
    if not tasks_file.exists():
        log_error(f"{tasks_file} not found")
        sys.exit(1)

    if args.dry_run:
        log_info("DRY RUN MODE - No actual changes will be made")

    iteration_count = 0

    client = None
    if not args.dry_run:
        log_info("Initializing Ralph orchestrator")
        log_info(f"Connecting to opencode at {args.base_url}")
        try:
            client = OpenCodeClient(base_url=args.base_url)
        except Exception as e:
            log_error(f"Error creating OpenCodeClient: {e}")
            sys.exit(1)

        log_info("Checking opencode health")
        try:
            health = client.health()
            if not health.get("healthy"):
                log_error(f"OpenCode not healthy: {health}")
                sys.exit(1)
            version = health.get("version", "unknown")
            log_success(f"Health check passed (version: {version})")
        except Exception as e:
            log_error(f"Error checking health: {e}")
            sys.exit(1)

    while True:
        log_info("Loading tasks.json")
        try:
            tasks_data = load_tasks(tasks_file)
            task_count = len(tasks_data.get("tasks", []))
            log_success(f"Loading tasks.json ({task_count} tasks total)")
        except Exception as e:
            log_error(f"Error loading tasks from {tasks_file}: {e}")
            sys.exit(1)

        pending_task = find_pending_task(tasks_data)

        if not pending_task:
            log_section("All tasks completed - exiting")
            log_success(f"Total iterations: {iteration_count}")
            break

        task_id = pending_task["id"]
        log_success(f"Found pending task: {task_id}")

        if args.verbose:
            print_task_details(pending_task, verbose=True)
        else:
            log_info(f"[Task {task_id}] {pending_task['title']}")

        if args.dry_run:
            log_info(f"[DRY RUN] Would mark task {task_id} as in_progress")
            ralph_prompt = generate_ralph_prompt(pending_task)
            print("\n--- RALPH MODE PROMPT ---")
            print(ralph_prompt)
            print("--- END PROMPT ---\n")
            log_info("[DRY RUN] Would create opencode session and stream responses")
            log_info("[DRY RUN] Would wait for completion and mark as done")
            break

        log_step(5, "Marking task as in_progress")
        log_info(f"Marking task {task_id} as in_progress")
        update_task_status(tasks_data, task_id, "in_progress")
        log_info("Saving tasks.json")
        save_tasks(tasks_file, tasks_data)
        log_success("Saving tasks.json")

        try:
            assert client is not None, "Client should be initialized outside of dry-run mode"
            completed = process_task_with_client(
                client,
                pending_task,
                args.verbose,
                timeout=args.timeout,
            )

            if completed:
                log_section(f"TASK {task_id} COMPLETED")
                log_step(6, "Updating tasks.json with 'done' status")
                log_info(f"Marking task {task_id} as done")
                tasks_data = load_tasks(tasks_file)
                update_task_status(tasks_data, task_id, "done")
                log_info("Saving tasks.json")
                save_tasks(tasks_file, tasks_data)
                log_success("Saving tasks.json")

                iteration_count += 1
                log_success(f"Iteration {iteration_count} completed")
                log_info("Waiting 2 seconds before next task...")
                time.sleep(2)
            else:
                log_error(f"Task {task_id} not complete - AI did not signal completion")
                log_step(7, "Marking task as pending for retry")
                tasks_data = load_tasks(tasks_file)
                update_task_status(tasks_data, task_id, "pending")
                log_info("Saving tasks.json")
                save_tasks(tasks_file, tasks_data)
                log_success("Task marked as pending (will retry on next loop)")
                break

        except Exception as e:
            log_error(f"\nError processing task {task_id}: {e}")
            if args.verbose:
                import traceback

                log_info("Traceback:")
                traceback.print_exc()
            tasks_data = load_tasks(tasks_file)
            update_task_status(tasks_data, task_id, "pending")
            log_info("Saving tasks.json")
            save_tasks(tasks_file, tasks_data)
            log_success("Task marked as pending (will retry on next iteration)")
            break


if __name__ == "__main__":
    main()
