"""Ownership and response-contract coverage for the Roll bootstrap endpoint."""

from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from app.api import roll as roll_api


class _Result:
    """Minimal SQLAlchemy result double for the bootstrap query sequence."""

    def __init__(self, *, rows=None, scalar_value=None):
        self._rows = rows or []
        self._scalar_value = scalar_value

    def all(self):
        return self._rows

    def scalar(self):
        return self._scalar_value

    def first(self):
        return self._rows[0] if self._rows else None


@pytest.mark.asyncio
async def test_bootstrap_scopes_snoozed_threads_and_returns_format(monkeypatch):
    """Do not expose a foreign snoozed ID or omit fields required by RollPage."""
    current_session = SimpleNamespace(
        id=55,
        manual_die=None,
        pending_thread_id=None,
        snoozed_thread_ids=[101, 202],
    )
    current_user = SimpleNamespace(id=7)
    owned_snoozed = SimpleNamespace(id=101, title="Owned", format="ongoing")

    monkeypatch.setattr(
        roll_api,
        "get_or_create",
        AsyncMock(return_value=current_session),
    )
    monkeypatch.setattr(
        roll_api,
        "get_session_with_thread_safe",
        AsyncMock(return_value=(current_session, None)),
    )
    monkeypatch.setattr(roll_api, "get_current_die", AsyncMock(return_value=4))

    db = AsyncMock()
    db.execute.side_effect = [
        _Result(rows=[]),
        _Result(rows=[owned_snoozed]),
        _Result(scalar_value=0),
        _Result(rows=[]),
        _Result(scalar_value=0),
    ]

    response = await roll_api.roll_bootstrap(current_user=current_user, db=db)

    snoozed_statement = db.execute.await_args_list[1].args[0]
    compiled = str(snoozed_statement)
    assert "threads.user_id" in compiled
    assert "threads.id" in compiled

    assert response.snoozed_count == 1
    assert [thread.model_dump() for thread in response.snoozed_threads] == [
        {
            "id": 101,
            "title": "Owned",
            "format": "ongoing",
            "last_activity_at": None,
        }
    ]
