"""Scratch debug for the pre-existing undo issue_id regression."""

import pytest
from datetime import UTC, datetime

from httpx import AsyncClient
from sqlalchemy import event as sa_event, func, select
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession

from app.models import Event, Issue, Snapshot, Thread
from app.models import Session as SessionModel
from app.models.user import User
from app.schemas import RateRequest
from tests.test_delta_undo_regressions import _latest_snapshot
from app.services.snapshot_contract import SNAPSHOT_VERSION, SNAPSHOT_VERSION_KEY


@pytest.mark.asyncio
async def test_debug_undo_issue_id(
    auth_client: AsyncClient,
    async_db: AsyncSession,
    default_user: User,
) -> None:
    session = SessionModel(
        start_die=6,
        user_id=default_user.id,
        started_at=datetime.now(UTC),
    )
    thread = Thread(
        title="Legacy Counter Series",
        format="comic",
        issues_remaining=3,
        queue_position=1,
        status="active",
        user_id=default_user.id,
    )
    async_db.add_all([session, thread])
    await async_db.commit()
    await async_db.refresh(session)
    await async_db.refresh(thread)

    async_db.add(
        Event(
            type="roll",
            session_id=session.id,
            selected_thread_id=thread.id,
            die=6,
            result=1,
        )
    )
    await async_db.commit()

    rate_response = await auth_client.post(
        "/api/rate/",
        json={"rating": 5.0, "issues_read": 1, "issue_number": "1"},
    )
    assert rate_response.status_code == 200

    snapshot = await _latest_snapshot(async_db, session.id)
    assert snapshot.thread_states[SNAPSHOT_VERSION_KEY] == SNAPSHOT_VERSION

    from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

    _eng = create_async_engine("postgresql+asyncpg://postgres:postgres@localhost:5432/comic_pile_test")
    _f = async_sessionmaker(_eng, expire_on_commit=False)

    statements: list[str] = []

    def _capture(conn, cursor, statement, parameters, context, executemany):
        statements.append(str(statement))

    sa_event.listen(_eng.sync_engine, "before_cursor_execute", _capture)
    try:
        undo_response = await auth_client.post(
            f"/api/undo/{session.id}/undo/{snapshot.id}",
        )
    finally:
        sa_event.remove(_eng.sync_engine, "before_cursor_execute", _capture)
    assert undo_response.status_code == 200

    for s in statements:
        print(f"UNDOSTMT: {s}")

    async with _f() as _db:
        _res = await _db.execute(
            select(Event).where(Event.session_id == session.id).where(Event.type == "rate")
        )
        _ev = _res.scalars().one()
        print(f"DBFRESH issue_id={_ev.issue_id} issue_number={_ev.issue_number}")
    await _eng.dispose()
