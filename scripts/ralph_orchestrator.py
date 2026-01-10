#!/usr/bin/env python3
"""Ralph Orchestrator - Autonomous task iteration using Ralph mode and OpenCodeClient."""

import argparse
import logging
import random
import re
import subprocess
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


def run_pytest() -> tuple[bool, str, float]:
    """Run pytest and check results.

    Returns:
        (passed, output, coverage_percentage)
    """
    logger.info("Running pytest...")
    try:
        result = subprocess.run(
            ["pytest", "--cov=comic_pile", "--cov-report=term-missing", "-q"],
            capture_output=True,
            text=True,
            timeout=300,
        )

        output = result.stdout + result.stderr
        coverage = 0.0

        for line in output.split("\n"):
            if "TOTAL" in line and "coverage" in line.lower():
                try:
                    coverage_str = line.split("coverage")[1].split("%")[0].strip()
                    coverage = float(coverage_str)
                except Exception:
                    pass

        passed = result.returncode == 0
        return passed, output, coverage
    except subprocess.TimeoutExpired:
        return False, "Tests timed out after 5 minutes", 0.0
    except Exception as e:
        return False, str(e), 0.0


def run_lint() -> tuple[bool, str]:
    """Run linting and check results.

    Returns:
        (passed, output)
    """
    logger.info("Running lint...")
    try:
        result = subprocess.run(
            ["bash", "scripts/lint.sh"],
            capture_output=True,
            text=True,
            timeout=120,
        )

        output = result.stdout + result.stderr
        passed = result.returncode == 0
        return passed, output
    except subprocess.TimeoutExpired:
        return False, "Linting timed out after 2 minutes"
    except Exception as e:
        return False, str(e)


def analyze_code_quality(task: dict) -> list[str]:
    """Check for code quality issues in the task's changes.

    Returns:
        List of quality findings
    """
    issues = []

    try:
        result = subprocess.run(
            ["git", "log", "--all", "--oneline", "--grep", f"#{task['id']}"],
            capture_output=True,
            text=True,
            timeout=30,
        )

        if result.stdout.strip():
            commit_hash = result.stdout.split()[0].split(":")[-1]
            diff_result = subprocess.run(
                ["git", "show", "--stat", commit_hash],
                capture_output=True,
                text=True,
                timeout=30,
            )
            diff_output = diff_result.stdout + diff_result.stderr

            if "TODO" in diff_output or "FIXME" in diff_output:
                issues.append("Found TODO/FIXME comments in new code")

            if "print(" in diff_output or "console.log" in diff_output:
                issues.append("Found debug print statements or console.log calls")

            if "# type: ignore" in diff_output:
                issues.append("Found '# type: ignore' comments - should use proper types")

            if "# noqa" in diff_output or "# pylint: ignore" in diff_output:
                issues.append("Found '# noqa' or '# pylint: ignore' - fix linting issue")
    except Exception as e:
        logger.warning(f"Could not analyze code quality: {e}")

    return issues


def analyze_edge_cases(task: dict) -> list[str]:
    """Check for edge case handling.

    Returns:
        List of edge case issues
    """
    issues = []

    try:
        result = subprocess.run(
            ["git", "log", "--all", "--oneline", "--grep", f"#{task['id']}"],
            capture_output=True,
            text=True,
            timeout=30,
        )

        if result.stdout.strip():
            commit_hash = result.stdout.split()[0].split(":")[-1]
            diff_result = subprocess.run(
                ["git", "show", commit_hash],
                capture_output=True,
                text=True,
                timeout=30,
            )
            diff_output = diff_result.stdout + diff_result.stderr

            if "except:" in diff_output and "raise" not in diff_output:
                issues.append("Exception handler doesn't re-raise - errors swallowed")

            if task.get("task_type") in ["feature", "bug_fix"]:
                if "validate" not in diff_output and "check" not in diff_output:
                    issues.append("No input validation found for user-facing changes")
    except Exception as e:
        logger.warning(f"Could not analyze edge cases: {e}")

    return issues


def analyze_hacks(task: dict) -> list[str]:
    """Check for hacks and workarounds.

    Returns:
        List of hack findings
    """
    issues = []

    try:
        result = subprocess.run(
            ["git", "log", "--all", "--oneline", "--grep", f"#{task['id']}"],
            capture_output=True,
            text=True,
            timeout=30,
        )

        if result.stdout.strip():
            commit_hash = result.stdout.split()[0].split(":")[-1]
            diff_result = subprocess.run(
                ["git", "show", commit_hash],
                capture_output=True,
                text=True,
                timeout=30,
            )
            diff_output = diff_result.stdout + diff_result.stderr

            if re.search(r"try:\s*import.*except.*:", diff_output):
                issues.append("Found try/except import pattern - should fix circular imports")

            if "user_id=1" in diff_output:
                issues.append("Hardcoded user_id=1 - should use proper user context")

            if "'*'" in diff_output and "CORS" in diff_output:
                issues.append("CORS set to wildcard - security risk")
    except Exception as e:
        logger.warning(f"Could not analyze hacks: {e}")

    return issues


def mrs_crabapple_qc_review(task_id: int, github_client: GitHubTaskClient) -> bool:
    """Mrs. Crabapple reviews an in-review task for quality.

    Args:
        task_id: GitHub issue number
        github_client: GitHub task client (using gh CLI)

    Returns:
        True if approved (marks as done), False if rejected (reverts to pending)
    """
    log_section(f"MRS. CRABAPPLE QC REVIEW FOR TASK {task_id}")

    task = github_client.get_task(task_id)
    if not task:
        logger.error(f"Task {task_id} not found")
        return False

    task_title = task.get("title", "Unknown")

    logger.info("Running pytest...")
    test_passed, test_output, test_coverage = run_pytest()

    logger.info("Running linting...")
    lint_passed, lint_output = run_lint()

    logger.info(f"Test coverage: {test_coverage:.1f}%")

    all_issues = []

    if not test_passed:
        all_issues.append("Tests failed")

    if not lint_passed:
        all_issues.append("Linting failed")
        if lint_output:
            all_issues.append(f"Linting errors: {lint_output}")

    code_quality_issues = analyze_code_quality(task)
    all_issues.extend(code_quality_issues)

    edge_case_issues = analyze_edge_cases(task)
    all_issues.extend(edge_case_issues)

    hack_issues = analyze_hacks(task)
    all_issues.extend(hack_issues)

    if all_issues:
        log_section(f"TASK {task_id} QC REJECTED")
        log_step(1, "Quality issues found:")
        for i, issue in enumerate(all_issues, 1):
            log_step(1 + i, f"  - {issue}")

        qc_comment = f"""## Mrs. Crabapple Quality Control Review

**Task:** #{task_id} - {task_title}
**Reviewed at:** {datetime.now(UTC).isoformat()}

### Test Results
- **Tests:** {"✓ PASSED" if test_passed else "✗ FAILED"}
- **Coverage:** {test_coverage:.1f}%

### Linting Results
- **Linting:** {"✓ PASSED" if lint_passed else "✗ FAILED"}

### Quality Issues Found
"""
        for issue in all_issues:
            qc_comment += f"- {issue}\n"

        qc_comment += """
### Action Required
Please address the issues above and resubmit for review.
This task will be picked up by Ralph for another iteration.
"""

        log_step(2, f"Reverting task {task_id} to pending with QC notes")
        github_client.update_status(task_id, "pending", qc_comment)
        logger.info(f"Reverted task {task_id} to pending")
        return False
    else:
        log_section(f"TASK {task_id} QC APPROVED")
        log_step(1, "✓ All quality checks passed")
        log_step(2, f"  - Tests passed with {test_coverage:.1f}% coverage")
        log_step(3, "  - Linting passed")
        log_step(4, "  - No code quality issues found")

        qc_comment = f"""## Mrs. Crabapple Quality Control Review

**Task:** #{task_id} - {task_title}
**Reviewed at:** {datetime.now(UTC).isoformat()}

### Test Results
- **Tests:** ✓ PASSED
- **Coverage:** {test_coverage:.1f}%

### Linting Results
- **Linting:** ✓ PASSED

### Quality Assessment
✅ **APPROVED** - Code meets all quality standards.

This task is marked as done and Ralph will move to the next task.
"""

        log_step(5, f"Marking task {task_id} as done")
        github_client.update_status(task_id, "done", qc_comment)
        logger.info(f"Approved and marked task {task_id} as done")
        return True


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

## Ralph Ownership and Quality Control

### OWNERSHIP
- **Don't skip work** because something is pre-existing or not related to the task at hand
- **Take full ownership** - solve the actual problem, don't work around it
- **Fix root causes**, not symptoms
- **Don't leave technical debt** - address issues properly
- **Don't defer to other tasks** or create sub-tasks to avoid work
- **Investigate full scope** - understand all aspects of the problem before fixing

### QUALITY CONTROL
- **No shortcuts** - QC agents expect full, proper solutions
- **No hacks or workarounds** that violate code standards
- **Complete solutions** - partial fixes that create more debt will be rejected
- **Test edge cases** - QC checks for coverage and error handling
- **Fix all linting issues** - don't use `# type: ignore` or `# noqa` to bypass standards
- **Ensure tests pass and linting clean** before marking as done

### WHEN TO ASK FOR CLARIFICATION
If the task description is incomplete or ambiguous:
- Ask for clarification BEFORE starting work
- Don't assume scope beyond what's documented
- Once scope is clear, take full ownership and complete without further questions
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
            log_step(1, "Checking for in-review tasks (Mrs. Crabapple)...")
            in_review_task = github_client.find_in_review_task()

            if in_review_task:
                task_id = in_review_task.get("id")
                if not isinstance(task_id, int):
                    logger.error(f"Invalid in-review task ID: {task_id}")
                    time.sleep(2)
                    continue

                log_section(f"PROCESSING IN-REVIEW TASK: {task_id}")

                qc_passed = mrs_crabapple_qc_review(task_id, github_client)

                if qc_passed:
                    metrics_db.record_metric(
                        task_id=task_id,
                        status="done",
                        duration=0,
                    )
                else:
                    metrics_db.record_metric(
                        task_id=task_id,
                        status="pending",
                        duration=0,
                    )

                total_iterations += 1
                logger.info(f"Iteration {total_iterations}/{args.max_iterations} completed")
                time.sleep(2)
                continue

            log_step(2, "No in-review tasks, checking for pending tasks...")
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

            log_step(3, f"Marking task {task_id} as in-progress")
            github_client.update_status(task_id, "in-progress")
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
                    log_step(4, f"Marking task {task_id} as in-review")
                    github_client.update_status(task_id, "in-review")
                    logger.info(f"Marked task {task_id} as in-review")
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
                    logger.error(f"Task {task_id} not complete - AI did not signal completion")
                    log_step(6, f"Marking task {task_id} as pending for retry")
                    github_client.update_status(task_id, "pending")
                    logger.info(f"Marked task {task_id} as pending (will retry on next loop)")

                    metrics_db.record_metric(
                        task_id=task_id,
                        status="pending",
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

                log_step(6, f"Marking task {task_id} as pending for retry")
                github_client.update_status(task_id, "pending")
                logger.info(f"Marked task {task_id} as pending (will retry on next iteration)")

                metrics_db.record_metric(
                    task_id=task_id,
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
                traceback.print_exc()
            time.sleep(5)
            total_iterations += 1

    logger.info(f"\nRalph Orchestrator completed after {total_iterations} iterations")
    logger.info(f"Successfully completed {iteration_count} tasks")


if __name__ == "__main__":
    main()
