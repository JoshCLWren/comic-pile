"""Thread CRUD API endpoints."""

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.database import get_db
from app.models import Thread
from app.schemas import ThreadCreate, ThreadResponse, ThreadUpdate

router = APIRouter(tags=["threads"])


@router.get("/", response_model=list[ThreadResponse])
def list_threads(db: Session = Depends(get_db)) -> list[ThreadResponse]:
    """List all threads ordered by position."""
    threads = db.execute(select(Thread).order_by(Thread.queue_position)).scalars().all()
    return [
        ThreadResponse(
            id=thread.id,
            title=thread.title,
            format=thread.format,
            issues_remaining=thread.issues_remaining,
            position=thread.queue_position,
            created_at=thread.created_at,
        )
        for thread in threads
    ]


@router.post("/", response_model=ThreadResponse, status_code=status.HTTP_201_CREATED)
def create_thread(thread_data: ThreadCreate, db: Session = Depends(get_db)) -> ThreadResponse:
    """Create a new thread."""
    max_position = (
        db.execute(select(Thread.queue_position).order_by(Thread.queue_position.desc())).scalar()
        or 0
    )
    new_thread = Thread(
        title=thread_data.title,
        format=thread_data.format,
        issues_remaining=thread_data.issues_remaining,
        queue_position=max_position + 1,
        user_id=1,
    )
    db.add(new_thread)
    db.commit()
    db.refresh(new_thread)
    return ThreadResponse(
        id=new_thread.id,
        title=new_thread.title,
        format=new_thread.format,
        issues_remaining=new_thread.issues_remaining,
        position=new_thread.queue_position,
        created_at=new_thread.created_at,
    )


@router.get("/{thread_id}", response_model=ThreadResponse)
def get_thread(thread_id: int, db: Session = Depends(get_db)) -> ThreadResponse:
    """Get a single thread by ID."""
    thread = db.get(Thread, thread_id)
    if not thread:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Thread {thread_id} not found",
        )
    return ThreadResponse(
        id=thread.id,
        title=thread.title,
        format=thread.format,
        issues_remaining=thread.issues_remaining,
        position=thread.queue_position,
        created_at=thread.created_at,
    )


@router.put("/{thread_id}", response_model=ThreadResponse)
def update_thread(
    thread_id: int, thread_data: ThreadUpdate, db: Session = Depends(get_db)
) -> ThreadResponse:
    """Update a thread."""
    thread = db.get(Thread, thread_id)
    if not thread:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Thread {thread_id} not found",
        )
    if thread_data.title is not None:
        thread.title = thread_data.title
    if thread_data.format is not None:
        thread.format = thread_data.format
    if thread_data.issues_remaining is not None:
        thread.issues_remaining = thread_data.issues_remaining
        if thread.issues_remaining == 0:
            thread.status = "completed"
        else:
            thread.status = "active"
    db.commit()
    db.refresh(thread)
    return ThreadResponse(
        id=thread.id,
        title=thread.title,
        format=thread.format,
        issues_remaining=thread.issues_remaining,
        position=thread.queue_position,
        created_at=thread.created_at,
    )


@router.delete("/{thread_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_thread(thread_id: int, db: Session = Depends(get_db)) -> None:
    """Delete a thread."""
    thread = db.get(Thread, thread_id)
    if not thread:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Thread {thread_id} not found",
        )
    db.delete(thread)
    db.commit()
