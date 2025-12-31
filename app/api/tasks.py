"""Task API endpoints."""

from datetime import UTC, datetime

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.database import get_db
from app.models import Task
from app.schemas.task import (
    ClaimTaskRequest,
    HeartbeatRequest,
    InitializeTasksResponse,
    SetStatusRequest,
    TaskCoordinatorResponse,
    TaskResponse,
    UnclaimRequest,
    UpdateNotesRequest,
)

router = APIRouter(prefix="/tasks", tags=["tasks"])

TASK_DATA = {
    "TASK-101": {
        "title": "Complete Narrative Session Summaries",
        "priority": "HIGH",
        "dependencies": None,
        "estimated_effort": "4 hours",
        "description": "Implement narrative session summaries that show consolidated 'Read:', 'Skipped:', and 'Completed:' lists per Section 11 of PRD.",
    },
    "TASK-102": {
        "title": "Add Staleness Awareness UI",
        "priority": "MEDIUM",
        "dependencies": None,
        "estimated_effort": "3 hours",
        "description": "Display stale thread suggestions on roll screen per Section 7 of PRD: 'You haven't touched X in 51 days'.",
    },
    "TASK-103": {
        "title": "Queue UI Enhancements - Roll Pool Highlighting",
        "priority": "MEDIUM",
        "dependencies": None,
        "estimated_effort": "2 hours",
        "description": "Add visual highlighting to roll pool threads (top N) in queue screen per Section 13 wireframe.",
    },
    "TASK-104": {
        "title": "Queue UI Enhancements - Completed Threads Toggle",
        "priority": "MEDIUM",
        "dependencies": None,
        "estimated_effort": "2 hours",
        "description": "Add 'Show Completed' toggle button to queue screen to show/hide completed threads.",
    },
    "TASK-105": {
        "title": "Queue UI Enhancements - Star Ratings Display",
        "priority": "MEDIUM",
        "dependencies": None,
        "estimated_effort": "2 hours",
        "description": "Display star ratings (★★★★☆) in queue list based on `last_rating` field per wireframe.",
    },
    "TASK-106": {
        "title": "Remove Unused Dice Ladder Functions",
        "priority": "MEDIUM",
        "dependencies": None,
        "estimated_effort": "1 hour",
        "description": "Remove `step_up_to_max()` and `step_down_to_min()` functions from dice_ladder.py as they violate PRD Section 2.3.",
    },
    "TASK-107": {
        "title": "Remove Notes Field from Events",
        "priority": "MEDIUM",
        "dependencies": None,
        "estimated_effort": "2 hours",
        "description": "Remove `notes` field from Event model and database as PRD Section 5.2 states 'No notes system exists'.",
    },
    "TASK-108": {
        "title": "Issues Read Adjustment UI",
        "priority": "LOW",
        "dependencies": None,
        "estimated_effort": "2 hours",
        "description": "Add increment/decrement controls to rating form to adjust issues read (currently hardcoded to 1).",
    },
    "TASK-109": {
        "title": "Queue Effect Preview Enhancement",
        "priority": "LOW",
        "dependencies": "TASK-108",
        "estimated_effort": "1 hour",
        "description": "Add explicit queue movement preview text to rating form per PRD Section 13.",
    },
    "TASK-110": {
        "title": "Add last_review_at Field to Threads",
        "priority": "LOW",
        "dependencies": None,
        "estimated_effort": "1 hour",
        "description": "Add `last_review_at` timestamp field to Thread model for storing imported review timestamps.",
    },
    "TASK-111": {
        "title": "Review Timestamp Import API",
        "priority": "LOW",
        "dependencies": "TASK-110",
        "estimated_effort": "3 hours",
        "description": "Add API endpoint to import review timestamps from League of Comic Geeks.",
    },
    "TASK-112": {
        "title": "Narrative Summary Export",
        "priority": "LOW",
        "dependencies": "TASK-101",
        "estimated_effort": "3 hours",
        "description": "Add export endpoint to generate narrative session summaries in readable text/markdown format.",
    },
}


@router.get("/", response_model=list[TaskResponse])
def list_tasks(db: Session = Depends(get_db)) -> list[TaskResponse]:
    """List all tasks with their current state."""
    tasks = db.execute(select(Task).order_by(Task.task_id)).scalars().all()
    return [
        TaskResponse(
            id=task.id,
            task_id=task.task_id,
            title=task.title,
            priority=task.priority,
            status=task.status,
            dependencies=task.dependencies,
            assigned_agent=task.assigned_agent,
            worktree=task.worktree,
            status_notes=task.status_notes,
            estimated_effort=task.estimated_effort,
            completed=task.completed,
            blocked_reason=task.blocked_reason,
            blocked_by=task.blocked_by,
            last_heartbeat=task.last_heartbeat,
            created_at=task.created_at,
            updated_at=task.updated_at,
        )
        for task in tasks
    ]


@router.get("/ready", response_model=list[TaskResponse])
def get_ready_tasks(db: Session = Depends(get_db)) -> list[TaskResponse]:
    """Get tasks ready for claiming.

    Returns tasks that are:
    - status = "pending" (not claimed)
    - blocked_reason = NULL (not blocked)
    - All dependencies are "done" (check dependencies)
    - Ordered by priority (HIGH first, then MEDIUM, then LOW)
    """
    all_tasks = (
        db.execute(select(Task).where(Task.status == "pending", Task.blocked_reason.is_(None)))
        .scalars()
        .all()
    )

    ready_tasks = []
    for task in all_tasks:
        deps_are_done = True
        if task.dependencies:
            dep_task_ids = [d.strip() for d in task.dependencies.split(",")]
            for dep_id in dep_task_ids:
                dep_task = db.execute(
                    select(Task).where(Task.task_id == dep_id)
                ).scalar_one_or_none()
                if not dep_task or dep_task.status != "done":
                    deps_are_done = False
                    break
        if deps_are_done:
            ready_tasks.append(task)

    priority_order = {"HIGH": 0, "MEDIUM": 1, "LOW": 2}
    ready_tasks.sort(key=lambda t: priority_order.get(t.priority, 99))

    return [
        TaskResponse(
            id=task.id,
            task_id=task.task_id,
            title=task.title,
            priority=task.priority,
            status=task.status,
            dependencies=task.dependencies,
            assigned_agent=task.assigned_agent,
            worktree=task.worktree,
            status_notes=task.status_notes,
            estimated_effort=task.estimated_effort,
            completed=task.completed,
            blocked_reason=task.blocked_reason,
            blocked_by=task.blocked_by,
            last_heartbeat=task.last_heartbeat,
            created_at=task.created_at,
            updated_at=task.updated_at,
        )
        for task in ready_tasks
    ]


@router.get("/coordinator-data", response_model=TaskCoordinatorResponse)
def get_coordinator_data(db: Session = Depends(get_db)) -> TaskCoordinatorResponse:
    """Get all tasks grouped by status for coordinator dashboard."""
    all_tasks = db.execute(select(Task).order_by(Task.task_id)).scalars().all()

    tasks_by_status = {
        "pending": [],
        "in_progress": [],
        "blocked": [],
        "in_review": [],
        "done": [],
    }

    for task in all_tasks:
        task_response = TaskResponse(
            id=task.id,
            task_id=task.task_id,
            title=task.title,
            priority=task.priority,
            status=task.status,
            dependencies=task.dependencies,
            assigned_agent=task.assigned_agent,
            worktree=task.worktree,
            status_notes=task.status_notes,
            estimated_effort=task.estimated_effort,
            completed=task.completed,
            blocked_reason=task.blocked_reason,
            blocked_by=task.blocked_by,
            last_heartbeat=task.last_heartbeat,
            created_at=task.created_at,
            updated_at=task.updated_at,
        )
        tasks_by_status[task.status].append(task_response)

    return TaskCoordinatorResponse(
        pending=tasks_by_status["pending"],
        in_progress=tasks_by_status["in_progress"],
        blocked=tasks_by_status["blocked"],
        in_review=tasks_by_status["in_review"],
        done=tasks_by_status["done"],
    )


@router.get("/{task_id}", response_model=TaskResponse)
def get_task(task_id: str, db: Session = Depends(get_db)) -> TaskResponse:
    """Get a single task by ID."""
    task = db.execute(select(Task).where(Task.task_id == task_id)).scalar_one_or_none()
    if not task:
        raise HTTPException(status_code=404, detail=f"Task {task_id} not found")
    return TaskResponse(
        id=task.id,
        task_id=task.task_id,
        title=task.title,
        priority=task.priority,
        status=task.status,
        dependencies=task.dependencies,
        assigned_agent=task.assigned_agent,
        worktree=task.worktree,
        status_notes=task.status_notes,
        estimated_effort=task.estimated_effort,
        completed=task.completed,
        blocked_reason=task.blocked_reason,
        blocked_by=task.blocked_by,
        last_heartbeat=task.last_heartbeat,
        created_at=task.created_at,
        updated_at=task.updated_at,
    )


@router.post("/{task_id}/claim", response_model=TaskResponse)
def claim_task(
    task_id: str, request: ClaimTaskRequest, db: Session = Depends(get_db)
) -> TaskResponse:
    """Claim a task - sets status to in_progress and assigns agent.

    Returns 409 Conflict if task is already claimed by another agent.
    """
    task = db.execute(select(Task).where(Task.task_id == task_id)).scalar_one_or_none()
    if not task:
        raise HTTPException(status_code=404, detail=f"Task {task_id} not found")

    if task.status == "in_progress" and task.assigned_agent:
        raise HTTPException(
            status_code=409,
            detail={
                "error": "Task already claimed",
                "task_id": task.task_id,
                "current_assignee": task.assigned_agent,
                "worktree": task.worktree,
                "claimed_at": task.updated_at.isoformat(),
            },
        )

    task.status = "in_progress"
    task.assigned_agent = request.agent_name
    task.worktree = request.worktree
    task.status_notes = f"Claimed by {request.agent_name} at {datetime.now(UTC).isoformat()}"
    db.commit()
    db.refresh(task)
    return TaskResponse(
        id=task.id,
        task_id=task.task_id,
        title=task.title,
        priority=task.priority,
        status=task.status,
        dependencies=task.dependencies,
        assigned_agent=task.assigned_agent,
        worktree=task.worktree,
        status_notes=task.status_notes,
        estimated_effort=task.estimated_effort,
        completed=task.completed,
        blocked_reason=task.blocked_reason,
        blocked_by=task.blocked_by,
        last_heartbeat=task.last_heartbeat,
        created_at=task.created_at,
        updated_at=task.updated_at,
    )


@router.post("/{task_id}/update-notes", response_model=TaskResponse)
def update_notes(
    task_id: str, request: UpdateNotesRequest, db: Session = Depends(get_db)
) -> TaskResponse:
    """Update status notes (appends to existing notes)."""
    task = db.execute(select(Task).where(Task.task_id == task_id)).scalar_one_or_none()
    if not task:
        raise HTTPException(status_code=404, detail=f"Task {task_id} not found")

    timestamp = task.updated_at
    new_note = f"\n[{timestamp}] {request.notes}"
    if task.status_notes:
        task.status_notes += new_note
    else:
        task.status_notes = new_note

    db.commit()
    db.refresh(task)
    return TaskResponse(
        id=task.id,
        task_id=task.task_id,
        title=task.title,
        priority=task.priority,
        status=task.status,
        dependencies=task.dependencies,
        assigned_agent=task.assigned_agent,
        worktree=task.worktree,
        status_notes=task.status_notes,
        estimated_effort=task.estimated_effort,
        completed=task.completed,
        blocked_reason=task.blocked_reason,
        blocked_by=task.blocked_by,
        last_heartbeat=task.last_heartbeat,
        created_at=task.created_at,
        updated_at=task.updated_at,
    )


@router.post("/{task_id}/set-status", response_model=TaskResponse)
def set_status(
    task_id: str, request: SetStatusRequest, db: Session = Depends(get_db)
) -> TaskResponse:
    """Change task status.

    When status is "blocked", accepts blocked_reason and blocked_by fields.
    """
    valid_statuses = ["pending", "in_progress", "blocked", "in_review", "done"]
    if request.status not in valid_statuses:
        raise HTTPException(
            status_code=400,
            detail=f"Invalid status. Must be one of: {', '.join(valid_statuses)}",
        )

    task = db.execute(select(Task).where(Task.task_id == task_id)).scalar_one_or_none()
    if not task:
        raise HTTPException(status_code=404, detail=f"Task {task_id} not found")

    task.status = request.status
    if request.status == "done":
        task.completed = True
    elif request.status == "blocked":
        task.blocked_reason = request.blocked_reason
        task.blocked_by = request.blocked_by
    else:
        task.blocked_reason = None
        task.blocked_by = None

    db.commit()
    db.refresh(task)
    return TaskResponse(
        id=task.id,
        task_id=task.task_id,
        title=task.title,
        priority=task.priority,
        status=task.status,
        dependencies=task.dependencies,
        assigned_agent=task.assigned_agent,
        worktree=task.worktree,
        status_notes=task.status_notes,
        estimated_effort=task.estimated_effort,
        completed=task.completed,
        blocked_reason=task.blocked_reason,
        blocked_by=task.blocked_by,
        last_heartbeat=task.last_heartbeat,
        created_at=task.created_at,
        updated_at=task.updated_at,
    )


@router.get("/by-status/{status}", response_model=list[TaskResponse])
def get_tasks_by_status(status: str, db: Session = Depends(get_db)) -> list[TaskResponse]:
    """Get all tasks with a specific status."""
    tasks = (
        db.execute(select(Task).where(Task.status == status).order_by(Task.task_id)).scalars().all()
    )
    return [
        TaskResponse(
            id=task.id,
            task_id=task.task_id,
            title=task.title,
            priority=task.priority,
            status=task.status,
            dependencies=task.dependencies,
            assigned_agent=task.assigned_agent,
            worktree=task.worktree,
            status_notes=task.status_notes,
            estimated_effort=task.estimated_effort,
            completed=task.completed,
            blocked_reason=task.blocked_reason,
            blocked_by=task.blocked_by,
            last_heartbeat=task.last_heartbeat,
            created_at=task.created_at,
            updated_at=task.updated_at,
        )
        for task in tasks
    ]


@router.get("/by-agent/{agent_name}", response_model=list[TaskResponse])
def get_tasks_by_agent(agent_name: str, db: Session = Depends(get_db)) -> list[TaskResponse]:
    """Get all tasks assigned to a specific agent."""
    tasks = (
        db.execute(select(Task).where(Task.assigned_agent == agent_name).order_by(Task.task_id))
        .scalars()
        .all()
    )
    return [
        TaskResponse(
            id=task.id,
            task_id=task.task_id,
            title=task.title,
            priority=task.priority,
            status=task.status,
            dependencies=task.dependencies,
            assigned_agent=task.assigned_agent,
            worktree=task.worktree,
            status_notes=task.status_notes,
            estimated_effort=task.estimated_effort,
            completed=task.completed,
            blocked_reason=task.blocked_reason,
            blocked_by=task.blocked_by,
            last_heartbeat=task.last_heartbeat,
            created_at=task.created_at,
            updated_at=task.updated_at,
        )
        for task in tasks
    ]


@router.post("/{task_id}/heartbeat", response_model=TaskResponse)
def heartbeat(
    task_id: str, request: HeartbeatRequest, db: Session = Depends(get_db)
) -> TaskResponse:
    """Update task heartbeat to show activity.

    Only allowed by the current assigned agent.
    Returns 403 if not assigned to the requesting agent.
    """
    task = db.execute(select(Task).where(Task.task_id == task_id)).scalar_one_or_none()
    if not task:
        raise HTTPException(status_code=404, detail=f"Task {task_id} not found")

    if task.assigned_agent != request.agent_name:
        raise HTTPException(
            status_code=403,
            detail=f"Task not assigned to {request.agent_name}. Assigned to {task.assigned_agent}",
        )

    task.last_heartbeat = datetime.now(UTC)
    db.commit()
    db.refresh(task)
    return TaskResponse(
        id=task.id,
        task_id=task.task_id,
        title=task.title,
        priority=task.priority,
        status=task.status,
        dependencies=task.dependencies,
        assigned_agent=task.assigned_agent,
        worktree=task.worktree,
        status_notes=task.status_notes,
        estimated_effort=task.estimated_effort,
        completed=task.completed,
        blocked_reason=task.blocked_reason,
        blocked_by=task.blocked_by,
        last_heartbeat=task.last_heartbeat,
        created_at=task.created_at,
        updated_at=task.updated_at,
    )


@router.post("/{task_id}/unclaim", response_model=TaskResponse)
def unclaim(task_id: str, request: UnclaimRequest, db: Session = Depends(get_db)) -> TaskResponse:
    """Unclaim a task - resets to pending status and clears assignment.

    Only allowed by the current assigned agent (or admin).
    Returns 403 if not assigned to the requesting agent.
    """
    task = db.execute(select(Task).where(Task.task_id == task_id)).scalar_one_or_none()
    if not task:
        raise HTTPException(status_code=404, detail=f"Task {task_id} not found")

    if task.assigned_agent != request.agent_name and request.agent_name != "admin":
        raise HTTPException(
            status_code=403,
            detail=f"Task not assigned to {request.agent_name}. Assigned to {task.assigned_agent}",
        )

    task.status = "pending"
    task.assigned_agent = None
    task.worktree = None
    timestamp = datetime.now(UTC).isoformat()
    new_note = f"\n[{timestamp}] Unclaimed by {request.agent_name}"
    if task.status_notes:
        task.status_notes += new_note
    else:
        task.status_notes = new_note
    db.commit()
    db.refresh(task)
    return TaskResponse(
        id=task.id,
        task_id=task.task_id,
        title=task.title,
        priority=task.priority,
        status=task.status,
        dependencies=task.dependencies,
        assigned_agent=task.assigned_agent,
        worktree=task.worktree,
        status_notes=task.status_notes,
        estimated_effort=task.estimated_effort,
        completed=task.completed,
        blocked_reason=task.blocked_reason,
        blocked_by=task.blocked_by,
        last_heartbeat=task.last_heartbeat,
        created_at=task.created_at,
        updated_at=task.updated_at,
    )


@router.post("/initialize", response_model=InitializeTasksResponse)
def initialize_tasks(db: Session = Depends(get_db)) -> InitializeTasksResponse:
    """Initialize all 12 PRD tasks in database from TASK_DATA (idempotent)."""
    tasks_created = 0
    tasks_updated = 0
    created_tasks = []

    for task_id, data in TASK_DATA.items():
        existing_task = db.execute(select(Task).where(Task.task_id == task_id)).scalar_one_or_none()

        if existing_task:
            existing_task.title = data["title"]
            existing_task.priority = data["priority"]
            existing_task.dependencies = data["dependencies"]
            existing_task.estimated_effort = data["estimated_effort"]
            tasks_updated += 1
            created_tasks.append(existing_task)
        else:
            new_task = Task(
                task_id=task_id,
                title=data["title"],
                priority=data["priority"],
                status="pending",
                dependencies=data["dependencies"],
                estimated_effort=data["estimated_effort"],
                completed=False,
            )
            db.add(new_task)
            tasks_created += 1
            created_tasks.append(new_task)

    db.commit()

    for task in created_tasks:
        db.refresh(task)

    return InitializeTasksResponse(
        message=f"Initialized {tasks_created} new tasks and updated {tasks_updated} existing tasks",
        tasks_created=tasks_created,
        tasks_updated=tasks_updated,
        tasks=[
            TaskResponse(
                id=task.id,
                task_id=task.task_id,
                title=task.title,
                priority=task.priority,
                status=task.status,
                dependencies=task.dependencies,
                assigned_agent=task.assigned_agent,
                worktree=task.worktree,
                status_notes=task.status_notes,
                estimated_effort=task.estimated_effort,
                completed=task.completed,
                blocked_reason=task.blocked_reason,
                blocked_by=task.blocked_by,
                last_heartbeat=task.last_heartbeat,
                created_at=task.created_at,
                updated_at=task.updated_at,
            )
            for task in created_tasks
        ],
    )
