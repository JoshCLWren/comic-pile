"""Regression for #2466: History must show historically rated issue, not current next.

Repro: two sessions on same migrated thread where thread advances between sessions.
After #6 is rated, thread's next becomes #7. History rows for #5 and #6 must not
both show #7.
"""

from datetime import UTC, datetime, timedelta

import pytest
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import Event, Issue, Thread
from app.models import Session as SessionModel
from app.models import User


@pytest.mark.asyncio
async def test_history_shows_rated_issue_not_current_next(
    auth_client: AsyncClient, async_db: AsyncSession, default_user: User
) -> None:
    """Older History rows remain stable after thread advances."""
    now = datetime.now(UTC)

    # Create migrated thread with 7 issues: 1-4 read, 5-7 unread, next is #5
    thread = Thread(
        title="Justice League Europe",
        format="Comic",
        issues_remaining=3,
        queue_position=1,
        user_id=default_user.id,
        total_issues=7,
        reading_progress="in_progress",
    )
    async_db.add(thread)
    await async_db.flush()

    issues: list[Issue] = []
    for i in range(1, 8):
        issues.append(
            Issue(
                thread_id=thread.id,
                issue_number=str(i),
                position=i,
                status="read" if i <= 4 else "unread",
                read_at=now if i <= 4 else None,
            )
        )
    async_db.add_all(issues)
    await async_db.flush()
    for iss in issues:
        await async_db.refresh(iss)

    # Map number -> issue id for convenience
    by_number = {iss.issue_number: iss for iss in issues}
    thread.next_unread_issue_id = by_number["5"].id
    await async_db.flush()

    # Session 1: rolled thread, rated #5 at Sep 10
    session1 = SessionModel(
        start_die=6,
        user_id=default_user.id,
        started_at=now - timedelta(days=1, hours=2),
    )
    async_db.add(session1)
    await async_db.flush()

    roll1 = Event(
        type="roll",
        session_id=session1.id,
        selected_thread_id=thread.id,
        die=6,
        result=4,
        selection_method="random",
        timestamp=now - timedelta(days=1, hours=2),
    )
    async_db.add(roll1)
    await async_db.flush()
    rate1 = Event(
        type="rate",
        session_id=session1.id,
        thread_id=thread.id,
        rating=4.0,
        issues_read=1,
        issue_id=by_number["5"].id,
        issue_number="5",
        timestamp=now - timedelta(days=1, hours=1),
    )
    async_db.add(rate1)
    await async_db.flush()

    # Advance thread after session1 rating: #5 becomes read, next is #6
    by_number["5"].status = "read"
    by_number["5"].read_at = now - timedelta(days=1, hours=1)
    thread.next_unread_issue_id = by_number["6"].id
    thread.issues_remaining = 2
    await async_db.flush()

    # Session 2: rolled same thread, rated #6 Sep 11 morning
    session2 = SessionModel(
        start_die=6,
        user_id=default_user.id,
        started_at=now - timedelta(hours=1),
    )
    async_db.add(session2)
    await async_db.flush()

    roll2 = Event(
        type="roll",
        session_id=session2.id,
        selected_thread_id=thread.id,
        die=6,
        result=5,
        selection_method="random",
        timestamp=now - timedelta(hours=1),
    )
    async_db.add(roll2)
    await async_db.flush()
    rate2 = Event(
        type="rate",
        session_id=session2.id,
        thread_id=thread.id,
        rating=4.0,
        issues_read=1,
        issue_id=by_number["6"].id,
        issue_number="6",
        timestamp=now - timedelta(minutes=30),
    )
    async_db.add(rate2)
    await async_db.flush()

    # Advance thread again: #6 read, next is #7 (current state)
    by_number["6"].status = "read"
    by_number["6"].read_at = now - timedelta(minutes=30)
    thread.next_unread_issue_id = by_number["7"].id
    thread.issues_remaining = 1
    await async_db.commit()

    # History should show #5 for session1 and #6 for session2, not #7 for both.
    resp = await auth_client.get("/api/v1/sessions/")
    assert resp.status_code == 200
    data = resp.json()
    by_id = {s["id"]: s for s in data["sessions"]}

    assert session1.id in by_id, "session1 should appear in history"
    assert session2.id in by_id, "session2 should appear in history"

    s1 = by_id[session1.id]
    s2 = by_id[session2.id]

    assert s1["active_thread"] is not None
    assert s1["active_thread"]["next_issue_number"] == "5"
    assert s1["active_thread"]["next_issue_id"] == by_number["5"].id
    # Deprecated aliases must also be historically pinned
    assert s1["active_thread"]["issue_number"] == "5"

    assert s2["active_thread"] is not None
    assert s2["active_thread"]["next_issue_number"] == "6"
    assert s2["active_thread"]["next_issue_id"] == by_number["6"].id

    # Re-fetch after thread is at #7 to prove stability (second read).
    resp2 = await auth_client.get("/api/v1/sessions/")
    assert resp2.status_code == 200
    by_id2 = {s["id"]: s for s in resp2.json()["sessions"]}
    assert by_id2[session1.id]["active_thread"]["next_issue_number"] == "5"
    assert by_id2[session2.id]["active_thread"]["next_issue_number"] == "6"


@pytest.mark.asyncio
async def test_history_without_rate_falls_back_to_current_next(
    auth_client: AsyncClient, async_db: AsyncSession, default_user: User
) -> None:
    """Sessions without a rate event still show the current next issue."""
    now = datetime.now(UTC)
    thread = Thread(
        title="Fallback Comic",
        format="Comic",
        issues_remaining=2,
        queue_position=1,
        user_id=default_user.id,
        total_issues=5,
        reading_progress="in_progress",
    )
    async_db.add(thread)
    await async_db.flush()
    issues = [
        Issue(thread_id=thread.id, issue_number=str(i), position=i, status="unread" if i > 3 else "read")
        for i in range(1, 6)
    ]
    async_db.add_all(issues)
    await async_db.flush()
    for iss in issues:
        await async_db.refresh(iss)
    thread.next_unread_issue_id = [i for i in issues if i.issue_number == "4"][0].id
    await async_db.flush()

    session = SessionModel(start_die=6, user_id=default_user.id, started_at=now)
    async_db.add(session)
    await async_db.flush()
    async_db.add(
        Event(
            type="roll",
            session_id=session.id,
            selected_thread_id=thread.id,
            die=6,
            result=3,
            selection_method="random",
            timestamp=now,
        )
    )
    await async_db.commit()

    resp = await auth_client.get("/api/v1/sessions/")
    assert resp.status_code == 200
    item = next(s for s in resp.json()["sessions"] if s["id"] == session.id)
    assert item["active_thread"] is not None
    assert item["active_thread"]["next_issue_number"] == "4"
