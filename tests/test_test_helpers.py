"""Regression tests for test-only browser helpers."""

from datetime import UTC, datetime
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.test_helpers import expire_current_session


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
