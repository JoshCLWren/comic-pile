"""Admin API endpoints for data import/export."""

import csv
import io
import json
from datetime import UTC, datetime

from fastapi import APIRouter, Depends, File, HTTPException, UploadFile
from fastapi.responses import StreamingResponse
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.session import build_narrative_summary
from app.database import get_db
from app.models import Event, Thread, User
from app.models import Session as SessionModel

router = APIRouter(prefix="/admin", tags=["admin"])


@router.post("/import/csv/")
async def import_csv(
    file: UploadFile = File(...), db: Session = Depends(get_db)
) -> dict[str, int | list[str]]:
    """Import threads from CSV file.

    CSV format: title, format, issues_remaining
    - title: Thread title (required)
    - format: Thread format (required)
    - issues_remaining: Number of issues remaining (required, integer)

    Threads are inserted at position 1 (front of queue).
    """
    if not file.filename or not file.filename.endswith(".csv"):
        raise HTTPException(status_code=400, detail="File must be a CSV")

    content = await file.read()
    csv_reader = csv.DictReader(content.decode("utf-8").splitlines())

    imported = 0
    errors = []
    imported_threads = []

    for row_num, row in enumerate(csv_reader, start=2):
        try:
            title = row.get("title", "").strip()
            format_val = row.get("format", "").strip()
            issues_remaining_str = row.get("issues_remaining", "").strip()

            if not title:
                errors.append(f"Row {row_num}: Missing title")
                continue

            if not format_val:
                errors.append(f"Row {row_num}: Missing format")
                continue

            if not issues_remaining_str:
                errors.append(f"Row {row_num}: Missing issues_remaining")
                continue

            try:
                issues_remaining = int(issues_remaining_str)
                if issues_remaining < 0:
                    errors.append(f"Row {row_num}: issues_remaining must be >= 0")
                    continue
            except ValueError:
                errors.append(f"Row {row_num}: issues_remaining must be an integer")
                continue

            new_thread = Thread(
                title=title,
                format=format_val,
                issues_remaining=issues_remaining,
                queue_position=1,
                status="active",
                user_id=1,
            )
            db.add(new_thread)
            imported_threads.append(new_thread)
            imported += 1

        except Exception as e:
            errors.append(f"Row {row_num}: {str(e)}")

    db.commit()

    for i, thread in enumerate(reversed(imported_threads)):
        thread.queue_position = i + 1
        db.flush()

    db.commit()
    return {"imported": imported, "errors": errors}


@router.get("/export/csv/")
def export_csv(db: Session = Depends(get_db)) -> StreamingResponse:
    """Export active threads as CSV file.

    Format matches Google Sheets: title, format, issues_remaining
    """
    threads = (
        db.execute(
            select(Thread)
            .where(Thread.status == "active")
            .where(Thread.queue_position >= 1)
            .where(Thread.issues_remaining > 0)
            .order_by(Thread.queue_position)
        )
        .scalars()
        .all()
    )

    output = io.StringIO()
    writer = csv.writer(output)

    writer.writerow(["title", "format", "issues_remaining"])

    for thread in threads:
        writer.writerow([thread.title, thread.format, thread.issues_remaining])

    output.seek(0)

    return StreamingResponse(
        io.BytesIO(output.getvalue().encode()),
        media_type="text/csv",
        headers={"Content-Disposition": "attachment; filename=threads_export.csv"},
    )


@router.get("/export/json/")
def export_json(db: Session = Depends(get_db)) -> StreamingResponse:
    """Export full database as JSON for backups.

    Includes all data: users, threads, sessions, events
    """
    users = db.execute(select(User)).scalars().all()
    threads = db.execute(select(Thread)).scalars().all()
    sessions = db.execute(select(SessionModel)).scalars().all()
    events = db.execute(select(Event)).scalars().all()

    data = {
        "users": [
            {
                "id": user.id,
                "username": user.username,
                "created_at": user.created_at.isoformat() if user.created_at else None,
            }
            for user in users
        ],
        "threads": [
            {
                "id": thread.id,
                "title": thread.title,
                "format": thread.format,
                "issues_remaining": thread.issues_remaining,
                "queue_position": thread.queue_position,
                "status": thread.status,
                "last_rating": thread.last_rating,
                "last_activity_at": thread.last_activity_at.isoformat()
                if thread.last_activity_at
                else None,
                "review_url": thread.review_url,
                "last_review_at": thread.last_review_at.isoformat()
                if thread.last_review_at
                else None,
                "created_at": thread.created_at.isoformat() if thread.created_at else None,
                "user_id": thread.user_id,
            }
            for thread in threads
        ],
        "sessions": [
            {
                "id": session.id,
                "started_at": session.started_at.isoformat() if session.started_at else None,
                "ended_at": session.ended_at.isoformat() if session.ended_at else None,
                "start_die": session.start_die,
                "user_id": session.user_id,
            }
            for session in sessions
        ],
        "events": [
            {
                "id": event.id,
                "type": event.type,
                "timestamp": event.timestamp.isoformat() if event.timestamp else None,
                "die": event.die,
                "result": event.result,
                "selected_thread_id": event.selected_thread_id,
                "selection_method": event.selection_method,
                "rating": event.rating,
                "issues_read": event.issues_read,
                "queue_move": event.queue_move,
                "die_after": event.die_after,
                "session_id": event.session_id,
                "thread_id": event.thread_id,
            }
            for event in events
        ],
    }

    json_output = json.dumps(data, indent=2)
    return StreamingResponse(
        io.BytesIO(json_output.encode()),
        media_type="application/json",
        headers={"Content-Disposition": "attachment; filename=database_backup.json"},
    )


@router.get("/export/summary/")
def export_summary(db: Session = Depends(get_db)) -> StreamingResponse:
    """Export narrative session summaries as markdown file.

    Formats all sessions with read, skipped, and completed lists per PRD Section 11.
    """
    sessions = (
        db.execute(select(SessionModel).order_by(SessionModel.started_at.desc())).scalars().all()
    )

    output = io.StringIO()

    for session in sessions:
        started_at = session.started_at.astimezone(UTC)
        ended_at = session.ended_at.astimezone(UTC) if session.ended_at else None

        output.write(f"**Session:** {started_at.strftime('%b %d, %I:%M %p')}")
        if ended_at:
            output.write(f" – {ended_at.strftime('%I:%M %p')}")
        output.write("\n")
        output.write(f"Started at d{session.start_die}\n")

        summary = build_narrative_summary(session.id, db)

        if summary["read"]:
            output.write("\nRead:\n\n")
            for entry in summary["read"]:
                output.write(f"* {entry}\n")

        if summary["skipped"]:
            output.write("\nSkipped:\n\n")
            for title in summary["skipped"]:
                output.write(f"* {title}\n")

        if summary["completed"]:
            output.write("\nCompleted:\n\n")
            for title in summary["completed"]:
                output.write(f"* {title}\n")

        output.write("\n---\n\n")

    output.seek(0)

    filename = f"session_summaries_{datetime.now(UTC).strftime('%Y%m%d')}.md"
    return StreamingResponse(
        io.BytesIO(output.getvalue().encode()),
        media_type="text/markdown",
        headers={"Content-Disposition": f"attachment; filename={filename}"},
    )
