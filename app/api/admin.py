"""Admin API endpoints for data import/export."""

import csv
import io
import json
from datetime import UTC, datetime

from fastapi import APIRouter, Depends, File, HTTPException, UploadFile
from fastapi.responses import StreamingResponse
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.session import build_narrative_summary
from app.database import get_db_async
from app.dependencies import require_internal_ops_routes
from app.models import Event, Thread, User
from app.models import Session as SessionModel

router = APIRouter(
    prefix="/admin", tags=["admin"], dependencies=[Depends(require_internal_ops_routes)]
)


@router.post("/import/csv/")
async def import_csv(
    file: UploadFile = File(...), db: AsyncSession = Depends(get_db_async)
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

    await db.commit()

    for i, thread in enumerate(reversed(imported_threads)):
        thread.queue_position = i + 1
        await db.flush()

    await db.commit()
    return {"imported": imported, "errors": errors}


@router.get("/export/csv/")
async def export_csv(db: AsyncSession = Depends(get_db_async)) -> StreamingResponse:
    """Export active threads as CSV file.

    Format matches Google Sheets: title, format, issues_remaining
    """
    result = await db.execute(
        select(Thread)
        .where(Thread.status == "active")
        .where(Thread.queue_position >= 1)
        .where(Thread.issues_remaining > 0)
        .where(Thread.is_test.is_(False))
        .order_by(Thread.queue_position)
    )
    threads = result.scalars().all()

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
async def export_json(db: AsyncSession = Depends(get_db_async)) -> StreamingResponse:
    """Export full database as JSON for backups.

    Includes all data: users, threads, sessions, events (excludes test data)
    """
    users_result = await db.execute(select(User))
    users = users_result.scalars().all()
    threads_result = await db.execute(select(Thread).where(Thread.is_test.is_(False)))
    threads = threads_result.scalars().all()
    sessions_result = await db.execute(select(SessionModel))
    sessions = sessions_result.scalars().all()
    events_result = await db.execute(select(Event))
    events = events_result.scalars().all()

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


@router.post("/delete-test-data/")
async def delete_test_data(db: AsyncSession = Depends(get_db_async)) -> dict[str, int]:
    """Delete all test data (threads, sessions, events marked as test).

    Returns count of deleted items.
    """
    test_threads_result = await db.execute(select(Thread).where(Thread.is_test.is_(True)))
    test_threads = test_threads_result.scalars().all()
    thread_ids = [t.id for t in test_threads]

    deleted_events = 0
    deleted_sessions = 0
    deleted_threads = len(test_threads)

    for thread_id in thread_ids:
        events_by_thread_id_result = await db.execute(
            select(Event).where(Event.thread_id == thread_id)
        )
        events_by_thread_id = events_by_thread_id_result.scalars().all()
        events_by_selected_thread_id_result = await db.execute(
            select(Event).where(Event.selected_thread_id == thread_id)
        )
        events_by_selected_thread_id = events_by_selected_thread_id_result.scalars().all()
        all_events = set()
        for e in events_by_thread_id:
            all_events.add(e)
        for e in events_by_selected_thread_id:
            all_events.add(e)
        deleted_events += len(all_events)
        for event in all_events:
            await db.delete(event)

    await db.execute(
        update(SessionModel)
        .where(SessionModel.pending_thread_id.in_(thread_ids))
        .values(pending_thread_id=None)
    )

    for _thread_id in thread_ids:
        sessions_result = await db.execute(select(SessionModel).where(SessionModel.user_id == 1))
        sessions = sessions_result.scalars().all()
        for session in sessions:
            session_id = session.id
            session_events_result = await db.execute(
                select(Event).where(Event.session_id == session_id)
            )
            session_events = session_events_result.scalars().all()
            if all(e.thread_id in thread_ids for e in session_events if e.thread_id):
                await db.delete(session)
                deleted_sessions += 1

    for thread in test_threads:
        await db.delete(thread)

    await db.commit()

    return {
        "deleted_threads": deleted_threads,
        "deleted_sessions": deleted_sessions,
        "deleted_events": deleted_events,
    }


@router.post("/import/reviews/")
async def import_reviews(
    file: UploadFile = File(...), db: AsyncSession = Depends(get_db_async)
) -> dict[str, int | list[str]]:
    """Import review timestamps from CSV file.

    CSV format: thread_id, review_url, review_timestamp
    - thread_id: Thread ID (required, must exist)
    - review_url: Review URL (required)
    - review_timestamp: ISO format datetime (required)

    Updates thread's last_review_at and review_url fields.
    """
    if not file.filename or not file.filename.endswith(".csv"):
        raise HTTPException(status_code=400, detail="File must be a CSV")

    content = await file.read()
    csv_reader = csv.DictReader(content.decode("utf-8").splitlines())

    imported = 0
    errors = []

    for row_num, row in enumerate(csv_reader, start=2):
        try:
            thread_id_str = row.get("thread_id", "").strip()
            review_url = row.get("review_url", "").strip()
            review_timestamp_str = row.get("review_timestamp", "").strip()

            if not thread_id_str:
                errors.append(f"Row {row_num}: Missing thread_id")
                continue

            if not review_url:
                errors.append(f"Row {row_num}: Missing review_url")
                continue

            if not review_timestamp_str:
                errors.append(f"Row {row_num}: Missing review_timestamp")
                continue

            try:
                thread_id = int(thread_id_str)
            except ValueError:
                errors.append(f"Row {row_num}: thread_id must be an integer")
                continue

            thread_result = await db.execute(select(Thread).where(Thread.id == thread_id))
            thread = thread_result.scalar_one_or_none()

            if not thread:
                errors.append(f"Row {row_num}: Thread {thread_id} not found")
                continue

            try:
                review_timestamp = datetime.fromisoformat(review_timestamp_str)
            except ValueError:
                errors.append(f"Row {row_num}: review_timestamp must be ISO format datetime")
                continue

            thread.review_url = review_url
            thread.last_review_at = review_timestamp
            await db.flush()
            imported += 1

        except Exception as e:
            errors.append(f"Row {row_num}: {str(e)}")

    await db.commit()
    return {"imported": imported, "errors": errors}


@router.get("/export/summary/")
async def export_summary(db: AsyncSession = Depends(get_db_async)) -> StreamingResponse:
    """Export narrative session summaries as markdown file.

    Formats all sessions with read, skipped, and completed lists per PRD Section 11.
    Excludes sessions that only involve test threads.
    """
    all_sessions_result = await db.execute(
        select(SessionModel).order_by(SessionModel.started_at.desc())
    )
    all_sessions = all_sessions_result.scalars().all()

    test_threads_result = await db.execute(select(Thread).where(Thread.is_test.is_(True)))
    test_thread_ids = {t.id for t in test_threads_result.scalars().all()}

    sessions = []
    for session in all_sessions:
        session_id = session.id
        session_events_result = await db.execute(
            select(Event).where(Event.session_id == session_id)
        )
        session_events = session_events_result.scalars().all()
        thread_ids_in_session = set()
        for event in session_events:
            if event.thread_id:
                thread_ids_in_session.add(event.thread_id)
            if event.selected_thread_id:
                thread_ids_in_session.add(event.selected_thread_id)
        if not thread_ids_in_session or not thread_ids_in_session.issubset(test_thread_ids):
            sessions.append((session, session_id))

    output = io.StringIO()

    for session, session_id in sessions:
        started_at = session.started_at.astimezone(UTC)
        ended_at = session.ended_at.astimezone(UTC) if session.ended_at else None

        output.write(f"**Session:** {started_at.strftime('%b %d, %I:%M %p')}")
        if ended_at:
            output.write(f" - {ended_at.strftime('%I:%M %p')}")
        output.write("\n")
        output.write(f"Started at d{session.start_die}\n")

        summary = await build_narrative_summary(session_id, db)

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
