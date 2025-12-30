"""Thread CRUD API endpoints."""

from fastapi import APIRouter, Depends, HTTPException, Request, status
from fastapi.responses import HTMLResponse
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.database import get_db
from app.models import Thread
from app.schemas.thread import ReactivateRequest, ThreadCreate, ThreadResponse, ThreadUpdate

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


@router.get("/completed", response_class=HTMLResponse)
def list_completed_threads(request: Request, db: Session = Depends(get_db)) -> str:
    """List completed threads for reactivation modal."""
    threads = (
        db.execute(
            select(Thread).where(Thread.status == "completed").order_by(Thread.created_at.desc())
        )
        .scalars()
        .all()
    )
    options = "\n".join(
        f'<option value="{thread.id}">{thread.title} ({thread.format})</option>'
        for thread in threads
    )
    return f'<option value="">Select a completed thread...</option>\n{options}'


@router.get("/active", response_class=HTMLResponse)
def list_active_threads(request: Request, db: Session = Depends(get_db)) -> str:
    """List active threads for override modal."""
    threads = (
        db.execute(select(Thread).where(Thread.status == "active").order_by(Thread.queue_position))
        .scalars()
        .all()
    )
    items = "\n".join(
        f'<div class="flex items-center p-2 hover:bg-gray-50 rounded">'
        f'<input type="radio" name="thread_id" value="{thread.id}" id="thread-{thread.id}" class="mr-3">'
        f'<label for="thread-{thread.id}" class="flex-1 cursor-pointer">'
        f'<span class="font-medium">{thread.title}</span>'
        f'<span class="text-sm text-gray-500 ml-2">({thread.format})</span>'
        f"</label></div>"
        for thread in threads
    )
    return items or '<p class="text-gray-500 text-center py-4">No active threads available</p>'


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


@router.post("/reactivate", response_model=ThreadResponse)
def reactivate_thread(request: ReactivateRequest, db: Session = Depends(get_db)) -> ThreadResponse:
    """Reactivate a completed thread by adding more issues."""
    thread = db.get(Thread, request.thread_id)
    if not thread:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Thread {request.thread_id} not found",
        )
    if thread.status != "completed":
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Thread {request.thread_id} is not completed",
        )
    if request.issues_to_add <= 0:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Must add at least 1 issue",
        )
    from sqlalchemy import update

    db.execute(update(Thread).values(queue_position=Thread.queue_position + 1))
    thread.issues_remaining = request.issues_to_add
    thread.status = "active"
    thread.queue_position = 1
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
