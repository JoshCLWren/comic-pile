"""Ownership and response-contract coverage for the Roll bootstrap endpoint."""

from datetime import UTC, datetime
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from httpx import AsyncClient
from sqlalchemy import event
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession

from app.api import roll as roll_api
from app.models import DependencyGroup, DependencyGroupMembership, Issue, Thread
from app.schemas import RollBootstrapResponse, RollBootstrapThread
from app.services.bandwidth import BANDWIDTH_VERSION
from tests.conftest import get_or_create_user_async


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
        predicted_bandwidth="balanced",
        active_bandwidth="balanced",
        bandwidth_confidence=0.0,
        bandwidth_source="inferred",
        bandwidth_version=BANDWIDTH_VERSION,
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
        predicted_bandwidth="balanced",
        active_bandwidth="balanced",
        bandwidth_confidence=0.0,
        bandwidth_source="inferred",
        bandwidth_version=BANDWIDTH_VERSION,
    )
    current_user = SimpleNamespace(id=7)
    pool_rows = [
        SimpleNamespace(
            id=index,
            title=f"Thread {index}",
            format="ongoing",
            issue_id=None,
            issue_number=None,
            route_labels=[],
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
async def test_bootstrap_pool_includes_threads_without_route_labels(
    auth_client: AsyncClient,
    async_db: AsyncSession,
) -> None:
    """Pool must not exclude threads that have no dependency group membership.

    Regression guard against the chained-outerjoin construction that dropped
    threads without memberships; this runs real SQL through the async
    PostgreSQL fixture so the join semantics are actually exercised.
    """
    user = await get_or_create_user_async(async_db)
    thread = Thread(
        user_id=user.id,
        title="No Route",
        format="Comic",
        issues_remaining=3,
        queue_position=1,
        status="active",
        created_at=datetime.now(UTC),
    )
    async_db.add(thread)
    await async_db.commit()

    response = await auth_client.get("/api/roll/bootstrap")
    assert response.status_code == 200
    pool = response.json()["roll_pool"]

    matching = [item for item in pool if item["id"] == thread.id]
    assert len(matching) == 1
    assert matching[0]["route_labels"] == []


@pytest.mark.asyncio
async def test_bootstrap_pool_aggregates_membership_labels_once(
    auth_client: AsyncClient,
    async_db: AsyncSession,
) -> None:
    """Aggregate route labels from thread- and issue-level memberships.

    Labels must deduplicate, stay user-scoped, and never drop membership-less
    threads. Runs against the real async PostgreSQL fixture so the correlated
    label subquery's user scoping and single-row-per-thread semantics are
    verified.
    """
    user = await get_or_create_user_async(async_db)
    other_user = await get_or_create_user_async(async_db, username="foreign_owner")

    multi = Thread(
        user_id=user.id,
        title="Multi Group",
        format="Comic",
        issues_remaining=3,
        queue_position=1,
        status="active",
        created_at=datetime.now(UTC),
    )
    issue_level = Thread(
        user_id=user.id,
        title="Issue Level",
        format="Comic",
        issues_remaining=3,
        queue_position=2,
        status="active",
        created_at=datetime.now(UTC),
    )
    no_membership = Thread(
        user_id=user.id,
        title="No Route",
        format="Comic",
        issues_remaining=3,
        queue_position=3,
        status="active",
        created_at=datetime.now(UTC),
    )
    async_db.add_all([multi, issue_level, no_membership])
    await async_db.flush()

    multi_issue = Issue(
        thread_id=multi.id,
        issue_number="1",
        position=1,
        status="unread",
    )
    next_issue = Issue(
        thread_id=issue_level.id,
        issue_number="3",
        position=1,
        status="unread",
    )
    async_db.add_all([multi_issue, next_issue])
    await async_db.flush()
    multi.next_unread_issue_id = multi_issue.id
    issue_level.next_unread_issue_id = next_issue.id

    alpha = DependencyGroup(user_id=user.id, name="Alpha")
    beta = DependencyGroup(user_id=user.id, name="Beta")
    gamma = DependencyGroup(user_id=user.id, name="Gamma")
    foreign = DependencyGroup(user_id=other_user.id, name="Foreign")
    async_db.add_all([alpha, beta, gamma, foreign])
    await async_db.flush()

    async_db.add_all(
        [
            DependencyGroupMembership(group_id=alpha.id, thread_id=multi.id),
            DependencyGroupMembership(group_id=beta.id, thread_id=multi.id),
            DependencyGroupMembership(group_id=alpha.id, issue_id=multi_issue.id),
            DependencyGroupMembership(group_id=gamma.id, issue_id=next_issue.id),
            DependencyGroupMembership(group_id=foreign.id, thread_id=multi.id),
        ]
    )
    await async_db.commit()

    response = await auth_client.get("/api/roll/bootstrap")
    assert response.status_code == 200
    pool = {item["id"]: item for item in response.json()["roll_pool"]}

    assert pool[multi.id]["title"] == "Multi Group"
    assert sorted(pool[multi.id]["route_labels"]) == ["Alpha", "Beta"]
    assert pool[issue_level.id]["route_labels"] == ["Gamma"]
    assert pool[no_membership.id]["route_labels"] == []
    all_labels = {label for item in pool.values() for label in item["route_labels"]}
    assert "Foreign" not in all_labels


@pytest.mark.asyncio
async def test_bootstrap_pool_query_count_is_constant(
    auth_client: AsyncClient,
    async_db: AsyncSession,
    db_engine: AsyncEngine,
) -> None:
    """Bootstrap SELECT count must not scale with pool rows or memberships.

    Regression guard: route labels are fetched by a correlated subquery inside
    the single pool query, so the endpoint performs no separate per-thread or
    per-membership label query and no route_result round trip.
    """
    user = await get_or_create_user_async(async_db)

    response = await auth_client.get("/api/roll/bootstrap")
    assert response.status_code == 200

    async def _add_pool(thread_count: int, groups_per_thread: int) -> None:
        for position in range(1, thread_count + 1):
            thread = Thread(
                user_id=user.id,
                title=f"Thread {position}",
                format="Comic",
                issues_remaining=3,
                queue_position=position,
                status="active",
                created_at=datetime.now(UTC),
            )
            async_db.add(thread)
            await async_db.flush()
            for group_index in range(groups_per_thread):
                group = DependencyGroup(
                    user_id=user.id,
                    name=f"Group {position}-{group_index}",
                )
                async_db.add(group)
                await async_db.flush()
                async_db.add(
                    DependencyGroupMembership(
                        group_id=group.id,
                        thread_id=thread.id,
                    )
                )

    async def _capture_selects() -> list[str]:
        statements: list[str] = []

        def _capture(conn, cursor, statement, parameters, context, executemany):
            if statement.lstrip().upper().startswith("SELECT"):
                statements.append(statement)

        event.listen(db_engine.sync_engine, "before_cursor_execute", _capture)
        try:
            response = await auth_client.get("/api/roll/bootstrap")
        finally:
            event.remove(db_engine.sync_engine, "before_cursor_execute", _capture)
        assert response.status_code == 200
        return statements

    await _add_pool(1, 0)
    await async_db.flush()
    small_pool_selects = await _capture_selects()

    await _add_pool(10, 3)
    await async_db.flush()
    large_pool_selects = await _capture_selects()

    assert len(large_pool_selects) == len(small_pool_selects)

    label_selects = [
        statement
        for statement in large_pool_selects
        if "dependency_group_memberships" in statement
    ]
    assert len(label_selects) == 1
    assert "array_agg" in label_selects[0]
