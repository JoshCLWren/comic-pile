"""Admin API endpoints for data import/export."""

from fastapi import APIRouter, Depends, File, UploadFile
from typing import Annotated
from fastapi.responses import StreamingResponse
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.access_control import require_internal_ops_routes
from app.services.admin_service import (
    import_csv as svc_import_csv,
    export_csv as svc_export_csv,
    export_json as svc_export_json,
    delete_test_data as svc_delete_test_data,
    export_summary as svc_export_summary,
)

router = APIRouter(
    prefix="/admin", tags=["admin"], dependencies=[Depends(require_internal_ops_routes)]
)


@router.post("/import/csv/")
async def import_csv(
    file: Annotated[UploadFile, File(...)], db: Annotated[AsyncSession, Depends(get_db)]
) -> dict[str, int | list[str]]:
    """Import threads from CSV file.

    CSV format: title, format, issues_remaining
    - title: Thread title (required)
    - format: Thread format (required)
    - issues_remaining: Number of issues remaining (required, integer)

    Threads are inserted at position 1 (front of queue).

    Args:
        file: CSV file to import.
        db: SQLAlchemy session for database operations.

    Returns:
        Dictionary with "imported" count and "errors" list.

    Raises:
        HTTPException: If file is not a CSV.
    """
    return await svc_import_csv(file, db)


@router.get("/export/csv/")
async def export_csv(db: Annotated[AsyncSession, Depends(get_db)]) -> StreamingResponse:
    """Export active threads as CSV file.

    Format matches Google Sheets: title, format, issues_remaining

    Args:
        db: SQLAlchemy session for database operations.

    Returns:
        StreamingResponse with CSV file attachment.
    """
    csv_bytes = await svc_export_csv(db)
    return StreamingResponse(
        csv_bytes,
        media_type="text/csv",
        headers={"Content-Disposition": "attachment; filename=threads_export.csv"},
    )


@router.get("/export/json/")
async def export_json(db: Annotated[AsyncSession, Depends(get_db)]) -> StreamingResponse:
    """Export full database as JSON for backups.

    Includes all data: users, threads, sessions, events (excludes test data)

    Args:
        db: SQLAlchemy session for database operations.

    Returns:
        StreamingResponse with JSON file attachment.
    """
    json_bytes = await svc_export_json(db)
    return StreamingResponse(
        json_bytes,
        media_type="application/json",
        headers={"Content-Disposition": "attachment; filename=database_backup.json"},
    )


@router.post("/delete-test-data/")
async def delete_test_data(db: Annotated[AsyncSession, Depends(get_db)]) -> dict[str, int]:
    """Delete all test data (threads, sessions, events marked as test).

    Args:
        db: SQLAlchemy session for database operations.

    Returns:
        Dictionary with counts of deleted threads, sessions, and events.
    """
    return await svc_delete_test_data(db)


@router.get("/export/summary/")
async def export_summary(db: Annotated[AsyncSession, Depends(get_db)]) -> StreamingResponse:
    """Export narrative session summaries as markdown file.

    Formats all sessions with read, skipped, and completed lists per PRD Section 11.
    Excludes sessions that only involve test threads.

    Args:
        db: SQLAlchemy session for database operations.

    Returns:
        StreamingResponse with markdown file attachment.
    """
    md_bytes, filename = await svc_export_summary(db)
    return StreamingResponse(
        md_bytes,
        media_type="text/markdown",
        headers={"Content-Disposition": f"attachment; filename={filename}"},
    )