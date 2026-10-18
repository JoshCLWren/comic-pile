"""Scratch reproduction for issue #3468 (rate -> undo -> rate -> undo)."""

from datetime import UTC, datetime

import pytest
from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import Event, Issue, Snapshot, Thread, User
from app.models import ReadingSession
from comic_pile.reading_session import create_session_start_snapshot


async def _snapshots(db: AsyncSession, session_id: int) -> list[Snapshot]:
    result = await db.execute(
        select(Snapshot).where(Snapshot.session_id == session_id).order_by(Snapshot.id)
    )
    return list(result.scalars().all())


@pytest.mark.asyncio
async def test_rate_undo_rate_undo_sequence(
    auth_client: AsyncClient,
    async_db: AsyncSession,
    default_user: User,
) -> None:
    """Walk the reported sequence and print each observed snapshot list."""
    session = ReadingSession(start_die=6, user_id=default_user.id, started_at=datetime.now(UTC))
    thread = Thread(
        title="Sequence Series",
        format="comic",
        issues_remaining=5,
        total_issues=5,
        reading_progress="in_progress",
        queue_position=1,
        status="active",
        user_id=default_user.id,
    )
    async_db.add_all([session, thread])
    await async_db.commit()
    await async_db.refresh(session)
    await async_db.refresh(thread)

    issue = Issue(thread_id=thread.id, issue_number="1", position=1, status="unread")
    async_db.add(issue)
    await async_db.commit()
    await async_db.refresh(issue)
    thread.next_unread_issue_id = issue.id
    await async_db.commit()

    await create_session_start_snapshot(async_db, session)

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

    print("\nAfter session start:", [(s.id, s.description, s.snapshot_kind) for s in await _snapshots(async_db, session.id)])

    # Rate #1
    r1 = await auth_client.post("/api/v1/rate/", json={"rating": 5.0, "issues_read": 1})
    print("rate1 status", r1.status_code, r1.json() if r1.status_code != 200 else "")
    print("After rate1:", [(s.id, s.description, s.snapshot_kind) for s in await _snapshots(async_db, session.id)])

    list1 = await auth_client.get(f"/api/v1/sessions/{session.id}/snapshots")
    print("session snapshots endpoint after rate1:", list1.status_code, list1.json())
    undo_list1 = await auth_client.get(f"/api/v1/undo/{session.id}/snapshots")
    print("undo snapshots endpoint after rate1:", undo_list1.status_code, undo_list1.json())
    hist1 = await auth_client.get("/api/v1/sessions/?page_size=50")
    print("history after rate1:", [(s["id"], s["snapshot_count"]) for s in hist1.json()["sessions"]])

    # Undo #1 (the newest non session-start snapshot)
    snaps = await _snapshots(async_db, session.id)
    delta1 = [s for s in snaps if s.description != "Session start"][-1]
    u1 = await auth_client.post(f"/api/v1/undo/{session.id}/undo/{delta1.id}")
    print("undo1 status", u1.status_code, u1.json() if u1.status_code != 200 else u1.json().get("snapshot_count"))
    print("After undo1:", [(s.id, s.description, s.snapshot_kind) for s in await _snapshots(async_db, session.id)])

    # Roll again, then rate #2
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
    r2 = await auth_client.post("/api/v1/rate/", json={"rating": 4.0, "issues_read": 1})
    print("rate2 status", r2.status_code, r2.json() if r2.status_code != 200 else "")
    print("After rate2:", [(s.id, s.description, s.snapshot_kind) for s in await _snapshots(async_db, session.id)])

    list2 = await auth_client.get(f"/api/v1/sessions/{session.id}/snapshots")
    print("session snapshots endpoint after rate2:", list2.status_code, list2.json())
    undo_list2 = await auth_client.get(f"/api/v1/undo/{session.id}/snapshots")
    print("undo snapshots endpoint after rate2:", undo_list2.status_code, undo_list2.json())
    hist2 = await auth_client.get("/api/v1/sessions/?page_size=50")
    print("history after rate2:", [(s["id"], s["snapshot_count"]) for s in hist2.json()["sessions"]])

    # Undo #2
    snaps2 = await _snapshots(async_db, session.id)
    delta2 = [s for s in snaps2 if s.description != "Session start"][-1]
    u2 = await auth_client.post(f"/api/v1/undo/{session.id}/undo/{delta2.id}")
    print("undo2 status", u2.status_code, u2.json())
    print("After undo2:", [(s.id, s.description, s.snapshot_kind) for s in await _snapshots(async_db, session.id)])

    await async_db.refresh(session)
    await async_db.refresh(thread)
    print("session ended_at", session.ended_at, "pending", session.pending_thread_id)
    print("thread issues_remaining", thread.issues_remaining, "last_rating", thread.last_rating)
