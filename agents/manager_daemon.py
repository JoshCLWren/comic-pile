#!/usr/bin/env python3
"""Manager daemon agent that runs continuous coordination loop."""

import argparse
import asyncio
import logging
import os
import subprocess
import sys
from datetime import datetime

import httpx

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(levelname)s - %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
logger = logging.getLogger(__name__)

SERVER_URL = "http://localhost:8000"
SLEEP_INTERVAL = 120
HEARTBEAT_TIMEOUT = 20
MAIN_REPO = "/home/josh/code/comic-pile"
SUMMARY_INTERVAL = 300


async def review_and_merge_task(client, task, verbose=False, stats=None):
    """Review a task and auto-merge if tests pass."""
    if stats is None:
        stats = {}

    task_id = task["task_id"]
    worktree = task.get("worktree")

    if not worktree:
        logger.warning("%s: No worktree, skipping merge (reason: worktree field is null)", task_id)
        stats["no_worktree"] = stats.get("no_worktree", 0) + 1
        return False

    if os.path.isabs(worktree):
        worktree_path = worktree
    else:
        worktree_path = os.path.join(os.path.dirname(MAIN_REPO), worktree)

    if not os.path.exists(worktree_path):
        logger.warning("%s: Worktree not found: %s, skipping review", task_id, worktree_path)
        logger.debug("%s: Reason: worktree path does not exist", task_id)
        stats["worktree_not_found"] = stats.get("worktree_not_found", 0) + 1
        return False

    logger.info("%s: Reviewing...", task_id)

    os.chdir(worktree_path)

    try:
        result = subprocess.run(
            ["git", "fetch", "origin", "main"],
            capture_output=True,
            text=True,
            timeout=60,
        )
        if result.returncode != 0:
            error_msg = result.stderr[-200:] if result.stderr else "unknown error"
            logger.error("%s: Failed to fetch main (error: %s)", task_id, error_msg)
            stats["fetch_failed"] = stats.get("fetch_failed", 0) + 1
            return False

        if verbose:
            logger.debug("%s: Git fetch successful", task_id)

        result = subprocess.run(
            ["git", "rebase", "origin/main"],
            capture_output=True,
            text=True,
            timeout=60,
        )

        if result.returncode != 0 or "CONFLICT" in result.stdout:
            logger.warning("%s: Merge conflict detected, gathering details...", task_id)
            logger.debug("%s: Git rebase returncode: %s", task_id, result.returncode)
            logger.debug("%s: Git rebase stdout: %s", task_id, result.stdout[-500:])

            conflict_details = []
            conflict_details.append("Merge conflict during rebase with origin/main")
            conflict_details.append(f"\nGit rebase output:\n{result.stdout}")
            if result.stderr:
                conflict_details.append(f"\nGit stderr:\n{result.stderr}")

            try:
                result = subprocess.run(
                    ["git", "status", "--short"],
                    capture_output=True,
                    text=True,
                    timeout=30,
                )
                if result.returncode == 0:
                    conflict_details.append(f"\nGit status:\n{result.stdout}")
                    logger.info("%s: Conflict files: %s", task_id, result.stdout.strip())
            except Exception as e:
                logger.warning("%s: Failed to get git status: %s", task_id, e)
                conflict_details.append(f"\nFailed to get git status: {e}")

            try:
                result = subprocess.run(
                    ["git", "log", "--oneline", "-5"],
                    capture_output=True,
                    text=True,
                    timeout=30,
                )
                if result.returncode == 0 and result.stdout:
                    conflict_details.append(f"\nRecent commits:\n{result.stdout}")
                    logger.info("%s: Branch recent commits:\n%s", task_id, result.stdout.strip())
            except Exception as e:
                logger.warning("%s: Failed to get recent commits: %s", task_id, e)
                conflict_details.append(f"\nFailed to get recent commits: {e}")

            try:
                result = subprocess.run(
                    ["git", "log", "--oneline", "origin/main", "-5"],
                    capture_output=True,
                    text=True,
                    timeout=30,
                )
                if result.returncode == 0 and result.stdout:
                    conflict_details.append(f"\nOrigin/main recent commits:\n{result.stdout}")
                    logger.info(
                        "%s: Origin/main recent commits:\n%s", task_id, result.stdout.strip()
                    )
            except Exception as e:
                logger.warning("%s: Failed to get origin/main commits: %s", task_id, e)
                conflict_details.append(f"\nFailed to get origin/main commits: {e}")

            conflict_note = "\n".join(conflict_details)

            detailed_reason = "Merge conflict during review"
            logger.info("%s: Marking blocked with conflict details", task_id)

            try:
                response = await client.post(
                    f"{SERVER_URL}/api/tasks/{task_id}/set-status",
                    json={
                        "status": "blocked",
                        "blocked_reason": detailed_reason,
                        "blocked_by": "manager-daemon",
                    },
                )
                if response.status_code != 200:
                    logger.error(
                        "%s: Failed to set blocked status (code: %s)", task_id, response.status_code
                    )
                else:
                    logger.info("%s: Successfully set blocked status", task_id)
            except Exception as e:
                logger.error("%s: Error setting blocked status: %s", task_id, e)

            try:
                response = await client.post(
                    f"{SERVER_URL}/api/tasks/{task_id}/update-notes",
                    json={"notes": conflict_note},
                )
                if response.status_code != 200:
                    logger.error(
                        "%s: Failed to update notes (code: %s)", task_id, response.status_code
                    )
                else:
                    logger.info("%s: Successfully updated conflict notes", task_id)
            except Exception as e:
                logger.error("%s: Error updating notes: %s", task_id, e)

            stats["merge_conflict"] = stats.get("merge_conflict", 0) + 1
            return False

        if verbose:
            logger.debug("%s: Rebase successful", task_id)

        result = subprocess.run(
            ["pytest", "-x"],
            capture_output=True,
            text=True,
            timeout=300,
        )

        if result.returncode != 0:
            error_output = result.stdout[-300:] if result.stdout else "no output"
            logger.error("%s: Tests failed, skipping merge (error: %s)", task_id, error_output)
            if verbose:
                logger.debug("%s: Full pytest output:\n%s", task_id, result.stdout)
            stats["tests_failed"] = stats.get("tests_failed", 0) + 1
            return False

        if verbose:
            logger.debug("%s: Tests passed", task_id)

        result = subprocess.run(
            ["bash", "scripts/lint.sh"],
            capture_output=True,
            text=True,
            timeout=120,
        )

        if result.returncode != 0:
            error_output = result.stderr[-200:] if result.stderr else "no output"
            logger.error("%s: Linting failed, skipping merge (error: %s)", task_id, error_output)
            if verbose:
                logger.debug("%s: Full lint output:\n%s", task_id, result.stdout)
            stats["lint_failed"] = stats.get("lint_failed", 0) + 1
            return False

        if verbose:
            logger.debug("%s: Linting passed", task_id)

        merge_response = await client.post(f"{SERVER_URL}/api/tasks/{task_id}/merge-to-main")

        if merge_response.status_code == 200:
            data = merge_response.json()
            if data.get("success"):
                logger.info("%s: Merge successful", task_id)
                stats["merged"] = stats.get("merged", 0) + 1
                return True
            else:
                logger.error("%s: Merge failed (reason: %s)", task_id, data.get("reason"))
                stats["merge_failed"] = stats.get("merge_failed", 0) + 1
                return False
        else:
            logger.error("%s: Merge endpoint error %s", task_id, merge_response.status_code)
            stats["merge_error"] = stats.get("merge_error", 0) + 1
            return False

    except subprocess.TimeoutExpired:
        logger.warning("%s: Review timeout (exceeded time limit)", task_id)
        stats["timeout"] = stats.get("timeout", 0) + 1
        return False
    except Exception as e:
        logger.error("%s: Review error: %s: %s", task_id, type(e).__name__, e)
        if verbose:
            import traceback

            logger.debug("%s: Traceback:", task_id)
            logger.debug(traceback.format_exc())
        stats["error"] = stats.get("error", 0) + 1
        return False


async def check_and_review_in_review_tasks(client, verbose=False, stats=None):
    """Check for tasks in review and automatically review/merge them."""
    if stats is None:
        stats = {}

    response = await client.get(f"{SERVER_URL}/api/tasks/")
    tasks = response.json()
    in_review = [t for t in tasks if t.get("status") == "in_review"]

    if not in_review:
        return 0, stats

    logger.info("Found %s in_review tasks", len(in_review))

    merged_count = 0
    for task in in_review:
        if await review_and_merge_task(client, task, verbose, stats):
            merged_count += 1

    return merged_count, stats


async def check_ready_tasks(client):
    """Check for available tasks."""
    response = await client.get(f"{SERVER_URL}/api/tasks/ready")
    ready_tasks = response.json()

    if ready_tasks:
        logger.info("Ready tasks: %s", len(ready_tasks))
        for task in ready_tasks[:3]:
            logger.info("  - %s: %s", task["task_id"], task["title"])
    return ready_tasks


async def check_and_handle_blocked_tasks(client):
    """Check for blocked tasks and attempt auto-recovery."""
    response = await client.get(f"{SERVER_URL}/api/tasks/")
    tasks = response.json()
    blocked = [t for t in tasks if t.get("status") == "blocked"]

    if not blocked:
        return 0

    logger.info("Found %s blocked tasks", len(blocked))

    handled_count = 0
    for task in blocked:
        task_id = task["task_id"]
        blocked_reason = task.get("blocked_reason", "Unknown")

        logger.warning("%s: %s", task_id, blocked_reason)

        if "Merge conflict" in blocked_reason or "CONFLICT" in blocked_reason:
            logger.warning("%s: 🔥 MERGE CONFLICT DETECTED", task_id)
            logger.warning("%s: Reason: %s", task_id, blocked_reason)
            logger.warning("%s: Worktree: %s", task_id, task.get("worktree"))
            logger.warning("%s: --------------------------------------------------", task_id)

            status_notes = task.get("status_notes", "")
            if status_notes:
                logger.info("%s: Conflict details available in task notes", task_id)
                logger.info("%s: View details: curl %s/api/tasks/%s", task_id, SERVER_URL, task_id)

            logger.warning("%s: Resolution steps:", task_id)
            logger.warning("%s:   1. cd %s", task_id, task.get("worktree"))
            logger.warning("%s:   2. Review conflict files and resolve manually", task_id)
            logger.warning("%s:   3. git add <resolved-files>", task_id)
            logger.warning("%s:   4. git rebase --continue", task_id)
            logger.warning("%s:   5. Run tests: pytest", task_id)
            logger.warning("%s:   6. Run lint: bash scripts/lint.sh", task_id)
            logger.warning("%s:   7. Update task status to in_review", task_id)
            logger.warning("%s: --------------------------------------------------", task_id)
        elif "agent" in blocked_reason.lower() or "confused" in blocked_reason.lower():
            logger.info("%s: Agent confusion, unblocking for reassignment", task_id)
            await client.post(
                f"{SERVER_URL}/api/tasks/{task_id}/unclaim",
                json={"agent_name": task.get("assigned_agent", "admin")},
            )
            logger.info("%s: Unblocked and ready for reassignment", task_id)
            handled_count += 1
        else:
            logger.warning("%s: Manual intervention needed - requires human review", task_id)

    return handled_count


async def check_active_workers(client):
    """Check for active workers."""
    response = await client.get(f"{SERVER_URL}/api/tasks/")
    tasks = response.json()
    active = [t for t in tasks if t.get("status") == "in_progress"]

    if active:
        logger.info("Active workers: %s", len(active))
        for task in active:
            last_hb = task.get("last_heartbeat")
            if last_hb:
                hb_time = datetime.fromisoformat(last_hb.replace("Z", "+00:00"))
                ago = datetime.now() - hb_time
                if ago.total_seconds() > HEARTBEAT_TIMEOUT * 60:
                    logger.warning(
                        "  - %s STALE: %sm since heartbeat",
                        task["assigned_agent"],
                        ago.total_seconds() // 60,
                    )
    return len(active)


async def check_stopping_condition(client):
    """Check if all tasks are done."""
    ready_response = await client.get(f"{SERVER_URL}/api/tasks/ready")
    ready_tasks = ready_response.json()
    all_done = len(ready_tasks) == 0

    active_count = await check_active_workers(client)

    if all_done and active_count == 0:
        logger.info("All tasks done! Exiting...")
        return True
    return False


async def main():
    """Main coordination loop."""
    parser = argparse.ArgumentParser(description="Manager daemon for task coordination")
    parser.add_argument("--verbose", action="store_true", help="Enable verbose logging")
    args = parser.parse_args()

    logger.info("Starting manager daemon...")
    logger.info("Checking every %ss...", SLEEP_INTERVAL)
    if args.verbose:
        logger.info("Verbose mode enabled")

    async with httpx.AsyncClient(timeout=30.0) as client:
        try:
            await client.post(
                f"{SERVER_URL}/api/manager-daemon/health/set-active", json={"active": True}
            )
            logger.info("Registered daemon as active with health endpoint")
        except Exception as e:
            logger.warning("Failed to register with health endpoint: %s", e)

        iteration = 0
        stats = {}
        last_summary_time = datetime.now()

        while True:
            try:
                iteration += 1
                logger.info("=== Iteration %s ===", iteration)

                merged, stats = await check_and_review_in_review_tasks(client, args.verbose, stats)

                if merged > 0:
                    logger.info("Auto-merged %s tasks this cycle", merged)

                unblocked = await check_and_handle_blocked_tasks(client)

                if unblocked > 0:
                    logger.info("Auto-unblocked %s tasks this cycle", unblocked)

                await check_ready_tasks(client)
                await check_active_workers(client)

                should_stop = await check_stopping_condition(client)

                try:
                    await client.post(f"{SERVER_URL}/api/manager-daemon/health/update-last-review")
                except Exception as e:
                    logger.debug("Failed to update last review timestamp: %s", e)

                if should_stop:
                    logger.info("=== STOPPING ===")
                    break

                time_since_summary = (datetime.now() - last_summary_time).total_seconds()
                if time_since_summary >= SUMMARY_INTERVAL:
                    reviewed = sum(stats.values())
                    skipped = stats.get("no_worktree", 0) + stats.get("worktree_not_found", 0)
                    tests_failed = stats.get("tests_failed", 0)
                    active_workers = await check_active_workers(client)
                    blocked_count = len(
                        [
                            t
                            for t in (await client.get(f"{SERVER_URL}/api/tasks/")).json()
                            if t.get("status") == "blocked"
                        ]
                    )

                    logger.info("=== SUMMARY (last %s minutes) ===", SUMMARY_INTERVAL // 60)
                    logger.info("Tasks reviewed: %s", reviewed)
                    logger.info("  - Skipped (no worktree): %s", skipped)
                    logger.info("  - Failed (tests): %s", tests_failed)
                    logger.info("  - Merged successfully: %s", stats.get("merged", 0))
                    logger.info("  - Blocked (merge conflicts): %s", stats.get("merge_conflict", 0))
                    logger.info(
                        "  - Other failures: %s",
                        stats.get("lint_failed", 0)
                        + stats.get("fetch_failed", 0)
                        + stats.get("timeout", 0)
                        + stats.get("error", 0),
                    )
                    logger.info("Active workers: %s", active_workers)
                    logger.info("Blocked tasks: %s", blocked_count)
                    logger.info("=== END SUMMARY ===")
                    stats = {}
                    last_summary_time = datetime.now()

                logger.debug("Waiting %ss...", SLEEP_INTERVAL)
                await asyncio.sleep(SLEEP_INTERVAL)

            except Exception as e:
                logger.error("ERROR: %s", e)
                logger.info("Retrying in %ss...", SLEEP_INTERVAL)
                await asyncio.sleep(SLEEP_INTERVAL)


if __name__ == "__main__":
    import atexit

    async def cleanup():
        try:
            async with httpx.AsyncClient(timeout=30.0) as client:
                await client.post(
                    f"{SERVER_URL}/api/manager-daemon/health/set-active", json={"active": False}
                )
                logger.info("Unregistered daemon from health endpoint")
        except Exception as e:
            logger.error("Error updating health status on shutdown: %s", e)

    atexit.register(lambda: asyncio.run(cleanup()))

    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        logger.info("Daemon stopped by user (Ctrl+C)")
        sys.exit(0)
