"""Regression tests for test-only browser helpers."""

from datetime import UTC, datetime
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.test_helpers import create_test_reading_order, expire_current_session


@pytest.mark.asyncio
async def test_expire_current_session_ends_active_session() -> None:
    """The helper must expire sessions even when recent reading activity exists."""
    session = SimpleNamespace(
        started_at=datetime.now(UTC),
        ended_at=None,
        pending_thread_id=17,
        pending_issue_id=42,
    )
    result = Mock()
    result.scalar_one_or_none.return_value = session
    db = AsyncMock(spec=AsyncSession)
    db.execute.return_value = result

    response = await expire_current_session(SimpleNamespace(id=1), db)

    assert response == {"status": "success", "message": "Session expired"}
    assert session.ended_at is not None
    db.commit.assert_awaited_once()


@pytest.mark.asyncio
async def test_create_test_reading_order_builds_order_and_items() -> None:
    """The helper must create a reading order plus any provided items."""
    db = AsyncMock(spec=AsyncSession)
    db.commit.return_value = None
    db.refresh.return_value = None
    db.add.side_effect = lambda obj: setattr(obj, "id", 7)

    response = await create_test_reading_order(
        {"name": "Beta", "items": [{"thread_id": 1, "position": 2}]},
        SimpleNamespace(id=1),
        db,
    )

    assert response == {"id": 7, "name": "Beta"}
    db.add.assert_called()
    db.flush.assert_awaited_once()
    db.commit.assert_awaited_once()
