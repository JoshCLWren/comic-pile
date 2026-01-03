"""Task API endpoints."""

import subprocess
from datetime import UTC, datetime, timedelta

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.database import get_db
from app.models import Task
from app.schemas.task import (
    ClaimTaskRequest,
    CreateTaskRequest,
    HeartbeatRequest,
    SetStatusRequest,
    TaskCoordinatorResponse,
    TaskResponse,
    UnclaimRequest,
    UpdateNotesRequest,
)

router = APIRouter(prefix="/tasks", tags=["tasks"])

INITIAL_TASKS = [
    {
        "task_id": "TASK-101",
        "title": "Complete Narrative Session Summaries",
        "description": "Review and document all session summaries for narrative continuity",
        "instructions": "Read through all session notes and create comprehensive summaries",
        "priority": "HIGH",
        "dependencies": None,
        "estimated_effort": "4 hours",
    },
    {
        "task_id": "TASK-102",
        "title": "Set Up Automated Testing Pipeline",
        "description": "Configure CI/CD pipeline with automated tests",
        "instructions": "Set up GitHub Actions with pytest and coverage reporting",
        "priority": "HIGH",
        "dependencies": None,
        "estimated_effort": "3 hours",
    },
    {
        "task_id": "TASK-103",
        "title": "Migrate Database Schema",
        "description": "Update database schema and create migration scripts",
        "instructions": "Use Alembic to create and apply migration",
        "priority": "HIGH",
        "dependencies": "TASK-102",
        "estimated_effort": "2 hours",
    },
    {
        "task_id": "TASK-104",
        "title": "Implement Worker Pool Manager",
        "description": "Create agent pool management system",
        "instructions": "Build worker pool with dynamic spawning capability",
        "priority": "HIGH",
        "dependencies": "TASK-101",
        "estimated_effort": "8 hours",
    },
    {
        "task_id": "TASK-105",
        "title": "Design Task Dependency Graph",
        "description": "Create visual representation of task dependencies",
        "instructions": "Design and implement dependency tracking",
        "priority": "MEDIUM",
        "dependencies": "TASK-103",
        "estimated_effort": "3 hours",
    },
    {
        "task_id": "TASK-106",
        "title": "Add Authentication Middleware",
        "description": "Implement user authentication for API endpoints",
        "instructions": "Add JWT-based authentication",
        "priority": "MEDIUM",
        "dependencies": None,
        "estimated_effort": "4 hours",
    },
    {
        "task_id": "TASK-107",
        "title": "Optimize Database Queries",
        "description": "Identify and optimize slow database queries",
        "instructions": "Profile queries and add indexes",
        "priority": "MEDIUM",
        "dependencies": "TASK-103",
        "estimated_effort": "2 hours",
    },
    {
        "task_id": "TASK-108",
        "title": "Create API Documentation",
        "description": "Document all REST API endpoints",
        "instructions": "Generate OpenAPI documentation",
        "priority": "MEDIUM",
        "dependencies": None,
        "estimated_effort": "3 hours",
    },
    {
        "task_id": "TASK-109",
        "title": "Implement Error Logging",
        "description": "Add centralized error logging and monitoring",
        "instructions": "Set up structured logging with error tracking",
        "priority": "LOW",
        "dependencies": "TASK-106",
        "estimated_effort": "2 hours",
    },
    {
        "task_id": "TASK-110",
        "title": "Add Performance Metrics",
        "description": "Track application performance metrics",
        "instructions": "Implement metrics collection and dashboard",
        "priority": "LOW",
        "dependencies": "TASK-109",
        "estimated_effort": "3 hours",
    },
    {
        "task_id": "TASK-111",
        "title": "Create User Guide",
        "description": "Write comprehensive user documentation",
        "instructions": "Document all features and use cases",
        "priority": "LOW",
        "dependencies": "TASK-108",
        "estimated_effort": "4 hours",
    },
    {
        "task_id": "TASK-112",
        "title": "Set Up Production Deployment",
        "description": "Configure production environment and deployment",
        "instructions": "Set up Docker and production database",
        "priority": "LOW",
        "dependencies": "TASK-103, TASK-107",
        "estimated_effort": "4 hours",
    },
]


@router.post("/initialize")
async def initialize_tasks(db: Session = Depends(get_db)):
    """Initialize database with sample tasks."""
    tasks_created = 0
    tasks_updated = 0

    for task_data in INITIAL_TASKS:
        existing_task = db.execute(
            select(Task).where(Task.task_id == task_data["task_id"])
        ).scalar_one_or_none()

        if existing_task:
            existing_task.title = task_data["title"]
            existing_task.description = task_data["description"]
            existing_task.instructions = task_data["instructions"]
            existing_task.priority = task_data["priority"]
            existing_task.dependencies = task_data["dependencies"]
            existing_task.estimated_effort = task_data["estimated_effort"]
            tasks_updated += 1
        else:
            task = Task(
                task_id=task_data["task_id"],
                title=task_data["title"],
                description=task_data["description"],
                instructions=task_data["instructions"],
                priority=task_data["priority"],
                dependencies=task_data["dependencies"],
                estimated_effort=task_data["estimated_effort"],
                status="pending",
                completed=False,
            )
            db.add(task)
            tasks_created += 1

    db.commit()

    tasks = db.execute(select(Task).order_by(Task.id)).scalars().all()

    return {
        "message": "Tasks initialized successfully",
        "tasks_created": tasks_created,
        "tasks_updated": tasks_updated,
        "tasks": [
            TaskResponse(
                id=task.id,
                task_id=task.task_id,
                title=task.title,
                description=task.description,
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
                instructions=task.instructions,
                created_at=task.created_at,
                updated_at=task.updated_at,
            )
            for task in tasks
        ],
    }


INITIAL_TASKS = [
    {
        "task_id": "TASK-101",
        "title": "Complete Narrative Session Summaries",
        "description": "Review and document all session summaries for narrative continuity",
        "instructions": "Read through all session notes and create comprehensive summaries",
        "priority": "HIGH",
        "dependencies": None,
        "estimated_effort": "4 hours",
    },
    {
        "task_id": "TASK-102",
        "title": "Set Up Automated Testing Pipeline",
        "description": "Configure CI/CD pipeline with automated tests",
        "instructions": "Set up GitHub Actions with pytest and coverage reporting",
        "priority": "HIGH",
        "dependencies": None,
        "estimated_effort": "3 hours",
    },
    {
        "task_id": "TASK-103",
        "title": "Migrate Database Schema",
        "description": "Update database schema and create migration scripts",
        "instructions": "Use Alembic to create and apply migration",
        "priority": "HIGH",
        "dependencies": "TASK-102",
        "estimated_effort": "2 hours",
    },
    {
        "task_id": "TASK-104",
        "title": "Implement Worker Pool Manager",
        "description": "Create agent pool management system",
        "instructions": "Build worker pool with dynamic spawning capability",
        "priority": "HIGH",
        "dependencies": "TASK-101",
        "estimated_effort": "8 hours",
    },
    {
        "task_id": "TASK-105",
        "title": "Design Task Dependency Graph",
        "description": "Create visual representation of task dependencies",
        "instructions": "Design and implement dependency tracking",
        "priority": "MEDIUM",
        "dependencies": "TASK-103",
        "estimated_effort": "3 hours",
    },
    {
        "task_id": "TASK-106",
        "title": "Add Authentication Middleware",
        "description": "Implement user authentication for API endpoints",
        "instructions": "Add JWT-based authentication",
        "priority": "MEDIUM",
        "dependencies": None,
        "estimated_effort": "4 hours",
    },
    {
        "task_id": "TASK-107",
        "title": "Optimize Database Queries",
        "description": "Identify and optimize slow database queries",
        "instructions": "Profile queries and add indexes",
        "priority": "MEDIUM",
        "dependencies": "TASK-103",
        "estimated_effort": "2 hours",
    },
    {
        "task_id": "TASK-108",
        "title": "Create API Documentation",
        "description": "Document all REST API endpoints",
        "instructions": "Generate OpenAPI documentation",
        "priority": "MEDIUM",
        "dependencies": None,
        "estimated_effort": "3 hours",
    },
    {
        "task_id": "TASK-109",
        "title": "Implement Error Logging",
        "description": "Add centralized error logging and monitoring",
        "instructions": "Set up structured logging with error tracking",
        "priority": "LOW",
        "dependencies": "TASK-106",
        "estimated_effort": "2 hours",
    },
    {
        "task_id": "TASK-110",
        "title": "Add Performance Metrics",
        "description": "Track application performance metrics",
        "instructions": "Implement metrics collection and dashboard",
        "priority": "LOW",
        "dependencies": "TASK-109",
        "estimated_effort": "3 hours",
    },
    {
        "task_id": "TASK-111",
        "title": "Create User Guide",
        "description": "Write comprehensive user documentation",
        "instructions": "Document all features and use cases",
        "priority": "LOW",
        "dependencies": "TASK-108",
        "estimated_effort": "4 hours",
    },
    {
        "task_id": "TASK-112",
        "title": "Set Up Production Deployment",
        "description": "Configure production environment and deployment",
        "instructions": "Set up Docker and production database",
        "priority": "LOW",
        "dependencies": "TASK-103, TASK-107",
        "estimated_effort": "4 hours",
    },
]


@router.get("/", response_model=list[TaskResponse])
def list_tasks(db: Session = Depends(get_db)) -> list[TaskResponse]:
    """List all tasks with their current state."""
    tasks = db.execute(select(Task).order_by(Task.task_id)).scalars().all()
    return [
        TaskResponse(
            id=task.id,
            task_id=task.task_id,
            title=task.title,
            description=task.description,
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
            instructions=task.instructions,
            created_at=task.created_at,
            updated_at=task.updated_at,
        )
        for task in tasks
    ]


@router.post("/", response_model=TaskResponse, status_code=201)
def create_task(request: CreateTaskRequest, db: Session = Depends(get_db)) -> TaskResponse:
    """Create a new task."""
    existing_task = db.execute(
        select(Task).where(Task.task_id == request.task_id)
    ).scalar_one_or_none()
    if existing_task:
        raise HTTPException(status_code=400, detail=f"Task {request.task_id} already exists")

    new_task = Task(
        task_id=request.task_id,
        title=request.title,
        description=request.description,
        instructions=request.instructions,
        priority=request.priority,
        dependencies=request.dependencies,
        estimated_effort=request.estimated_effort,
        status="pending",
        completed=False,
    )
    db.add(new_task)
    db.commit()
    db.refresh(new_task)
    return TaskResponse(
        id=new_task.id,
        task_id=new_task.task_id,
        title=new_task.title,
        description=new_task.description,
        priority=new_task.priority,
        status=new_task.status,
        dependencies=new_task.dependencies,
        assigned_agent=new_task.assigned_agent,
        worktree=new_task.worktree,
        status_notes=new_task.status_notes,
        estimated_effort=new_task.estimated_effort,
        completed=new_task.completed,
        blocked_reason=new_task.blocked_reason,
        blocked_by=new_task.blocked_by,
        last_heartbeat=new_task.last_heartbeat,
        instructions=new_task.instructions,
        created_at=new_task.created_at,
        updated_at=new_task.updated_at,
    )


@router.post("/bulk", response_model=list[TaskResponse])
def create_tasks_bulk(
    requests: list[CreateTaskRequest], db: Session = Depends(get_db)
) -> list[TaskResponse]:
    """Create multiple tasks in one transaction."""
    created_tasks = []
    for request in requests:
        existing_task = db.execute(
            select(Task).where(Task.task_id == request.task_id)
        ).scalar_one_or_none()
        if existing_task:
            raise HTTPException(status_code=400, detail=f"Task {request.task_id} already exists")

        new_task = Task(
            task_id=request.task_id,
            title=request.title,
            description=request.description,
            instructions=request.instructions,
            priority=request.priority,
            dependencies=request.dependencies,
            estimated_effort=request.estimated_effort,
            status="pending",
            completed=False,
        )
        db.add(new_task)
        created_tasks.append(new_task)

    db.commit()

    for task in created_tasks:
        db.refresh(task)

    return [
        TaskResponse(
            id=task.id,
            task_id=task.task_id,
            title=task.title,
            description=task.description,
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
            instructions=task.instructions,
            created_at=task.created_at,
            updated_at=task.updated_at,
        )
        for task in created_tasks
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
            description=task.description,
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
            instructions=task.instructions,
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
            description=task.description,
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
            instructions=task.instructions,
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


@router.get("/stale", response_model=list[TaskResponse])
def get_stale_tasks(db: Session = Depends(get_db)) -> list[TaskResponse]:
    """Get tasks with last heartbeat > 20 minutes ago and status in_progress."""
    threshold = datetime.now(UTC) - timedelta(minutes=20)
    tasks = (
        db.execute(
            select(Task)
            .where(Task.status == "in_progress", Task.last_heartbeat < threshold)
            .order_by(Task.last_heartbeat.asc())
        )
        .scalars()
        .all()
    )
    return [
        TaskResponse(
            id=task.id,
            task_id=task.task_id,
            title=task.title,
            description=task.description,
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
            instructions=task.instructions,
            created_at=task.created_at,
            updated_at=task.updated_at,
        )
        for task in tasks
    ]


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
        description=task.description,
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
        instructions=task.instructions,
        created_at=task.created_at,
        updated_at=task.updated_at,
    )


@router.get("/{task_id}/history", response_model=list[dict])
def get_task_history(task_id: str, db: Session = Depends(get_db)) -> list[dict]:
    """Get audit trail of task status changes."""
    task = db.execute(select(Task).where(Task.task_id == task_id)).scalar_one_or_none()
    if not task:
        raise HTTPException(status_code=404, detail=f"Task {task_id} not found")

    history = []
    if task.status_notes:
        lines = task.status_notes.split("\n")
        for line in lines:
            if not line.strip():
                continue
            if line.startswith("[") and "] " in line:
                try:
                    timestamp_end = line.index("]")
                    timestamp = line[1:timestamp_end]
                    event = line[timestamp_end + 2 :]
                    history.append({"timestamp": timestamp, "event": event})
                except (ValueError, IndexError):
                    history.append({"timestamp": None, "event": line})
            else:
                history.append({"timestamp": None, "event": line})

    return history


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

    if task.assigned_agent:
        raise HTTPException(
            status_code=409,
            detail={
                "error": "Task already claimed",
                "task_id": task.task_id,
                "current_assignee": task.assigned_agent,
                "worktree": task.worktree,
                "current_status": task.status,
                "claimed_at": task.updated_at.isoformat(),
            },
        )

    import os

    skip_worktree_check = os.getenv("SKIP_WORKTREE_CHECK", "false").lower() == "true"
    if not skip_worktree_check:
        result = subprocess.run(
            ["git", "worktree", "list"],
            capture_output=True,
            text=True,
        )
        if request.worktree not in result.stdout:
            worktree_path = os.path.join(os.path.dirname(os.getcwd()), request.worktree)
            if not os.path.exists(worktree_path):
                raise HTTPException(
                    status_code=400,
                    detail=f"Worktree {request.worktree} does not exist. Please create it first with: git worktree add ../{request.worktree} <branch>",
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
        description=task.description,
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
        instructions=task.instructions,
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

    timestamp = datetime.now(UTC).isoformat()
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
        description=task.description,
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
        instructions=task.instructions,
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
        description=task.description,
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
        instructions=task.instructions,
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
            description=task.description,
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
            instructions=task.instructions,
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
            description=task.description,
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
            instructions=task.instructions,
            created_at=task.created_at,
            updated_at=task.updated_at,
        )
        for task in tasks
    ]


@router.get("/by-priority/{priority}", response_model=list[TaskResponse])
def get_tasks_by_priority(priority: str, db: Session = Depends(get_db)) -> list[TaskResponse]:
    """Get all tasks with a specific priority."""
    valid_priorities = ["HIGH", "MEDIUM", "LOW"]
    if priority not in valid_priorities:
        raise HTTPException(
            status_code=400,
            detail=f"Invalid priority. Must be one of: {', '.join(valid_priorities)}",
        )
    tasks = (
        db.execute(select(Task).where(Task.priority == priority).order_by(Task.task_id))
        .scalars()
        .all()
    )
    return [
        TaskResponse(
            id=task.id,
            task_id=task.task_id,
            title=task.title,
            description=task.description,
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
            instructions=task.instructions,
            created_at=task.created_at,
            updated_at=task.updated_at,
        )
        for task in tasks
    ]


@router.get("/completed", response_model=list[TaskResponse])
def get_completed_tasks(db: Session = Depends(get_db)) -> list[TaskResponse]:
    """Get all completed tasks."""
    tasks = db.execute(select(Task).where(Task.completed).order_by(Task.task_id)).scalars().all()
    return [
        TaskResponse(
            id=task.id,
            task_id=task.task_id,
            title=task.title,
            description=task.description,
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
            instructions=task.instructions,
            created_at=task.created_at,
            updated_at=task.updated_at,
        )
        for task in tasks
    ]


@router.get("/not-completed", response_model=list[TaskResponse])
def get_not_completed_tasks(db: Session = Depends(get_db)) -> list[TaskResponse]:
    """Get all tasks that are not completed."""
    tasks = db.execute(select(Task).where(~Task.completed).order_by(Task.task_id)).scalars().all()
    return [
        TaskResponse(
            id=task.id,
            task_id=task.task_id,
            title=task.title,
            description=task.description,
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
            instructions=task.instructions,
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
        description=task.description,
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
        instructions=task.instructions,
        created_at=task.created_at,
        updated_at=task.updated_at,
    )


@router.post("/{task_id}/unclaim", response_model=TaskResponse)
def unclaim(task_id: str, request: UnclaimRequest, db: Session = Depends(get_db)) -> TaskResponse:
    """Unclaim a task - clears assignment, but preserves in_review status.

    Only allowed by the current assigned agent (or admin).
    Returns 403 if not assigned to the requesting agent.
    in_review tasks remain in_review; in_progress tasks are reset to pending.
    """
    task = db.execute(select(Task).where(Task.task_id == task_id)).scalar_one_or_none()
    if not task:
        raise HTTPException(status_code=404, detail=f"Task {task_id} not found")

    if task.assigned_agent != request.agent_name and request.agent_name != "admin":
        raise HTTPException(
            status_code=403,
            detail=f"Task not assigned to {request.agent_name}. Assigned to {task.assigned_agent}",
        )

    if task.status != "in_review":
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
        description=task.description,
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
        instructions=task.instructions,
        created_at=task.created_at,
        updated_at=task.updated_at,
    )


@router.post("/{task_id}/merge-to-main")
async def merge_task_to_main(task_id: str, db: Session = Depends(get_db)) -> dict:
    """Merge a task's worktree to main automatically."""
    task = db.execute(select(Task).where(Task.task_id == task_id)).scalar_one_or_none()

    if not task:
        raise HTTPException(404, "Task not found")

    if task.status != "in_review":
        raise HTTPException(
            400,
            f"Task must be in_review, current status: {task.status}",
        )

    if not task.worktree:
        raise HTTPException(400, "No worktree assigned to task")

    worktree_path = task.worktree
    import os

    full_worktree_path = os.path.join(os.path.dirname(os.getcwd()), worktree_path)

    if not os.path.exists(full_worktree_path):
        raise HTTPException(400, f"Worktree not found: {worktree_path}")

    os.chdir(full_worktree_path)

    result = subprocess.run(
        ["git", "fetch", "origin", "main"],
        capture_output=True,
        text=True,
    )

    if result.returncode != 0:
        raise HTTPException(500, f"Failed to fetch main: {result.stderr}")

    result = subprocess.run(
        ["git", "merge", "origin/main", "--no-ff"],
        capture_output=True,
        text=True,
    )

    if "CONFLICT" in result.stdout or result.returncode != 0:
        task.status = "blocked"
        task.blocked_reason = "Merge conflict detected"
        merge_note = f"\n[{datetime.now(UTC).isoformat()}] Auto-merge failed: git merge conflict\n{result.stdout}"
        if task.status_notes:
            task.status_notes += merge_note
        else:
            task.status_notes = merge_note
        db.commit()

        return {
            "success": False,
            "reason": "merge_conflict",
            "output": result.stdout[:500],
        }

    result = subprocess.run(
        ["git", "push", "origin", "HEAD:main"],
        capture_output=True,
        text=True,
    )

    if result.returncode != 0:
        raise HTTPException(500, f"Failed to push: {result.stderr}")

    task.status = "done"
    task.completed = True
    timestamp = datetime.now(UTC).isoformat()
    merge_note = f"\n[{timestamp}] Merged to main by auto-merge"
    if task.status_notes:
        task.status_notes += merge_note
    else:
        task.status_notes = merge_note
    db.commit()

    return {
        "success": True,
        "message": "Merged to main successfully",
    }
