#!/usr/bin/env python3
"""Worker Pool Manager - Automatically spawns workers when needed."""

import asyncio
import sys
from datetime import datetime

import httpx

SERVER_URL = "http://localhost:8000"
CHECK_INTERVAL = 60
MAX_WORKERS = 3

AGENT_NAMES = [
    "Alice",
    "Bob",
    "Charlie",
    "Dave",
    "Eve",
    "Frank",
    "Grace",
    "Heidi",
    "Ivan",
    "Judy",
    "Kevin",
    "Linda",
    "Mike",
    "Nia",
    "Oscar",
    "Peggy",
    "Quinn",
    "Rick",
    "Stan",
    "Tanya",
    "Ulysses",
    "Victor",
    "Wendy",
    "Xavier",
    "Yvonne",
    "Zach",
]

agent_index = 0
workers_spawned = []


async def get_active_workers(client):
    """Get count of active workers."""
    response = await client.get(f"{SERVER_URL}/api/tasks/")
    tasks = response.json()
    active = [t for t in tasks if t.get("status") == "in_progress"]
    return len(active), active


async def get_ready_tasks(client):
    """Get count of available tasks."""
    response = await client.get(f"{SERVER_URL}/api/tasks/ready")
    ready_tasks = response.json()
    return len(ready_tasks), ready_tasks


async def print_worker_status(active_count, ready_count, active_tasks):
    """Print current worker pool status."""
    print(f"[{datetime.now()}] Active workers: {active_count}/{MAX_WORKERS}")
    print(f"[{datetime.now()}] Ready tasks: {ready_count}")

    if active_tasks:
        print(f"[{datetime.now()}] Current workers:")
        for task in active_tasks:
            agent = task.get("assigned_agent", "Unknown")
            task_id = task.get("task_id", "Unknown")
            print(f"  - {agent}: working on {task_id}")


def get_next_agent_name():
    """Get next unique agent name."""
    global agent_index
    if agent_index >= len(AGENT_NAMES):
        return None
    name = AGENT_NAMES[agent_index]
    agent_index += 1
    return name


async def main():
    """Main worker pool management loop."""
    print(f"[{datetime.now()}] === Worker Pool Manager Starting ===")
    print(f"[{datetime.now()}] Checking every {CHECK_INTERVAL}s...")
    print(f"[{datetime.now()}] Max workers: {MAX_WORKERS}")
    print(f"[{datetime.now()}] Available agents: {len(AGENT_NAMES)}\n")

    session_start = datetime.now()

    async with httpx.AsyncClient(timeout=30.0) as client:
        iteration = 0

        while True:
            try:
                iteration += 1
                print(f"\n[Iteration {iteration} at {datetime.now()}]")

                active_count, active_tasks = await get_active_workers(client)
                ready_count, ready_tasks = await get_ready_tasks(client)

                await print_worker_status(active_count, ready_count, active_tasks)

                if ready_count == 0 and active_count == 0:
                    print(f"\n[{datetime.now()}] ✅ All work done!")
                    session_end = datetime.now()
                    duration = session_end - session_start
                    print(f"[{datetime.now()}] Session duration: {duration}")
                    print(f"[{datetime.now()}] Total workers spawned: {len(workers_spawned)}")
                    print(f"[{datetime.now()}] Workers launched: {', '.join(workers_spawned)}")
                    print(f"\n[{datetime.now()}] === STOPPING ===")
                    break

                if ready_count > 0 and active_count < MAX_WORKERS:
                    agent_name = get_next_agent_name()

                    if not agent_name:
                        print(f"[{datetime.now()}] ⚠️ No more agent names available!")
                        print(f"[{datetime.now()}] Waiting for existing workers to finish...")
                    else:
                        print(f"\n[{datetime.now()}] 🚀 Spawning new worker: {agent_name}")
                        print(f"[{datetime.now()}] Ready tasks available: {ready_count}")
                        print(f"[{datetime.now()}] Active workers: {active_count}/{MAX_WORKERS}")
                        print(f"[{datetime.now()}] SPAWN WORKER NOW via Task tool")
                        print(f"[{datetime.now()}] Use this prompt:")
                        print(f"\n---\n")
                        print(f"Launch agent to work on available tasks")
                        print(
                            f'Prompt: "You are a worker agent named {agent_name}. Read the Worker Agent Instructions section from MANAGER_AGENT_PROMPT.md. Your responsibilities:\n'
                        )
                        print(f"\n1. Claim a task from /api/tasks/ready")
                        print(
                            f"2. Always use your agent name '{agent_name}' in all API calls (heartbeat, unclaim, notes)"
                        )
                        print(f"3. Update status notes at meaningful milestones")
                        print(f"4. Send heartbeat every 5 minutes")
                        print(
                            f"5. Mark task in_review only when complete, tested, and ready for auto-merge"
                        )
                        print(f"6. After marking in_review, unclaim the task")
                        print(f'\nBegin by claiming a task from /api/tasks/ready."\n')
                        print(f"---\n")

                        workers_spawned.append(agent_name)
                        print(f"[{datetime.now()}] Waiting for worker to claim a task...")
                else:
                    print(
                        f"[{datetime.now()}] Worker pool full ({active_count}/{MAX_WORKERS}) or no ready tasks"
                    )

                print(f"\n[{datetime.now()}] Waiting {CHECK_INTERVAL}s...")
                await asyncio.sleep(CHECK_INTERVAL)

            except Exception as e:
                print(f"[{datetime.now()}] ERROR: {e}")
                print(f"[{datetime.now()}] Retrying in {CHECK_INTERVAL}s...")
                await asyncio.sleep(CHECK_INTERVAL)


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print(f"\n[{datetime.now()}] Stopped by user (Ctrl+C)")
        sys.exit(0)
