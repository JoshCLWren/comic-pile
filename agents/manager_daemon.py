#!/usr/bin/env python3
"""Manager daemon agent that runs continuous coordination loop."""

import argparse
import asyncio
import os
import subprocess
import sys
from datetime import datetime

import httpx

SERVER_URL = "http://localhost:8000"
SLEEP_INTERVAL = 120
HEARTBEAT_TIMEOUT = 20
MAIN_REPO = "/home/josh/code/comic-pile"
SUMMARY_INTERVAL = 600


async def review_and_merge_task(client, task, verbose=False, stats=None):
    """Review a task and auto-merge if tests pass."""
    if stats is None:
        stats = {}

    task_id = task["task_id"]
    worktree = task.get("worktree")

    if not worktree:
        print(
            f"[{datetime.now()}] {task_id}: No worktree, skipping merge (reason: worktree field is null)"
        )
        stats["no_worktree"] = stats.get("no_worktree", 0) + 1
        return False

    if os.path.isabs(worktree):
        worktree_path = worktree
    else:
        worktree_path = os.path.join(os.path.dirname(MAIN_REPO), worktree)

    if not os.path.exists(worktree_path):
        print(f"[{datetime.now()}] {task_id}: Worktree not found: {worktree_path}, skipping review")
        print(f"[{datetime.now()}] {task_id}: Reason: worktree path does not exist")
        stats["worktree_not_found"] = stats.get("worktree_not_found", 0) + 1
        return False

    print(f"[{datetime.now()}] {task_id}: Reviewing...")

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
            print(f"[{datetime.now()}] {task_id}: Failed to fetch main (error: {error_msg})")
            stats["fetch_failed"] = stats.get("fetch_failed", 0) + 1
            return False

        if verbose:
            print(f"[{datetime.now()}] {task_id}: Git fetch successful")

        result = subprocess.run(
            ["git", "rebase", "origin/main"],
            capture_output=True,
            text=True,
            timeout=60,
        )

        if result.returncode != 0 or "CONFLICT" in result.stdout:
            print(f"[{datetime.now()}] {task_id}: Merge conflict detected, marking blocked")
            await client.post(
                f"{SERVER_URL}/api/tasks/{task_id}/set-status",
                json={
                    "status": "blocked",
                    "blocked_reason": "Merge conflict during review",
                    "blocked_by": "manager-daemon",
                },
            )
            stats["merge_conflict"] = stats.get("merge_conflict", 0) + 1
            return False

        if verbose:
            print(f"[{datetime.now()}] {task_id}: Rebase successful")

        result = subprocess.run(
            ["pytest", "-x"],
            capture_output=True,
            text=True,
            timeout=300,
        )

        if result.returncode != 0:
            error_output = result.stdout[-300:] if result.stdout else "no output"
            print(
                f"[{datetime.now()}] {task_id}: Tests failed, skipping merge (error: {error_output})"
            )
            if verbose:
                print(f"[{datetime.now()}] {task_id}: Full pytest output:\n{result.stdout}")
            stats["tests_failed"] = stats.get("tests_failed", 0) + 1
            return False

        if verbose:
            print(f"[{datetime.now()}] {task_id}: Tests passed")

        result = subprocess.run(
            ["bash", "scripts/lint.sh"],
            capture_output=True,
            text=True,
            timeout=120,
        )

        if result.returncode != 0:
            error_output = result.stderr[-200:] if result.stderr else "no output"
            print(
                f"[{datetime.now()}] {task_id}: Linting failed, skipping merge (error: {error_output})"
            )
            if verbose:
                print(f"[{datetime.now()}] {task_id}: Full lint output:\n{result.stdout}")
            stats["lint_failed"] = stats.get("lint_failed", 0) + 1
            return False

        if verbose:
            print(f"[{datetime.now()}] {task_id}: Linting passed")

        merge_response = await client.post(f"{SERVER_URL}/api/tasks/{task_id}/merge-to-main")

        if merge_response.status_code == 200:
            data = merge_response.json()
            if data.get("success"):
                print(f"[{datetime.now()}] {task_id}: ✅ Merge successful")
                stats["merged"] = stats.get("merged", 0) + 1
                return True
            else:
                print(f"[{datetime.now()}] {task_id}: Merge failed (reason: {data.get('reason')})")
                stats["merge_failed"] = stats.get("merge_failed", 0) + 1
                return False
        else:
            print(
                f"[{datetime.now()}] {task_id}: Merge endpoint error {merge_response.status_code}"
            )
            stats["merge_error"] = stats.get("merge_error", 0) + 1
            return False

    except subprocess.TimeoutExpired:
        print(f"[{datetime.now()}] {task_id}: Review timeout (exceeded time limit)")
        stats["timeout"] = stats.get("timeout", 0) + 1
        return False
    except Exception as e:
        print(f"[{datetime.now()}] {task_id}: Review error: {type(e).__name__}: {e}")
        if verbose:
            import traceback

            traceback.print_exc()
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

    print(f"[{datetime.now()}] Found {len(in_review)} in_review tasks")

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
        print(f"[{datetime.now()}] Ready tasks: {len(ready_tasks)}")
        for task in ready_tasks[:3]:
            print(f"  - {task['task_id']}: {task['title']}")
    return ready_tasks


async def check_and_handle_blocked_tasks(client):
    """Check for blocked tasks and attempt auto-recovery."""
    response = await client.get(f"{SERVER_URL}/api/tasks/")
    tasks = response.json()
    blocked = [t for t in tasks if t.get("status") == "blocked"]

    if not blocked:
        return 0

    print(f"[{datetime.now()}] Found {len(blocked)} blocked tasks")

    handled_count = 0
    for task in blocked:
        task_id = task["task_id"]
        blocked_reason = task.get("blocked_reason", "Unknown")

        print(f"[{datetime.now()}] {task_id}: {blocked_reason}")

        if "Merge conflict" in blocked_reason or "CONFLICT" in blocked_reason:
            print(
                f"[{datetime.now()}] {task_id}: Merge conflict detected, cannot auto-resolve. Requires manual intervention."
            )
            print(f"[{datetime.now()}] {task_id}: Worktree: {task.get('worktree')}")
        elif "agent" in blocked_reason.lower() or "confused" in blocked_reason.lower():
            print(f"[{datetime.now()}] {task_id}: Agent confusion, unblocking for reassignment")
            await client.post(
                f"{SERVER_URL}/api/tasks/{task_id}/unclaim",
                json={"agent_name": task.get("assigned_agent", "admin")},
            )
            print(f"[{datetime.now()}] {task_id}: ✅ Unblocked and ready for reassignment")
            handled_count += 1
        else:
            print(
                f"[{datetime.now()}] {task_id}: Manual intervention needed - requires human review"
            )

    return handled_count


async def check_active_workers(client):
    """Check for active workers."""
    response = await client.get(f"{SERVER_URL}/api/tasks/")
    tasks = response.json()
    active = [t for t in tasks if t.get("status") == "in_progress"]

    if active:
        print(f"[{datetime.now()}] Active workers: {len(active)}")
        for task in active:
            last_hb = task.get("last_heartbeat")
            if last_hb:
                hb_time = datetime.fromisoformat(last_hb.replace("Z", "+00:00"))
                ago = datetime.now() - hb_time
                if ago.total_seconds() > HEARTBEAT_TIMEOUT * 60:
                    print(
                        f"  - {task['assigned_agent']} STALE: {ago.total_seconds() // 60}m since heartbeat"
                    )
    return len(active)


async def check_stopping_condition(client):
    """Check if all tasks are done."""
    ready_response = await client.get(f"{SERVER_URL}/api/tasks/ready")
    ready_tasks = ready_response.json()
    all_done = len(ready_tasks) == 0

    active_count = await check_active_workers(client)

    if all_done and active_count == 0:
        print(f"[{datetime.now()}] All tasks done! Exiting...")
        return True
    return False


async def main():
    """Main coordination loop."""
    parser = argparse.ArgumentParser(description="Manager daemon for task coordination")
    parser.add_argument("--verbose", action="store_true", help="Enable verbose logging")
    args = parser.parse_args()

    print(f"[{datetime.now()}] Starting manager daemon...")
    print(f"[{datetime.now()}] Checking every {SLEEP_INTERVAL}s...")
    if args.verbose:
        print(f"[{datetime.now()}] Verbose mode enabled")

    async with httpx.AsyncClient(timeout=30.0) as client:
        iteration = 0
        stats = {}
        last_summary_time = datetime.now()

        while True:
            try:
                iteration += 1
                print(f"\n[Iteration {iteration} at {datetime.now()}]")

                merged, stats = await check_and_review_in_review_tasks(client, args.verbose, stats)

                if merged > 0:
                    print(f"[{datetime.now()}] Auto-merged {merged} tasks this cycle")

                unblocked = await check_and_handle_blocked_tasks(client)

                if unblocked > 0:
                    print(f"[{datetime.now()}] Auto-unblocked {unblocked} tasks this cycle")

                await check_ready_tasks(client)
                await check_active_workers(client)

                should_stop = await check_stopping_condition(client)

                if should_stop:
                    print("\n=== STOPPING ===")
                    break

                time_since_summary = (datetime.now() - last_summary_time).total_seconds()
                if time_since_summary >= SUMMARY_INTERVAL:
                    reviewed = sum(stats.values())
                    skipped = stats.get("no_worktree", 0) + stats.get("worktree_not_found", 0)
                    tests_failed = stats.get("tests_failed", 0)
                    print(f"\n=== SUMMARY (last {SUMMARY_INTERVAL // 60} minutes) ===")
                    print(f"Tasks reviewed: {reviewed}")
                    print(f"  - Skipped (no worktree): {skipped}")
                    print(f"  - Failed (tests): {tests_failed}")
                    print(f"  - Merged successfully: {stats.get('merged', 0)}")
                    print(f"  - Blocked (merge conflicts): {stats.get('merge_conflict', 0)}")
                    print(
                        f"  - Other failures: {stats.get('lint_failed', 0) + stats.get('fetch_failed', 0) + stats.get('timeout', 0) + stats.get('error', 0)}"
                    )
                    print("=== END SUMMARY ===\n")
                    stats = {}
                    last_summary_time = datetime.now()

                print(f"Waiting {SLEEP_INTERVAL}s...")
                await asyncio.sleep(SLEEP_INTERVAL)

            except Exception as e:
                print(f"[{datetime.now()}] ERROR: {e}")
                print(f"Retrying in {SLEEP_INTERVAL}s...")
                await asyncio.sleep(SLEEP_INTERVAL)


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print(f"\n[{datetime.now()}] Daemon stopped by user (Ctrl+C)")
        sys.exit(0)
