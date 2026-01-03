#!/usr/bin/env python3
"""Manager daemon agent that runs continuous coordination loop."""

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


async def review_and_merge_task(client, task):
    """Review a task and auto-merge if tests pass."""
    task_id = task["task_id"]
    worktree = task.get("worktree")

    if not worktree:
        print(f"[{datetime.now()}] {task_id}: No worktree, skipping")
        return False

    if os.path.isabs(worktree):
        worktree_path = worktree
    else:
        worktree_path = os.path.join(os.path.dirname(MAIN_REPO), worktree)

    if not os.path.exists(worktree_path):
        print(f"[{datetime.now()}] {task_id}: Worktree not found: {worktree_path}")
        print(f"[{datetime.now()}] {task_id}: Skipping review")
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
            print(f"[{datetime.now()}] {task_id}: Failed to fetch main")
            return False

        result = subprocess.run(
            ["git", "rebase", "origin/main"],
            capture_output=True,
            text=True,
            timeout=60,
        )

        if result.returncode != 0 or "CONFLICT" in result.stdout:
            print(f"[{datetime.now()}] {task_id}: Merge conflict, marking blocked")
            await client.post(
                f"{SERVER_URL}/api/tasks/{task_id}/set-status",
                json={
                    "status": "blocked",
                    "blocked_reason": "Merge conflict during review",
                    "blocked_by": "manager-daemon",
                },
            )
            return False

        result = subprocess.run(
            ["pytest", "-x"],
            capture_output=True,
            text=True,
            timeout=300,
        )

        if result.returncode != 0:
            print(f"[{datetime.now()}] {task_id}: Tests failed, skipping merge")
            print(f"  {result.stdout[-500:]}")
            return False

        result = subprocess.run(
            ["bash", "scripts/lint.sh"],
            capture_output=True,
            text=True,
            timeout=120,
        )

        if result.returncode != 0:
            print(f"[{datetime.now()}] {task_id}: Linting failed, skipping merge")
            return False

        merge_response = await client.post(f"{SERVER_URL}/api/tasks/{task_id}/merge-to-main")

        if merge_response.status_code == 200:
            data = merge_response.json()
            if data.get("success"):
                print(f"[{datetime.now()}] {task_id}: ✅ Merged to main")
                return True
            else:
                print(f"[{datetime.now()}] {task_id}: Merge failed - {data.get('reason')}")
                return False
        else:
            print(
                f"[{datetime.now()}] {task_id}: Merge endpoint error {merge_response.status_code}"
            )
            return False

    except subprocess.TimeoutExpired:
        print(f"[{datetime.now()}] {task_id}: Review timeout")
        return False
    except Exception as e:
        print(f"[{datetime.now()}] {task_id}: Review error: {e}")
        return False


async def check_and_review_in_review_tasks(client):
    """Check for tasks in review and automatically review/merge them."""
    response = await client.get(f"{SERVER_URL}/api/tasks/")
    tasks = response.json()
    in_review = [t for t in tasks if t.get("status") == "in_review"]

    if not in_review:
        return 0

    print(f"[{datetime.now()}] Found {len(in_review)} in_review tasks")

    merged_count = 0
    for task in in_review:
        if await review_and_merge_task(client, task):
            merged_count += 1

    return merged_count


async def check_ready_tasks(client):
    """Check for available tasks."""
    response = await client.get(f"{SERVER_URL}/api/tasks/ready")
    ready_tasks = response.json()

    if ready_tasks:
        print(f"[{datetime.now()}] Ready tasks: {len(ready_tasks)}")
        for task in ready_tasks[:3]:
            print(f"  - {task['task_id']}: {task['title']}")
    return ready_tasks


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
    print(f"[{datetime.now()}] Starting manager daemon...")
    print(f"[{datetime.now()}] Checking every {SLEEP_INTERVAL}s...")

    async with httpx.AsyncClient(timeout=30.0) as client:
        iteration = 0

        while True:
            try:
                iteration += 1
                print(f"\n[Iteration {iteration} at {datetime.now()}]")

                merged = await check_and_review_in_review_tasks(client)

                if merged > 0:
                    print(f"[{datetime.now()}] Auto-merged {merged} tasks this cycle")

                await check_ready_tasks(client)
                await check_active_workers(client)

                should_stop = await check_stopping_condition(client)

                if should_stop:
                    print("\n=== STOPPING ===")
                    break

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
