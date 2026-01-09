"""Task API endpoints."""

import subprocess
from datetime import UTC, datetime, timedelta

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import HTMLResponse, JSONResponse
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.database import get_db
from app.middleware import limiter
from app.models import Task
from app.schemas.task import (
    ClaimTaskRequest,
    CreateTaskRequest,
    HeartbeatRequest,
    PatchTaskRequest,
    SetStatusRequest,
    SetWorktreeRequest,
    TaskCoordinatorResponse,
    TaskResponse,
    UnclaimRequest,
    UpdateNotesRequest,
)

router = APIRouter(prefix="/tasks", tags=["tasks"])
health_router = APIRouter(tags=["health"])

_manager_daemon_last_review: datetime | None = None
_manager_daemon_active: bool = False


def set_manager_daemon_active(active: bool) -> None:
    """Set manager daemon active status."""
    global _manager_daemon_active
    _manager_daemon_active = active


def update_manager_daemon_last_review(timestamp: datetime) -> None:
    """Update manager daemon last review timestamp."""
    global _manager_daemon_last_review
    _manager_daemon_last_review = timestamp


@health_router.get("/manager-daemon/health")
def get_manager_daemon_health() -> dict:
    """Get manager daemon health status."""
    status = "OK" if _manager_daemon_active else "NOT_RUNNING"
    return {
        "status": status,
        "last_review": _manager_daemon_last_review.isoformat()
        if _manager_daemon_last_review
        else None,
        "daemon_active": _manager_daemon_active,
    }


@health_router.get("/health")
def health_check(db: Session = Depends(get_db)) -> dict:
    """Health check endpoint that verifies all components."""
    database_status = "connected"
    try:
        db.execute(select(Task).limit(1))
    except Exception:
        database_status = "disconnected"

    manager_daemon_status = "OK" if _manager_daemon_active else "NOT_RUNNING"

    overall_status = "healthy"
    if database_status != "connected":
        overall_status = "unhealthy"

    return {
        "status": overall_status,
        "database": database_status,
        "task_api": "OK",
        "manager_daemon": manager_daemon_status,
    }


@health_router.post("/manager-daemon/health/set-active")
def set_daemon_active(request: dict) -> dict:
    """Set manager daemon active status."""
    active = request.get("active", False)
    set_manager_daemon_active(active)
    status = "active" if _manager_daemon_active else "inactive"
    return {"status": status}


@health_router.post("/manager-daemon/health/update-last-review")
def update_last_review() -> dict:
    """Update manager daemon last review timestamp."""
    timestamp = datetime.now(UTC)
    update_manager_daemon_last_review(timestamp)
    return {"last_review": timestamp.isoformat()}


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
                task_type=task.task_type,
                session_id=task.session_id,
                session_start_time=task.session_start_time,
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
@limiter.limit("200/minute")
def list_tasks(request: Request, db: Session = Depends(get_db)) -> list[TaskResponse]:
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
            task_type=task.task_type,
            session_id=task.session_id,
            session_start_time=task.session_start_time,
            created_at=task.created_at,
            updated_at=task.updated_at,
        )
        for task in tasks
    ]


@router.post("/", response_model=TaskResponse, status_code=201)
@limiter.limit("60/minute")
def create_task(
    request: Request,
    create_request: CreateTaskRequest,
    db: Session = Depends(get_db),
    session_id: str | None = None,
) -> TaskResponse:
    """Create a new task."""
    from sqlalchemy.exc import IntegrityError

    new_task = Task(
        task_id=create_request.task_id,
        title=create_request.title,
        description=create_request.description,
        instructions=create_request.instructions,
        priority=create_request.priority,
        dependencies=create_request.dependencies,
        estimated_effort=create_request.estimated_effort,
        task_type=create_request.task_type,
        status="pending",
        completed=False,
        session_id=session_id,
        session_start_time=datetime.now(UTC) if session_id else None,
    )
    db.add(new_task)
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        existing_task = db.execute(
            select(Task).where(Task.task_id == create_request.task_id)
        ).scalar_one_or_none()
        if existing_task:
            raise HTTPException(
                status_code=400, detail=f"Task {create_request.task_id} already exists"
            ) from None
        raise
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
        task_type=new_task.task_type,
        session_id=new_task.session_id,
        session_start_time=new_task.session_start_time,
        created_at=new_task.created_at,
        updated_at=new_task.updated_at,
    )


@router.post("/bulk", response_model=list[TaskResponse])
def create_tasks_bulk(
    requests: list[CreateTaskRequest], db: Session = Depends(get_db)
) -> list[TaskResponse]:
    """Create multiple tasks in one transaction."""
    from sqlalchemy.exc import IntegrityError

    created_tasks = []
    for request in requests:
        new_task = Task(
            task_id=request.task_id,
            title=request.title,
            description=request.description,
            instructions=request.instructions,
            priority=request.priority,
            dependencies=request.dependencies,
            estimated_effort=request.estimated_effort,
            task_type=request.task_type,
            status="pending",
            completed=False,
        )
        db.add(new_task)
        created_tasks.append(new_task)

    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        for task in created_tasks:
            existing = db.execute(
                select(Task).where(Task.task_id == task.task_id)
            ).scalar_one_or_none()
            if existing:
                raise HTTPException(
                    status_code=400, detail=f"Task {task.task_id} already exists"
                ) from None
        raise

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
            task_type=task.task_type,
            session_id=task.session_id,
            session_start_time=task.session_start_time,
            created_at=task.created_at,
            updated_at=task.updated_at,
        )
        for task in created_tasks
    ]


@router.get("/ready", response_model=list[TaskResponse])
@limiter.limit("200/minute")
def get_ready_tasks(request: Request, db: Session = Depends(get_db)) -> list[TaskResponse]:
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
            task_type=task.task_type,
            session_id=task.session_id,
            session_start_time=task.session_start_time,
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
            task_type=task.task_type,
            session_id=task.session_id,
            session_start_time=task.session_start_time,
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
            task_type=task.task_type,
            session_id=task.session_id,
            session_start_time=task.session_start_time,
            created_at=task.created_at,
            updated_at=task.updated_at,
        )
        for task in tasks
    ]


@router.get("/metrics", response_model=dict)
def get_metrics(db: Session = Depends(get_db)) -> dict:
    """Get task completion metrics and analytics data."""
    all_tasks = db.execute(select(Task).order_by(Task.task_id)).scalars().all()

    total_tasks = len(all_tasks)

    tasks_by_status = {"pending": 0, "in_progress": 0, "blocked": 0, "in_review": 0, "done": 0}
    tasks_by_priority = {"HIGH": 0, "MEDIUM": 0, "LOW": 0}
    tasks_by_type = {}
    recent_completions = []
    active_agents = {}

    completed_tasks_with_time = []

    for task in all_tasks:
        tasks_by_status[task.status] = tasks_by_status.get(task.status, 0) + 1
        if task.priority in tasks_by_priority:
            tasks_by_priority[task.priority] += 1

        task_type = task.task_type or "feature"
        tasks_by_type[task_type] = tasks_by_type.get(task_type, 0) + 1

        if task.status == "done" and task.updated_at:
            completed_tasks_with_time.append(task)
            if len(recent_completions) < 10:
                recent_completions.append(
                    {
                        "task_id": task.task_id,
                        "title": task.title,
                        "completed_at": task.updated_at,
                        "completed_by": task.assigned_agent or "unknown",
                    }
                )

        if task.status == "in_progress" and task.assigned_agent:
            if task.assigned_agent not in active_agents:
                active_agents[task.assigned_agent] = {
                    "agent_name": task.assigned_agent,
                    "active_tasks": 0,
                    "task_ids": [],
                }
            active_agents[task.assigned_agent]["active_tasks"] += 1
            active_agents[task.assigned_agent]["task_ids"].append(task.task_id)

    completion_rate = (tasks_by_status["done"] / total_tasks * 100) if total_tasks > 0 else 0.0

    average_completion_time_hours = None
    if completed_tasks_with_time:
        completion_times_hours = []
        for task in completed_tasks_with_time:
            if task.created_at and task.updated_at:
                duration_hours = (task.updated_at - task.created_at).total_seconds() / 3600
                completion_times_hours.append(duration_hours)
        if completion_times_hours:
            average_completion_time_hours = sum(completion_times_hours) / len(
                completion_times_hours
            )

    stale_threshold = datetime.now(UTC) - timedelta(minutes=20)
    stale_tasks_count = len(
        [
            t
            for t in all_tasks
            if t.status == "in_progress"
            and t.last_heartbeat
            and (
                (t.last_heartbeat.tzinfo is not None and t.last_heartbeat < stale_threshold)
                or (
                    t.last_heartbeat.tzinfo is None
                    and t.last_heartbeat.replace(tzinfo=UTC) < stale_threshold
                )
            )
        ]
    )

    blocked_tasks_count = len([t for t in all_tasks if t.status == "blocked"])

    ready_to_claim = 0
    for task in all_tasks:
        if task.status == "pending" and not task.blocked_reason:
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
                ready_to_claim += 1

    return {
        "total_tasks": total_tasks,
        "tasks_by_status": tasks_by_status,
        "tasks_by_priority": tasks_by_priority,
        "tasks_by_type": tasks_by_type,
        "completion_rate": round(completion_rate, 2),
        "average_completion_time_hours": (
            round(average_completion_time_hours, 2) if average_completion_time_hours else None
        ),
        "recent_completions": recent_completions,
        "active_agents": list(active_agents.values()),
        "stale_tasks_count": stale_tasks_count,
        "blocked_tasks_count": blocked_tasks_count,
        "ready_to_claim": ready_to_claim,
    }


@router.get("/search")
def search_tasks(
    request: Request,
    q: str | None = None,
    task_type: str | None = None,
    priority: str | None = None,
    status: str | None = None,
    assigned_agent: str | None = None,
    page: int = 1,
    page_size: int = 20,
    db: Session = Depends(get_db),
):
    """Search tasks with filters and pagination.

    Args:
        request: FastAPI request object
        q: Text search across task_id, title, and description (case-insensitive)
        task_type: Filter by task type
        priority: Filter by priority (HIGH, MEDIUM, LOW)
        status: Filter by status
        assigned_agent: Filter by assigned agent
        page: Page number (1-indexed)
        page_size: Number of results per page (1-100)
        db: Database session

    Returns:
        HTML fragment with search results for HTMX requests
        JSON dict for direct API calls
    """
    from fastapi.templating import Jinja2Templates

    query = select(Task)

    if q:
        search_pattern = f"%{q}%"
        query = query.where(
            (Task.task_id.ilike(search_pattern))
            | (Task.title.ilike(search_pattern))
            | (Task.description.ilike(search_pattern))
        )

    if task_type:
        query = query.where(Task.task_type == task_type)

    if priority:
        valid_priorities = ["HIGH", "MEDIUM", "LOW"]
        if priority not in valid_priorities:
            raise HTTPException(
                status_code=400,
                detail=f"Invalid priority. Must be one of: {', '.join(valid_priorities)}",
            )
        query = query.where(Task.priority == priority)

    if status:
        query = query.where(Task.status == status)

    if assigned_agent:
        query = query.where(Task.assigned_agent == assigned_agent)

    query = query.order_by(Task.task_id)

    offset = (page - 1) * page_size
    query = query.offset(offset).limit(page_size)

    tasks = db.execute(query).scalars().all()

    total_query = select(func.count(Task.id))
    if q:
        search_pattern = f"%{q}%"
        total_query = total_query.where(
            (Task.task_id.ilike(search_pattern))
            | (Task.title.ilike(search_pattern))
            | (Task.description.ilike(search_pattern))
        )
    if task_type:
        total_query = total_query.where(Task.task_type == task_type)
    if priority:
        total_query = total_query.where(Task.priority == priority)
    if status:
        total_query = total_query.where(Task.status == status)
    if assigned_agent:
        total_query = total_query.where(Task.assigned_agent == assigned_agent)

    total_count = db.execute(total_query).scalar()
    if total_count is None:
        total_count = 0
    total_pages = (total_count + page_size - 1) // page_size

    task_responses = [
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
            task_type=task.task_type,
            session_id=task.session_id,
            session_start_time=task.session_start_time,
            created_at=task.created_at,
            updated_at=task.updated_at,
        )
        for task in tasks
    ]

    search_results = {
        "tasks": [task.model_dump(mode="json") for task in task_responses],
        "pagination": {
            "page": page,
            "page_size": page_size,
            "total_count": total_count,
            "total_pages": total_pages,
            "has_next": page < total_pages,
            "has_prev": page > 1,
        },
    }

    is_htmx = request.headers.get("hx-request") is not None

    if is_htmx:
        from fastapi.templating import Jinja2Templates

        templates = Jinja2Templates(directory="app/templates")
        template = templates.get_template("_search_results.html")
        return HTMLResponse(content=template.render(search_results=search_results))
    else:
        return JSONResponse(content=search_results)


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
        task_type=task.task_type,
        session_id=task.session_id,
        session_start_time=task.session_start_time,
        created_at=task.created_at,
        updated_at=task.updated_at,
    )


@router.patch("/{task_id}", response_model=TaskResponse)
def patch_task(
    task_id: str, request: PatchTaskRequest, db: Session = Depends(get_db)
) -> TaskResponse:
    """Partially update a task by ID."""
    task = db.execute(select(Task).where(Task.task_id == task_id)).scalar_one_or_none()
    if not task:
        raise HTTPException(status_code=404, detail=f"Task {task_id} not found")

    if request.title is not None:
        task.title = request.title
    if request.description is not None:
        task.description = request.description
    if request.priority is not None:
        valid_priorities = ["HIGH", "MEDIUM", "LOW"]
        if request.priority not in valid_priorities:
            raise HTTPException(
                status_code=400,
                detail=f"Invalid priority. Must be one of: {', '.join(valid_priorities)}",
            )
        task.priority = request.priority
    if request.instructions is not None:
        task.instructions = request.instructions
    if request.dependencies is not None:
        task.dependencies = request.dependencies
    if request.estimated_effort is not None:
        task.estimated_effort = request.estimated_effort
    if request.task_type is not None:
        valid_task_types = [
            "feature",
            "bug_fix",
            "test_failure",
            "conflict",
            "documentation",
            "browser_test",
        ]
        if request.task_type not in valid_task_types:
            raise HTTPException(
                status_code=400,
                detail=f"Invalid task_type. Must be one of: {', '.join(valid_task_types)}",
            )
        task.task_type = request.task_type

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
        task_type=task.task_type,
        session_id=task.session_id,
        session_start_time=task.session_start_time,
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
    Returns 403 Forbidden if worker_type cannot claim this task_type.
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

    allowed_types = {
        "test-fixer": ["test_failure"],
        "conflict-resolver": ["conflict"],
        "browser-tester": ["browser_test"],
        "docs-writer": ["documentation"],
        "general-worker": ["feature", "bug_fix"],
    }

    if request.worker_type and request.worker_type in allowed_types:
        if task.task_type not in allowed_types[request.worker_type]:
            raise HTTPException(
                status_code=403,
                detail=f"{request.worker_type} cannot claim {task.task_type} tasks. Allowed types: {allowed_types[request.worker_type]}",
            )

    import os

    skip_worktree_check = os.getenv("SKIP_WORKTREE_CHECK", "false").lower() == "true"
    if not skip_worktree_check:
        result = subprocess.run(
            ["git", "worktree", "list"],
            capture_output=True,
            text=True,
        )

        worktree_path = (
            request.worktree
            if os.path.isabs(request.worktree)
            else os.path.join(os.path.dirname(os.getcwd()), request.worktree)
        )

        if request.worktree not in result.stdout:
            if os.path.exists(worktree_path):
                raise HTTPException(
                    status_code=400,
                    detail=f"Worktree {request.worktree} exists but is not a valid git worktree. Please remove the directory or register it as a worktree.",
                )

            auto_create_worktree = os.getenv("AUTO_CREATE_WORKTREE", "false").lower() == "true"
            if not auto_create_worktree:
                raise HTTPException(
                    status_code=400,
                    detail=f"Worktree {request.worktree} does not exist. Please create it first with: git worktree add ../{request.worktree} <branch>",
                )

            branch_name = f"task/{task.task_id}"
            result = subprocess.run(
                ["git", "checkout", "-b", branch_name],
                capture_output=True,
                text=True,
            )
            if result.returncode != 0:
                raise HTTPException(
                    status_code=500,
                    detail=f"Failed to create branch {branch_name}: {result.stderr}",
                )

            result = subprocess.run(
                ["git", "worktree", "add", worktree_path, branch_name],
                capture_output=True,
                text=True,
            )
            if result.returncode != 0:
                subprocess.run(["git", "checkout", "main"], capture_output=True)
                subprocess.run(["git", "branch", "-D", branch_name], capture_output=True)
                raise HTTPException(
                    status_code=500,
                    detail=f"Failed to create worktree at {worktree_path}: {result.stderr}",
                )

            subprocess.run(["git", "checkout", "main"], capture_output=True)

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
        task_type=task.task_type,
        session_id=task.session_id,
        session_start_time=task.session_start_time,
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
        task_type=task.task_type,
        session_id=task.session_id,
        session_start_time=task.session_start_time,
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

    if request.status == "in_review":
        if not task.worktree:
            raise HTTPException(
                status_code=400,
                detail="Cannot set status to in_review without a valid worktree",
            )
        import os

        skip_worktree_check = os.getenv("SKIP_WORKTREE_CHECK", "false").lower() == "true"
        if not skip_worktree_check:
            result = subprocess.run(
                ["git", "worktree", "list"],
                capture_output=True,
                text=True,
            )
            worktree_path = (
                task.worktree
                if os.path.isabs(task.worktree)
                else os.path.join(os.path.dirname(os.getcwd()), task.worktree)
            )
            if task.worktree not in result.stdout:
                if not os.path.exists(worktree_path):
                    raise HTTPException(
                        status_code=400,
                        detail=f"Worktree {task.worktree} does not exist or is not a valid git worktree",
                    )

            os.chdir(worktree_path)

            result = subprocess.run(
                ["pytest", "-x", "--tb=short"],
                capture_output=True,
                text=True,
                timeout=300,
            )
            if result.returncode != 0:
                error_output = result.stdout[-500:] if result.stdout else "no output"
                raise HTTPException(
                    status_code=400,
                    detail=f"Tests must pass before marking in_review. Pytest output:\n{error_output}",
                )

            result = subprocess.run(
                ["bash", "scripts/lint.sh"],
                capture_output=True,
                text=True,
                timeout=120,
            )
            if result.returncode != 0:
                error_output = result.stderr[-300:] if result.stderr else "no output"
                raise HTTPException(
                    status_code=400,
                    detail=f"Linting must pass before marking in_review. Lint output:\n{error_output}",
                )

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
        task_type=task.task_type,
        session_id=task.session_id,
        session_start_time=task.session_start_time,
        created_at=task.created_at,
        updated_at=task.updated_at,
    )


@router.post("/{task_id}/set-worktree", response_model=TaskResponse)
def set_worktree(
    task_id: str, request: SetWorktreeRequest, db: Session = Depends(get_db)
) -> TaskResponse:
    """Set task worktree (admin endpoint for in_review tasks with missing worktree)."""
    task = db.execute(select(Task).where(Task.task_id == task_id)).scalar_one_or_none()
    if not task:
        raise HTTPException(status_code=404, detail=f"Task {task_id} not found")

    task.worktree = request.worktree
    timestamp = datetime.now(UTC).isoformat()
    new_note = f"\n[{timestamp}] Worktree set to {request.worktree}"
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
        task_type=task.task_type,
        session_id=task.session_id,
        session_start_time=task.session_start_time,
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
            task_type=task.task_type,
            session_id=task.session_id,
            session_start_time=task.session_start_time,
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
            task_type=task.task_type,
            session_id=task.session_id,
            session_start_time=task.session_start_time,
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
            task_type=task.task_type,
            session_id=task.session_id,
            session_start_time=task.session_start_time,
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
            task_type=task.task_type,
            session_id=task.session_id,
            session_start_time=task.session_start_time,
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
            task_type=task.task_type,
            session_id=task.session_id,
            session_start_time=task.session_start_time,
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
        task_type=task.task_type,
        session_id=task.session_id,
        session_start_time=task.session_start_time,
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
        task.worktree = None
    task.assigned_agent = None
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
        task_type=task.task_type,
        session_id=task.session_id,
        session_start_time=task.session_start_time,
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

    full_worktree_path = (
        worktree_path
        if os.path.isabs(worktree_path)
        else os.path.join(os.path.dirname(os.getcwd()), worktree_path)
    )

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


@router.delete("/{task_id}", status_code=204)
def delete_task(task_id: str, admin_override: bool = False, db: Session = Depends(get_db)) -> None:
    """Delete a task by ID.

    Requires that the task exists and has no dependent tasks.
    Admin override allows deletion even with dependencies.
    """
    task = db.execute(select(Task).where(Task.task_id == task_id)).scalar_one_or_none()
    if not task:
        raise HTTPException(status_code=404, detail=f"Task {task_id} not found")

    if not admin_override:
        all_tasks = db.execute(select(Task)).scalars().all()
        dependent_tasks = []
        for t in all_tasks:
            if t.dependencies and task_id in [d.strip() for d in t.dependencies.split(",")]:
                dependent_tasks.append(t.task_id)

        if dependent_tasks:
            raise HTTPException(
                status_code=400,
                detail=f"Cannot delete task with dependencies. Dependent tasks: {', '.join(dependent_tasks)}",
            )

    db.delete(task)
    db.commit()
