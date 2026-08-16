"""Ownership and response-contract coverage for the Roll bootstrap endpoint."""

from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from app.api import roll as roll_api
from app.schemas import RollBootstrapResponse, RollBootstrapThread


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

    def scalars(self):
        return self


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
    monkeypatch.setattr(
        roll_api,
        "get_current_die_for_session",
        AsyncMock(return_value=4),
    )

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
            "issue_id": None,
            "issue_number": None,
            "route_labels": [],
            "last_activity_at": None,
        }
    ]


@pytest.mark.asyncio
async def test_bootstrap_roll_pool_is_never_paginated_below_current_die(monkeypatch):
    """A d100 bootstrap may return all 100 eligible faces instead of a smaller summary page."""
    current_session = SimpleNamespace(
        id=55,
        manual_die=100,
        pending_thread_id=None,
        snoozed_thread_ids=[],
    )
    current_user = SimpleNamespace(id=7)
    pool_rows = [
        SimpleNamespace(
            id=index,
            title=f"Thread {index}",
            format="ongoing",
            issue_id=None,
            issue_number=None,
        )
        for index in range(1, 101)
    ]

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
    monkeypatch.setattr(
        roll_api,
        "get_current_die_for_session",
        AsyncMock(return_value=100),
    )

    db = AsyncMock()
    db.execute.side_effect = [
        _Result(rows=pool_rows),
        _Result(rows=[]),
        _Result(scalar_value=0),
        _Result(rows=[]),
        _Result(scalar_value=0),
    ]

    response = await roll_api.roll_bootstrap(current_user=current_user, db=db)

    pool_statement = db.execute.await_args_list[0].args[0]
    compiled = str(pool_statement.compile(compile_kwargs={"literal_binds": True}))
    assert "LIMIT 100" in compiled
    assert response.current_die == 100
    assert len(response.roll_pool) == 100


def test_bootstrap_schema_bounds_summary_lists_without_losing_counts():
    """Keep the HTTP payload bounded while preserving complete summary counts."""
    summaries = [
        RollBootstrapThread(id=index, title=f"Thread {index}", format="ongoing")
        for index in range(1, 26)
    ]

    response = RollBootstrapResponse(
        session_id=1,
        user_id=1,
        current_die=100,
        manual_die=None,
        pending_thread_id=None,
        last_rolled_result=None,
        active_thread=None,
        roll_pool=summaries,
        snoozed_threads=summaries,
        snoozed_count=len(summaries),
        blocked_count=len(summaries),
        blocked_threads=summaries,
        stale_thread_count=0,
        stale_thread=None,
    )

    assert len(response.roll_pool) == 25
    assert len(response.snoozed_threads) == response.summary_limit
    assert len(response.blocked_threads) == response.summary_limit
    assert response.snoozed_count == 25
    assert response.blocked_count == 25


@pytest.mark.asyncio
async def test_bootstrap_pool_includes_threads_without_route_labels(monkeypatch):
    """Pool must not exclude threads that have no dependency group membership.

    Regression guard: the pool query uses an outer join on DependencyGroup so
    threads without route labels must still appear in the roll pool.
    """
    current_session = SimpleNamespace(
        id=55,
        manual_die=None,
        pending_thread_id=None,
        snoozed_thread_ids=[],
    )
    current_user = SimpleNamespace(id=7)

    monkeypatch.setattr(
        roll_api, "get_or_create", AsyncMock(return_value=current_session)
    )
    monkeypatch.setattr(
        roll_api,
        "get_session_with_thread_safe",
        AsyncMock(return_value=(current_session, None)),
    )
    monkeypatch.setattr(roll_api, "get_current_die", AsyncMock(return_value=6))

    pool_row = SimpleNamespace(
        id=10,
        title="No Route",
        format="Comic",
        issue_id=None,
        issue_number=None,
        route_label=None,
    )

    db = AsyncMock()
    db.execute.side_effect = [
        _Result(rows=[pool_row]),
        _Result(rows=[]),   # snoozed (empty ids)
        _Result(scalar_value=0),  # blocked count
        _Result(rows=[]),   # blocked threads
        _Result(scalar_value=0),  # stale count
    ]

    response = await roll_api.roll_bootstrap(current_user=current_user, db=db)

    assert len(response.roll_pool) == 1
    assert response.roll_pool[0].id == 10
    assert response.roll_pool[0].route_labels == []


@pytest.mark.asyncio
async def test_bootstrap_pool_deduplicates_threads_with_multiple_memberships(
    monkeypatch,
):
    """A thread with two route-label memberships must appear once in the pool.

    Regression guard: the pool query outer-joining DependencyGroup can return
    multiple rows per thread; application code must deduplicate them.
    """
    current_session = SimpleNamespace(
        id=55,
        manual_die=None,
        pending_thread_id=None,
        snoozed_thread_ids=[],
    )
    current_user = SimpleNamespace(id=7)

    monkeypatch.setattr(
        roll_api, "get_or_create", AsyncMock(return_value=current_session)
    )
    monkeypatch.setattr(
        roll_api,
        "get_session_with_thread_safe",
        AsyncMock(return_value=(current_session, None)),
    )
    monkeypatch.setattr(roll_api, "get_current_die", AsyncMock(return_value=6))

    row_a = SimpleNamespace(
        id=10, title="Multi", format="Ongoing", issue_id=None,
        issue_number=None, route_label="Alpha",
    )
    row_b = SimpleNamespace(
        id=10, title="Multi", format="Ongoing", issue_id=None,
        issue_number=None, route_label="Beta",
    )

    db = AsyncMock()
    db.execute.side_effect = [
        _Result(rows=[row_a, row_b]),
        _Result(rows=[]),
        _Result(scalar_value=0),
        _Result(rows=[]),
        _Result(scalar_value=0),
    ]

    response = await roll_api.roll_bootstrap(current_user=current_user, db=db)

    assert len(response.roll_pool) == 1
    assert response.roll_pool[0].id == 10
    assert sorted(response.roll_pool[0].route_labels) == ["Alpha", "Beta"]
