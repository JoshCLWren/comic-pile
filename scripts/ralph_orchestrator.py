#!/usr/bin/env python3
"""Ralph Orchestrator - Autonomous task iteration using Ralph mode and OpenCodeClient."""

import argparse
import logging
import random
import sys
import time
from datetime import UTC, datetime

sys.path.insert(0, "/home/josh/code/journal")
from opencode_client import OpenCodeClient  # type: ignore

sys.path.insert(0, "/home/josh/code/comic-pile")
from scripts.github_task_client import GitHubTaskClient, GitHubRateLimitError
import scripts.metrics_db as metrics_db
from scripts.opencode_launcher import ensure_opencode_running

logging.basicConfig(
    level=logging.INFO,
    format="[%(asctime)s] %(levelname)s: %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger(__name__)

MAX_ITERATIONS = 1000
MAX_CONSECUTIVE_FAILURES = 10
MIN_BACKOFF_SECONDS = 10
MAX_BACKOFF_SECONDS = 600


class CircuitBreakerState:
    """Circuit breaker state for task execution."""

    def __init__(self) -> None:
        """Initialize circuit breaker state.

        Starts with circuit closed (allowing execution) and no failures.
        """
        self.consecutive_failures = 0
        self.is_open = False
        self.last_failure_time: datetime | None = None

    def record_success(self) -> None:
        """Record a successful task execution."""
        self.consecutive_failures = 0
        self.is_open = False
        self.last_failure_time = None

    def record_failure(self) -> None:
        """Record a failed task execution."""
        self.consecutive_failures += 1
        self.last_failure_time = datetime.now(UTC)

        if self.consecutive_failures >= MAX_CONSECUTIVE_FAILURES:
            self.is_open = True
            logger.error(
                f"Circuit breaker opened after {self.consecutive_failures} consecutive failures"
            )

    def should_allow_execution(self) -> bool:
        """Check if execution should be allowed."""
        if not self.is_open:
            return True

        if self.last_failure_time is None:
            return False

        elapsed = (datetime.now(UTC) - self.last_failure_time).total_seconds()
        if elapsed > MAX_BACKOFF_SECONDS:
            self.is_open = False
            self.consecutive_failures = 0
            logger.info("Circuit breaker closed")
            return True

        return False

    def get_backoff_seconds(self) -> float:
        """Get exponential backoff seconds with jitter."""
        if self.consecutive_failures == 0:
            return 0

        base_backoff = min(
            MIN_BACKOFF_SECONDS * (2 ** (self.consecutive_failures - 1)),
            MAX_BACKOFF_SECONDS,
        )
        jitter = random.uniform(0, base_backoff * 0.1)
        return base_backoff + jitter


def get_timestamp() -> str:
    """Get current timestamp in HH:MM:SS format."""
    return datetime.now().strftime("%H:%M:%S")


def log_step(step: int, message: str) -> None:
    """Log step with step number."""
    print(f"[{get_timestamp()}] [STEP {step}] {message}")


def log_section(title: str) -> None:
    """Log section header."""
    print(f"\n{'=' * 60}")
    print(f"  {title}")
    print(f"{'=' * 60}\n")


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
{task["description"]}

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


def process_task_with_client(
    client: OpenCodeClient,
    github_client: GitHubTaskClient,
    task: dict,
    verbose: bool = False,
) -> bool:
    """Process a single task using OpenCodeClient."""
    log_section(f"TASK: {task['id']} - {task['title']}")
    log_step(1, "Initializing OpenCode session")

    logger.info(f"Connecting to opencode at {client.base_url}")
    try:
        session_id = client.create_session()
        logger.info(f"Creating session: {session_id}")
    except Exception as e:
        logger.error(f"Failed to create session: {e}")
        raise

    log_step(2, "Generating Ralph mode prompt")
    ralph_prompt = generate_ralph_prompt(task)
    logger.info("Generating Ralph mode prompt")

    if verbose:
        print("\n--- RALPH MODE PROMPT ---")
        print(ralph_prompt)
        print("--- END PROMPT ---\n")

    log_step(3, "Sending prompt to opencode session")
    logger.info("Sending prompt to opencode")

    try:
        response = client.chat(ralph_prompt, timeout=None)
        content = response.get("content", "")

        if not content:
            logger.error("Received empty response from opencode")
            logger.error("AI may have failed to start or complete task")
            logger.error("Retrying task on next iteration...")
            return False

        logger.info(f"Received response ({len(content)} chars)")
    except Exception as e:
        logger.error(f"Failed to get response: {e}")
        logger.error("Retrying task on next iteration...")
        return False

    log_step(4, "Parsing AI response for completion detection")
    is_complete = "<complete>" in content or "<promise>" in content
    logger.info(f"Completion detection: {'COMPLETE' if is_complete else 'NOT COMPLETE'}")

    if not is_complete:
        logger.info("Note: AI response received but completion signal not found")
        logger.info("This is expected in Ralph mode - AI continues working in background")
        logger.info("Task will be retried on next iteration if not complete")

    return is_complete


def main() -> None:
    """Main orchestrator loop."""
    parser = argparse.ArgumentParser(description="Ralph Orchestrator - Autonomous task iteration")
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
    parser.add_argument(
        "--max-iterations",
        type=int,
        default=MAX_ITERATIONS,
        help="Maximum number of task iterations (default: 1000)",
    )
    args = parser.parse_args()

    if args.dry_run:
        logger.info("DRY RUN MODE - No actual changes will be made")
        logger.info("[DRY RUN] Would ensure opencode is running")
        logger.info("[DRY RUN] Would initialize GitHub client")
        logger.info("[DRY RUN] Would start task loop")
        return

    circuit_breaker = CircuitBreakerState()
    iteration_count = 0
    total_iterations = 0

    try:
        github_client = GitHubTaskClient()
        logger.info("Connected to GitHub")
    except ValueError as e:
        logger.error(f"Failed to initialize GitHub client: {e}")
        logger.error("GITHUB_TOKEN environment variable is required")
        sys.exit(1)

    logger.info("Ensuring opencode is running...")
    if not ensure_opencode_running(base_url=args.base_url):
        logger.error("Failed to ensure opencode is running")
        sys.exit(1)

    logger.info(f"Connecting to opencode at {args.base_url}")
    try:
        opencode_client = OpenCodeClient(base_url=args.base_url)

        logger.info("Checking opencode health")
        health = opencode_client.health()
        if not health.get("healthy"):
            logger.error(f"OpenCode not healthy: {health}")
            sys.exit(1)
        version = health.get("version", "unknown")
        logger.info(f"Health check passed (version: {version})")
    except Exception as e:
        logger.error(f"Error connecting to opencode: {e}")
        sys.exit(1)

    logger.info(f"Starting Ralph Orchestrator (max iterations: {args.max_iterations})")

    while total_iterations < args.max_iterations:
        if not circuit_breaker.should_allow_execution():
            backoff = circuit_breaker.get_backoff_seconds()
            logger.warning(f"Circuit breaker open. Waiting {backoff:.1f}s before retry...")
            time.sleep(backoff)
            continue

        try:
            logger.info("Finding pending task...")
            pending_task = github_client.find_pending_task()

            if not pending_task:
                logger.info("No pending tasks found, checking blocked tasks...")
                blocked_task = github_client.find_blocked_task()

                if blocked_task:
                    logger.info(
                        f"Found blocked task: {blocked_task['id']} - {blocked_task['title']}"
                    )

                    if github_client.are_dependencies_resolved(blocked_task):
                        logger.info(
                            f"  All dependencies resolved - unblocking task {blocked_task['id']}"
                        )
                        github_client.update_status(blocked_task["id"], "pending")  # type: ignore
                        time.sleep(2)
                        continue

                    deps = blocked_task.get("dependencies", "none")
                    logger.info(f"  Still blocked by: {deps}")
                    logger.info("  Waiting 60 seconds before next check...")
                    time.sleep(60)
                    continue

                    deps = blocked_task.get("dependencies", "none")
                    logger.info(f"  Still blocked by: {deps}")
                    logger.info("  Waiting 60 seconds before next check...")
                    time.sleep(60)
                    continue

                logger.info("No pending or blocked tasks found - waiting 60 seconds...")
                time.sleep(60)
                continue

            task_id = pending_task["id"]
            logger.info(f"Found pending task: {task_id} - {pending_task['title']}")

            if args.verbose:
                print(f"\n{'=' * 60}")
                print(f"Task: {pending_task['id']} - {pending_task['title']}")
                print(f"{'=' * 60}\n")
                print(f"Status: {pending_task['status']}")
                print(f"Priority: {pending_task['priority']}")
                print(f"Type: {pending_task['task_type']}")
                if pending_task.get("dependencies"):
                    print(f"Dependencies: {pending_task['dependencies']}")
                print(f"{'=' * 60}\n")

            log_step(5, f"Marking task {task_id} as in-progress")
            github_client.update_status(task_id, "in-progress")  # type: ignore
            logger.info(f"Marked task {task_id} as in-progress")

            start_time = time.time()

            try:
                completed = process_task_with_client(
                    opencode_client,
                    github_client,
                    pending_task,
                    args.verbose,
                )

                duration = time.time() - start_time

                if completed:
                    log_section(f"TASK {task_id} COMPLETED")
                    log_step(6, f"Updating task {task_id} to 'done' status")
                    github_client.update_status(task_id, "done")  # type: ignore
                    logger.info(f"Marked task {task_id} as done")

                    metrics_db.record_metric(
                        task_id=task_id,  # type: ignore
                        status="done",
                        duration=duration,
                    )

                    circuit_breaker.record_success()
                    iteration_count += 1
                    total_iterations += 1
                    logger.info(f"Iteration {iteration_count}/{args.max_iterations} completed")
                    logger.info("Waiting 2 seconds before next task...")
                    time.sleep(2)
                else:
                    logger.error(f"Task {task_id} not complete - AI did not signal completion")
                    log_step(7, f"Marking task {task_id} as pending for retry")
                    github_client.update_status(task_id, "pending")  # type: ignore
                    logger.info(f"Marked task {task_id} as pending (will retry on next loop)")

                    metrics_db.record_metric(
                        task_id=task_id,  # type: ignore
                        status="pending",
                        duration=duration,
                        error_type="no_completion_signal",
                    )

                    circuit_breaker.record_failure()
                    total_iterations += 1

            except GitHubRateLimitError as e:
                logger.warning(f"GitHub rate limit hit: {e}")
                logger.info("Waiting for rate limit to reset...")
                github_client._wait_for_rate_limit_reset()
                continue
            except Exception as e:
                duration = time.time() - start_time
                logger.error(f"\nError processing task {task_id}: {e}")
                if args.verbose:
                    import traceback

                    logger.info("Traceback:")
                    traceback.print_exc()

                log_step(7, f"Marking task {task_id} as pending for retry")
                github_client.update_status(task_id, "pending")  # type: ignore
                logger.info(f"Marked task {task_id} as pending (will retry on next iteration)")

                metrics_db.record_metric(
                    task_id=task_id,  # type: ignore
                    status="pending",
                    duration=duration,
                    error_type="no_completion_signal",
                )

                circuit_breaker.record_failure()
                total_iterations += 1

        except KeyboardInterrupt:
            logger.info("\nInterrupted by user")
            break
        except Exception as e:
            logger.error(f"Unexpected error in main loop: {e}")
            if args.verbose:
                import traceback

                traceback.print_exc()
            time.sleep(5)
            total_iterations += 1

    logger.info(f"\nRalph Orchestrator completed after {total_iterations} iterations")
    logger.info(f"Successfully completed {iteration_count} tasks")


if __name__ == "__main__":
    main()
