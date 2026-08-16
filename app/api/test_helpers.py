"""Test API endpoints for E2E testing."""

import os
from datetime import UTC, datetime
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth import get_current_user
from app.database import get_db
from app.models import Session as SessionModel
from app.models import User
from app.models.reading_order import ReadingOrder, ReadingOrderItem

router = APIRouter(prefix="/test", tags=["test"])


async def _require_test_environment() -> None:
    """Reject test-only endpoints outside the E2E environment."""
    if os.getenv("TEST_ENVIRONMENT") != "true":
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="This endpoint is only available in test environment",
        )


@router.post("/reading-orders")
async def create_test_reading_order(
    payload: dict[str, object],
    current_user: Annotated[User, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> dict[str, object]:
    """Create a reading order (with optional items) for E2E tests.

    Only available in test environments. Accepts a name and a list of
    thread_id/position items so browser tests can seed projection targets.
    """
    await _require_test_environment()

    name = str(payload.get("name") or "Test reading order")
    order = ReadingOrder(name=name, user_id=current_user.id)
    db.add(order)
    await db.flush()

    raw_items = payload.get("items")
    if isinstance(raw_items, list):
        for raw in raw_items:
            if not isinstance(raw, dict):
                continue
            raw_thread_id = raw.get("thread_id")
            raw_position = raw.get("position")
            db.add(
                ReadingOrderItem(
                    reading_order_id=order.id,
                    thread_id=int(raw_thread_id) if raw_thread_id is not None else 0,
                    position=int(raw_position) if raw_position is not None else 1,
                    issue_number=raw.get("issue_number"),
                )
            )
    await db.commit()
    await db.refresh(order)

    return {"id": order.id, "name": order.name}


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
    await _require_test_environment()

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

    session.ended_at = datetime.now(UTC)
    await db.commit()

    return {"status": "success", "message": "Session expired"}
