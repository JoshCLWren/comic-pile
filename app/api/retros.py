"""Retro API endpoints for session retrospective generation."""

from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.database import get_db
from app.models import Task

router = APIRouter(prefix="/retros", tags=["retros"])


class RetroTaskItem(BaseModel):
    task_id: str
    title: str
    status: str
    priority: str
    blocked_reason: str | None
    assigned_agent: str | None
    worktree: str | None
    status_notes: str | None


class RetroResponse(BaseModel):
    session_id: str
    task_count: int
    completed_count: int
    blocked_count: int
    in_review_count: int
    failed_tests_count: int
    merge_conflicts_count: int
    tasks: list[RetroTaskItem]


class GenerateRetroRequest(BaseModel):
    session_id: str = Field(..., min_length=1)


@router.post("/generate", response_model=RetroResponse)
async def generate_retro(
    request: GenerateRetroRequest, db: Session = Depends(get_db)
) -> RetroResponse:
    tasks = db.execute(select(Task).where(Task.session_id == request.session_id)).scalars().all()

    completed = [t for t in tasks if t.status == "done"]
    blocked = [t for t in tasks if t.status == "blocked"]
    in_review = [t for t in tasks if t.status == "in_review"]
    failed_tests = [t for t in tasks if t.blocked_reason and "test" in t.blocked_reason.lower()]
    merge_conflicts = [
        t for t in tasks if t.blocked_reason and "conflict" in t.blocked_reason.lower()
    ]

    return RetroResponse(
        session_id=request.session_id,
        task_count=len(tasks),
        completed_count=len(completed),
        blocked_count=len(blocked),
        in_review_count=len(in_review),
        failed_tests_count=len(failed_tests),
        merge_conflicts_count=len(merge_conflicts),
        tasks=[
            RetroTaskItem(
                task_id=t.task_id,
                title=t.title,
                status=t.status,
                priority=t.priority,
                blocked_reason=t.blocked_reason,
                assigned_agent=t.assigned_agent,
                worktree=t.worktree,
                status_notes=t.status_notes[-500:] if t.status_notes else None,
            )
            for t in tasks
        ],
    )
