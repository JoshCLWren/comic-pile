# Manager Automation Proposals

This document outlines several approaches to enforce continuous manager operation and reduce manual coordination overhead.

---

## Approach 1: Shell Script Automation

**File:** `scripts/manager-daemon.sh`

A shell script that runs a continuous coordination loop, checking for in_review tasks, ready tasks, and stopping condition.

```bash
#!/bin/bash

# Manager Daemon - Runs continuous coordination loop
# Usage: ./scripts/manager-daemon.sh &

SERVER_URL="${SERVER_URL:-http://localhost:8000}"
SLEEP_INTERVAL="${SLEEP_INTERVAL:-120}"  # 2 minutes

echo "Starting manager daemon..."

while true; do
    # 1. Check for in_review tasks
    IN_REVIEW=$(curl -s "$SERVER_URL/api/tasks/" | jq '[.[] | select(.status == "in_review")]')
    
    if echo "$IN_REVIEW" | jq -e '. | length > 0'; then
        echo "Found $(echo "$IN_REVIEW" | jq 'length') tasks to review..."

        # For each in_review task, attempt auto-review
        # Note: Full auto-review logic would be more complex
        # This is a simplified version that just notifies
        for task_id in $(echo "$IN_REVIEW" | jq -r '.[].task_id'); do
            echo "  - $task_id ready for review"
        done
    fi

    # 2. Check for ready tasks
    READY_COUNT=$(curl -s "$SERVER_URL/api/tasks/ready" | jq 'length')
    ACTIVE_WORKERS=$(curl -s "$SERVER_URL/api/tasks/" | jq '[.[] | select(.status == "in_progress")] | length')

    echo "Ready: $READY_COUNT, Active: $ACTIVE_WORKERS"

    # 3. Check stopping condition
    if [ "$READY_COUNT" -eq 0 ] && [ "$ACTIVE_WORKERS" -eq 0 ]; then
        echo "All tasks done! Exiting..."
        break
    fi

    sleep "$SLEEP_INTERVAL"
done
```

### Usage:

```bash
chmod +x scripts/manager-daemon.sh
./scripts/manager-daemon.sh &  # Runs in background
```

### Pros:
- Simple to implement
- Runs continuously without supervision
- Can be stopped with Ctrl+C or kill command
- Provides console output for monitoring

### Cons:
- Limited auto-review capability (shell can't run tests/linting)
- Doesn't actively merge tasks (just notifies)
- Still needs human for actual review/merge

---

## Approach 2: Enhanced Coordinator Dashboard with Auto-Merge

**File:** `app/templates/coordinator.html`

Add JavaScript functions and UI elements to support one-click merging of all in_review tasks.

### JavaScript to Add:

```javascript
// Add to coordinator.html script section

async function autoMergeAll() {
    const response = await fetch('/api/tasks/');
    const tasks = await response.json();
    const inReview = tasks.filter(t => t.status === 'in_review');

    if (inReview.length === 0) {
        alert('No tasks in review');
        return;
    }

    if (!confirm(`Merge ${inReview.length} in-review tasks?`)) {
        return;
    }

    let success = 0;
    let skipped = 0;

    for (const task of inReview) {
        try {
            // Trigger merge via new endpoint
            const mergeResponse = await fetch(`/api/tasks/${task.task_id}/merge-to-main`, {
                method: 'POST'
            });

            if (mergeResponse.ok) {
                // Mark as done
                await fetch(`/api/tasks/${task.task_id}/set-status`, {
                    method: 'POST',
                    headers: {'Content-Type': 'application/json'},
                    body: JSON.stringify({status: 'done'})
                });

                // Unclaim task
                await fetch(`/api/tasks/${task.task_id}/unclaim`, {
                    method: 'POST',
                    headers: {'Content-Type': 'application/json'},
                    body: JSON.stringify({agent_name: task.assigned_agent})
                });

                success++;
                console.log(`Merged: ${task.task_id}`);
            } else {
                skipped++;
                console.error(`Failed to merge: ${task.task_id}`);
            }
        } catch (error) {
            skipped++;
            console.error(`Error merging ${task.task_id}:`, error);
        }
    }

    alert(`Merged ${success} tasks, ${skipped} failed/skipped`);
    location.reload();  // Refresh dashboard
}
```

### Backend Endpoint to Add (`app/api/tasks.py`):

```python
@router.post("/{task_id}/merge-to-main")
async def merge_task_to_main(task_id: str):
    """Merge a task's worktree to main automatically."""
    db = SessionLocal()
    try:
        task = db.execute(
            select(Task).where(Task.task_id == task_id)
        ).scalar_one_or_none()

        if not task:
            raise HTTPException(404, "Task not found")

        if task.status != "in_review":
            raise HTTPException(
                400,
                f"Task must be in_review, current status: {task.status}"
            )

        if not task.worktree:
            raise HTTPException(400, "No worktree assigned to task")

        # Determine worktree directory
        worktree_path = task.worktree

        if not worktree_path or not os.path.exists(worktree_path):
            raise HTTPException(400, f"Worktree not found: {worktree_path}")

        # Fetch latest main
        os.chdir(worktree_path)
        result = subprocess.run(
            ["git", "fetch", "origin", "main"],
            capture_output=True,
            text=True
        )

        if result.returncode != 0:
            raise HTTPException(500, f"Failed to fetch main: {result.stderr}")

        # Merge to main
        result = subprocess.run(
            ["git", "merge", "origin/main", "--no-ff"],
            capture_output=True,
            text=True
        )

        # Check for merge conflicts
        if "CONFLICT" in result.stdout or result.returncode != 0:
            # Mark task as blocked with conflict info
            task.status = "blocked"
            task.blocked_reason = "Merge conflict detected"
            task.status_notes += f"\n[{datetime.now()}] Auto-merge failed: git merge conflict\n{result.stdout}"
            db.commit()

            return {
                "success": False,
                "reason": "merge_conflict",
                "output": result.stdout[:500]
            }

        # Push merged changes
        result = subprocess.run(
            ["git", "push", "origin", "HEAD:main"],
            capture_output=True,
            text=True
        )

        if result.returncode != 0:
            raise HTTPException(500, f"Failed to push: {result.stderr}")

        return {
            "success": True,
            "message": "Merged to main successfully"
        }

    finally:
        db.close()
```

### UI Button to Add:

```html
<!-- Add to coordinator.html dashboard -->
<div class="mt-6 p-4 bg-yellow-500/10 border border-yellow-500/20 rounded-xl">
    <div class="flex items-center justify-between">
        <h3 class="font-bold text-yellow-600">Quick Actions</h3>
        <button
            onclick="autoMergeAll()"
            class="px-4 py-2 bg-teal-500 hover:bg-teal-600 text-white rounded-lg font-bold transition-colors">
            Auto-Merge All In-Review Tasks
        </button>
    </div>
    <p class="text-sm text-slate-500 mt-2">
        Quickly merge all review-ready tasks. Tasks with merge conflicts will be marked as blocked.
    </p>
</div>
```

### Pros:
- One-click operation for manager
- Runs tests/linting before merge (can be added to endpoint)
- Handles merge conflicts gracefully
- Immediate feedback on success/failure
- Dashboard stays updated

### Cons:
- Requires new backend endpoint
- More complex to implement
- Still requires human verification before clicking

---

## Approach 3: Automatic Worker Assignment Endpoint

**File:** Add to `app/api/tasks.py`

Add a new endpoint that automatically assigns ready tasks to idle workers.

### New Endpoint:

```python
@router.post("/auto-assign")
async def auto_assign_tasks():
    """Automatically assign ready tasks to idle workers."""
    db = SessionLocal()
    try:
        # Get ready tasks
        ready_tasks = db.execute(
            select(Task)
            .where(Task.status == "pending")
            .where(Task.dependencies.is_(None) | Task.all_dependencies_done == True)
            .order_by(Task.priority.desc())
        ).scalars().all()

        if not ready_tasks:
            return {"ready_count": 0, "assignments": []}

        # Get idle workers (no task for 10+ min)
        from datetime import datetime, timedelta
        idle_threshold = datetime.now() - timedelta(minutes=10)

        # Get workers from sessions or agent tracking
        # Note: This assumes an Agent model or tracking table exists
        # You may need to adjust based on your actual data model
        active_workers = db.execute(
            select(Task)
            .where(Task.status == "in_progress")
            .distinct(Task.assigned_agent)
        ).scalars().all()

        # For simplicity, assign tasks to available workers
        # In reality, you'd track actual worker agents separately
        assignments = []
        available_slots = max(0, 3 - len(active_workers))  # Max 3 workers

        for i, task in enumerate(ready_tasks[:available_slots]):
            # Create a worker assignment (you'd typically have worker agents)
            worker_name = f"worker-{(len(active_workers) + i + 1)}"
            worker_port = 8001 + len(active_workers) + i

            task.assigned_agent = worker_name
            task.assigned_at = datetime.now()
            task.status = "in_progress"
            task.worker_port = worker_port

            assignments.append({
                "task_id": task.task_id,
                "worker": worker_name,
                "port": worker_port
            })

        db.commit()

        return {
            "ready_count": len(ready_tasks),
            "active_count": len(active_workers),
            "assignments": assignments,
            "available_slots": available_slots
        }

    finally:
        db.close()
```

### Usage:

```bash
# Manager daemon just calls:
curl -X POST http://localhost:8000/api/tasks/auto-assign

# Response example:
{
  "ready_count": 5,
  "active_count": 2,
  "available_slots": 1,
  "assignments": [
    {
      "task_id": "TASK-BUG-001",
      "worker": "worker-3",
      "port": 8003
    }
  ]
}
```

### Pros:
- Automatically matches workers with tasks
- Reduces manual assignment friction
- Respects worker capacity limits
- Manager just triggers assignment

### Cons:
- Requires tracking idle workers
- Needs agent/worker data model
- Still relies on workers to launch themselves

---

## Approach 4: Manager Daemon Agent (Python)

**File:** `agents/manager_daemon.py`

A Python script that runs as a continuous coordination daemon with logging and proper error handling.

```python
#!/usr/bin/env python3
"""Manager daemon agent that runs continuous coordination loop."""

import asyncio
import sys
import time
from datetime import datetime, timedelta
import httpx

SERVER_URL = "http://localhost:8000"
SLEEP_INTERVAL = 120  # 2 minutes
HEARTBEAT_TIMEOUT = 20  # minutes

async def check_in_review_tasks(client):
    """Check for tasks that need review."""
    response = await client.get(f"{SERVER_URL}/api/tasks/")
    tasks = response.json()
    in_review = [t for t in tasks if t.get("status") == "in_review"]

    if in_review:
        print(f"[{datetime.now()}] Found {len(in_review)} in_review tasks")
        for task in in_review:
            print(f"  - {task['task_id']}: {task['title']}")
        return in_review
    return []

async def check_ready_tasks(client):
    """Check for available tasks."""
    response = await client.get(f"{SERVER_URL}/api/tasks/ready")
    ready_tasks = response.json()

    if ready_tasks:
        print(f"[{datetime.now()}] Ready tasks: {len(ready_tasks)}")
        for task in ready_tasks[:3]:  # Show top 3
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
            last_hb = task.get('last_heartbeat')
            if last_hb:
                hb_time = datetime.fromisoformat(last_hb.replace('Z', '+00:00'))
                ago = datetime.now() - hb_time
                if ago.total_seconds() > HEARTBEAT_TIMEOUT * 60:
                    print(f"  - {task['assigned_agent']} STALE: {ago.total_seconds() // 60}m since heartbeat")
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

                # 1. Check for in_review tasks
                in_review = await check_in_review_tasks(client)

                if in_review:
                    print(f"\nACTION NEEDED: Review and merge {len(in_review)} tasks")
                    print("Manager should review these tasks now.")
                    # Could add auto-merge logic here

                # 2. Check ready tasks and workers
                ready_tasks = await check_ready_tasks(client)
                active_count = await check_active_workers(client)

                # 3. Check stopping condition
                should_stop = await check_stopping_condition(client)

                if should_stop:
                    print("\n=== STOPPING ===")
                    break

                # 4. Wait for next iteration
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
```

### Usage:

```bash
chmod +x agents/manager_daemon.py
python3 agents/manager_daemon.py &
# Runs in background, continuous monitoring
```

### Pros:
- Full Python implementation with error handling
- Async I/O for efficient API calls
- Detailed logging and timestamps
- Detects stale workers (no heartbeat for 20+ min)
- Clean shutdown on Ctrl+C
- Extensible (can add auto-merge logic)

### Cons:
- Requires Python async client (httpx)
- Doesn't actively do work (just monitors and reports)
- Still needs manager to take action on recommendations

---

## Recommended Combination

### For Best Results, Use:

1. **Approach 2: Enhanced Coordinator Dashboard**
   - Add auto-merge button for one-click operations
   - Manager still has control (verifies before clicking)
   - Backend handles merge conflict detection

2. **Approach 4: Manager Daemon Agent** (for background monitoring)
   - Runs continuously while you're away
   - Detects stale workers and in_review tasks
   - Sends notifications to console/log file
   - You check console when you return

### Workflow:

```bash
# Start manager daemon when you leave
python3 agents/manager_daemon.py > logs/manager-$(date +%Y%m%d).log 2>&1 &

# When you return, check log file
tail -f logs/manager-$(date +%Y%m%d).log

# Use coordinator dashboard for quick actions:
# - Auto-merge button when you see in_review tasks
# - Click claim/unclaim if worker needs help
# - View stale task highlights

# Stop daemon when you're back to work
pkill -f "manager_daemon.py"
```

---

## Implementation Priority

### Phase 1 (Quick Wins - Do First):
1. **Add auto-merge button to coordinator dashboard** (Approach 2)
   - Add `/merge-to-main` endpoint to `app/api/tasks.py`
   - Add JavaScript function and button to `app/templates/coordinator.html`
   - Test: Mark task in_review, click auto-merge, verify merge

### Phase 2 (Background Monitoring):
2. **Create manager_daemon.py** (Approach 4)
   - Copy the full implementation to `agents/manager_daemon.py`
   - Test: Run in background, verify it monitors tasks correctly
   - Add to .gitignore any log files it creates

### Phase 3 (Advanced - Optional):
3. **Add auto-assign endpoint** (Approach 3)
   - Only if you want full automation
   - Requires agent/worker tracking model
   - More complex to implement

---

## Testing Checklist

After implementing any approach, test:

### For Approach 1 (Shell Script):
- [ ] Script runs without errors
- [ ] Correctly detects in_review tasks
- [ ] Correctly detects ready tasks
- [ ] Stops when all tasks done
- [ ] Runs in background (use &)
- [ ] Can be stopped with Ctrl+C

### For Approach 2 (Auto-Merge Dashboard):
- [ ] Auto-merge button appears on coordinator
- [ ] Clicking button attempts merge
- [ ] Merge conflicts are detected and task marked blocked
- [ ] Successful merges update task status to done
- [ ] Successful merges unclaim tasks
- [ ] Dashboard refreshes after merge

### For Approach 4 (Manager Daemon):
- [ ] Daemon starts without errors
- [ ] Logs in_review tasks when found
- [ ] Logs ready tasks count
- [ ] Detects stale workers (no heartbeat for 20+ min)
- [ ] Stops when all tasks done
- [ ] Handles Ctrl+C gracefully
- [ ] Runs in background with logging

---

## Notes

- These approaches can be combined or used independently
- Start with Phase 1 (auto-merge button) for quick win
- Add Phase 2 (daemon) for away-from-work scenarios
- Phase 3 is optional and more complex
- All approaches preserve the human-in-the-loop requirement
