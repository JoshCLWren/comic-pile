"""Test API endpoints for E2E testing."""

from datetime import UTC, datetime, timedelta
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth import get_current_user
from app.config import get_app_settings
from app.database import get_db
from app.models import Session as SessionModel
from app.models import User

router = APIRouter(prefix="/test", tags=["test"])


@router.post("/sessions/expire")
async def expire_current_session(
    current_user: Annotated[User, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> dict[str, str]:
    """Expire the current active session by setting started_at to an old timestamp.

    This endpoint is only available in test environment and is used for E2E testing
    of session expiry notifications.

    Args:
        current_user: The authenticated user making the request.
        db: SQLAlchemy session for database operations.

    Returns:
        Dictionary with success message.

    Raises:
        HTTPException: If not in test environment or no active session found.
    """
    app_settings = get_app_settings()

    if app_settings.environment != "test":
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="This endpoint is only available in test environment",
        )

    cutoff_time = datetime.now(UTC) - timedelta(hours=24)

    session_result = await db.execute(
        select(SessionModel)
        .where(SessionModel.user_id == current_user.id)
        .where(SessionModel.ended_at.is_(None))
    )
    session = session_result.scalar_one_or_none()

    if not session:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="No active session found",
        )

    session.started_at = cutoff_time
    await db.commit()

    return {"status": "success", "message": "Session expired"}
