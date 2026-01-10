#!/usr/bin/env python3
"""Ralph Orchestrator - Autonomous task iteration using Ralph mode and OpenCodeClient."""

import argparse
import logging
import random
import sys
import time
import traceback
from datetime import UTC, datetime

sys.path.insert(0, "/home/josh/code/journal")
from opencode_client import OpenCodeClient  # type: ignore

sys.path.insert(0, "/home/josh/code/comic-pile")
from scripts import metrics_db
from scripts.github_task_client import GitHubTaskClient
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
QC_CHECK_INTERVAL = 30


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


def generate_mrs_crabapple_prompt(task: dict) -> str:
    """Generate a Mrs. Crabapple QC review prompt for the agent."""
    prompt = f"""# Mrs. Crabapple Quality Control Review

You are Mrs. Crabapple, a quality control agent reviewing code changes.

## Task
**ID:** {task["id"]}
**Title:** {task["title"]}
**Priority:** {task["priority"]}
**Type:** {task["task_type"]}

## Description
{task["description"]}

## Instructions
1. Review the git changes for this task (use git log and git show)
2. Run pytest to verify all tests pass
3. Run make lint to verify code quality
4. Analyze code for quality issues (TODO/FIXME, debug prints, type ignores, etc.)
5. Check for proper edge case handling
6. Identify any hacks or workarounds

## Output Format

If APPROVED (all quality checks pass):
```
<approve>
All quality checks passed:
- Tests passed
- Linting clean
- No code quality issues
</approve>
```

If REJECTED (quality issues found):
```
<reject>
Quality issues found:
- [list each issue with details]
</reject>
```

After outputting your decision, add a GitHub comment with your findings using the gh CLI:
- If approved: gh issue comment {task["id"]} --body "## QC Review\n✅ APPROVED"
- If rejected: gh issue comment {task["id"]} --body "## QC Review\n❌ REJECTED\n\n[list issues]"

Then update the task status using the GitHub client:
- If approved: Mark as done
- If rejected: Mark as pending (so Ralph can retry)

## Quality Standards
- No shortcuts or partial fixes
- No hacks or workarounds
- Complete solutions with proper error handling
- All tests passing
- Linting clean (no type: ignore, noqa, etc.)
- Documentation updated
"""
    return prompt


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
0. Claim this task by running: gh issue edit {task["id"]} --add-label ralph-status:in-progress
1. Read docs/RALPH_MODE.md for Ralph mode philosophy
2. Work autonomously to complete this task
3. Follow AGENTS.md for code style guidelines
4. Run tests (pytest) until all pass even if they have nothing to do with this task.
5. Run linting (make lint) until clean even if unrelated to this task.
6. Commit changes with conventional format
7. When complete, mark as in-review: gh issue edit {task["id"]} --remove-label ralph-status:in-progress --add-label ralph-status:in-review
8. Output: <complete>Task done</complete>

Do NOT:
- Ask for approval on anything
- Wait for instructions
- Mark tests as expected to fail.
- Take shortcuts.

 DO:
 - Iterate until complete
 - Fix failures yourself
 - Test everything
 - Practice extreme ownership of the Codebase.
 - Feel free to delegate tasks to sub-agents if needed.
 - Write code that Mrs. Crabapple will approve on QC review.
 - Unblock yourself. If you get stuck, find a way around it, use sub-agents if needed.

## Ralph Ownership and Quality Control

### OWNERSHIP
- **Don't skip work** because something is pre-existing or not related to the task at hand
- **Take full ownership** - solve the actual problem, don't work around it
- **Fix root causes**, not symptoms
- **Don't leave technical debt** - address issues properly
- **Don't defer to other tasks** or create sub-tasks to avoid work
- **Investigate full scope** - understand all aspects of the problem before fixing
- **Leave it better than you found it** - improve code quality wherever possible even if you're just tasked with writing a md file.

### QUALITY CONTROL
- **No shortcuts** - QC agents expect full, proper solutions
- **No hacks or workarounds** that violate code standards
- **Complete solutions** - partial fixes that create more debt will be rejected
- **Test edge cases** - QC checks for coverage and error handling
- **Fix all linting issues** - don't use `# type: ignore` or `# noqa` to bypass standards
- **Ensure tests pass and linting clean** before marking as done
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
        sys.exit(1)

    logger.info("Ensuring opencode is running...")
    opencode_running, actual_url = ensure_opencode_running(base_url=args.base_url)
    if not opencode_running:
        logger.error("Failed to ensure opencode is running")
        sys.exit(1)

    args.base_url = actual_url

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
            log_step(1, "Checking for stale in-progress tasks...")
            stale_task = github_client.find_stale_in_progress_task(stale_seconds=3600)

            if stale_task:
                stale_id = stale_task.get("id")
                if isinstance(stale_id, int):
                    logger.info(
                        f"Found stale in-progress task: {stale_id} - {stale_task.get('title')}"
                    )
                    logger.info("  Reverting to pending so Ralph can retry")
                    github_client.update_status(stale_id, "pending")
                    time.sleep(2)
                    continue

            log_step(2, "Checking for in-review tasks (Mrs. Crabapple)...")
            in_review_task = github_client.find_in_review_task()

            if in_review_task:
                task_id = in_review_task.get("id")
                if not isinstance(task_id, int):
                    logger.error(f"Invalid in-review task ID: {task_id}")
                    time.sleep(2)
                    continue

                log_section(f"PROCESSING IN-REVIEW TASK: {task_id}")
                log_step(2, "Initializing Mrs. Crabapple session")

                logger.info(f"Connecting to opencode at {opencode_client.base_url}")
                try:
                    session_id = opencode_client.create_session()
                    logger.info(f"Creating session: {session_id}")
                except Exception as e:
                    logger.error(f"Failed to create session: {e}")
                    raise

                log_step(3, "Generating Mrs. Crabapple QC prompt")
                crabapple_prompt = generate_mrs_crabapple_prompt(in_review_task)
                logger.info("Generating Mrs. Crabapple QC prompt")

                if args.verbose:
                    print("\n--- MRS. CRABAPPLE PROMPT ---")
                    print(crabapple_prompt)
                    print("--- END PROMPT ---\n")

                log_step(4, "Sending prompt to opencode session")
                logger.info("Sending prompt to opencode")

                try:
                    response = opencode_client.chat(crabapple_prompt, timeout=None)
                    content = response.get("content", "")

                    if not content:
                        logger.error("Received empty response from opencode")
                        logger.error("AI may have failed to complete QC review")
                        logger.error("Retrying task on next iteration...")
                        continue

                    logger.info(f"Received response ({len(content)} chars)")
                except Exception as e:
                    logger.error(f"Failed to get response: {e}")
                    logger.error("Retrying task on next iteration...")
                    continue

                log_step(5, "Parsing QC review decision")
                is_approved = "<approve>" in content
                is_rejected = "<reject>" in content

                if is_approved:
                    log_section(f"TASK {task_id} QC APPROVED")
                    metrics_db.record_metric(
                        task_id=task_id,
                        status="done",
                        duration=0,
                    )
                elif is_rejected:
                    log_section(f"TASK {task_id} QC REJECTED")
                    metrics_db.record_metric(
                        task_id=task_id,
                        status="pending",
                        duration=0,
                    )
                else:
                    logger.warning("No decision found in QC review response")
                    logger.warning("Retrying task on next iteration...")
                    continue

                total_iterations += 1
                logger.info(f"Iteration {total_iterations}/{args.max_iterations} completed")
                time.sleep(2)
                continue

            log_step(3, "No in-review tasks, checking for pending tasks...")
            pending_task = github_client.find_pending_task()

            if not pending_task:
                logger.info("No pending tasks found, checking blocked tasks...")
                blocked_task = github_client.find_blocked_task()

                if blocked_task:
                    blocked_id = blocked_task.get("id")
                    if isinstance(blocked_id, int):
                        logger.info(
                            f"Found blocked task: {blocked_id} - {blocked_task.get('title')}"
                        )

                        if github_client.are_dependencies_resolved(blocked_task):
                            logger.info(
                                f"  All dependencies resolved - unblocking task {blocked_id}"
                            )
                            github_client.update_status(blocked_id, "pending")
                            time.sleep(2)
                            continue

                        deps = blocked_task.get("dependencies", "none")
                        logger.info(f"  Still blocked by: {deps}")
                        logger.info("  Waiting 60 seconds before next check...")
                        time.sleep(60)
                        continue
                    else:
                        logger.warning(f"Invalid blocked task ID: {blocked_id}")
                        time.sleep(60)
                        continue

                logger.info("No pending or blocked tasks found - waiting 60 seconds...")
                time.sleep(60)
                continue

            task_id_val = pending_task.get("id")
            if not isinstance(task_id_val, int):
                logger.error(f"Invalid task ID: {task_id_val}")
                continue
            task_id = task_id_val
            logger.info(f"Found pending task: {task_id} - {pending_task.get('title')}")

            if args.verbose:
                print(f"\n{'=' * 60}")
                print(f"Task: {task_id} - {pending_task.get('title')}")
                print(f"{'=' * 60}\n")
                print(f"Status: {pending_task.get('status')}")
                print(f"Priority: {pending_task.get('priority')}")
                print(f"Type: {pending_task.get('task_type')}")
                if pending_task.get("dependencies"):
                    print(f"Dependencies: {pending_task.get('dependencies')}")
                print(f"{'=' * 60}\n")

            log_step(3, "Sending task to Ralph agent (Ralph will claim it)")
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
                    log_section(f"TASK {task_id} READY FOR QC")
                    metrics_db.record_metric(
                        task_id=task_id,
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
                    logger.warning(f"Task {task_id} not signaled complete yet")
                    logger.warning("Ralph will retry on next loop (task is in-progress)")

                    metrics_db.record_metric(
                        task_id=task_id,
                        status="in-progress",
                        duration=duration,
                        error_type="no_completion_signal",
                    )

                    circuit_breaker.record_failure()
                    total_iterations += 1

            except Exception as e:
                duration = time.time() - start_time
                logger.error(f"\nError processing task {task_id}: {e}")
                if args.verbose:
                    logger.info("Traceback:")
                    traceback.print_exc()

                logger.warning(f"Task {task_id} will be retried on next loop")

                metrics_db.record_metric(
                    task_id=task_id,
                    status="in-progress",
                    duration=duration,
                    error_type="exception",
                )

                circuit_breaker.record_failure()
                total_iterations += 1

        except KeyboardInterrupt:
            logger.info("\nInterrupted by user")
            break
        except Exception as e:
            logger.error(f"Unexpected error in main loop: {e}")
            if args.verbose:
                traceback.print_exc()
            time.sleep(5)
            total_iterations += 1

    logger.info(f"\nRalph Orchestrator completed after {total_iterations} iterations")
    logger.info(f"Successfully completed {iteration_count} tasks")


if __name__ == "__main__":
    main()
