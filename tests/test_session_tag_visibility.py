"""Session surfaces must expose the active thread's tags (issue #3759).

Split from #3425: Queue rows and Roll die faces already carry tags, but the
History list and the session/current payload still dropped them, so a reader
could not see tag context next to past or in-progress rolls. These tests lock
the session-surface contract:

- a History row carries the rolled thread's visible direct tags
- the current-session payload carries tags on both the pending-thread and
  rolled-thread resolution paths
- an untagged active thread reports an empty list rather than dropping the field
- another user's private tag is never leaked into a session row
"""

from __future__ import annotations

from datetime import UTC, datetime

import pytest
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import Event, ReadingSession, TagAssignment, Thread, User
from app.services.tag_service import TagService


async def _session_with_thread(
    db: AsyncSession,
    user_id: int,
    thread: Thread,
    *,
    pending: bool,
) -> ReadingSession:
    """Insert one open session whose active thread is ``thread``.

    Args:
        db: Database session.
        user_id: Owner of the session and thread.
        thread: Thread selected by the session's roll event.
        pending: When True, also mark the thread as the session's pending
            thread so the pending-first resolution branch is exercised.

    Returns:
        The committed reading session.
    """
    session = ReadingSession(start_die=10, user_id=user_id)
    db.add(session)
    await db.commit()
    await db.refresh(session)

    db.add(
        Event(
            type="roll",
            die=10,
            result=1,
            selected_thread_id=thread.id,
            selection_method="random",
            session_id=session.id,
            thread_id=thread.id,
        )
    )
    if pending:
        session.pending_thread_id = thread.id
    await db.commit()
    await db.refresh(session)
    return session


async def _thread(db: AsyncSession, user_id: int, title: str) -> Thread:
    """Insert one active thread owned by ``user_id``."""
    thread = Thread(
        user_id=user_id,
        title=title,
        format="Comic",
        issues_remaining=3,
        queue_position=1,
        status="active",
        created_at=datetime.now(UTC),
    )
    db.add(thread)
    await db.commit()
    await db.refresh(thread)
    return thread


async def _tag_and_assign(
    db: AsyncSession, user: User, thread: Thread, name: str
) -> None:
    """Create one private tag for ``user`` and assign it to ``thread``."""
    created = await TagService(db).create_tag(user, name, color="blue", scope="private")
    await TagService(db).assign_tag(user, created.tag.id, "Thread", thread.id)


@pytest.mark.asyncio
async def test_history_rows_expose_visible_thread_tags(
    auth_client: AsyncClient,
    async_db: AsyncSession,
    default_user: User,
) -> None:
    """A History row carries the rolled thread's direct tags."""
    tagged = await _thread(async_db, default_user.id, "Spider-Man")
    await _session_with_thread(async_db, default_user.id, tagged, pending=False)
    await _tag_and_assign(async_db, default_user, tagged, "Physical")

    response = await auth_client.get("/api/v1/sessions/")
    assert response.status_code == 200, response.text
    rows = response.json()["sessions"]
    active = next(
        row["active_thread"]
        for row in rows
        if row["active_thread"] and row["active_thread"]["id"] == tagged.id
    )
    assert [tag["name"] for tag in active["tags"]] == ["Physical"]
    assert active["tags"][0]["scope"] == "private"


@pytest.mark.asyncio
async def test_current_session_pending_thread_exposes_tags(
    auth_client: AsyncClient,
    async_db: AsyncSession,
    default_user: User,
) -> None:
    """The current-session payload carries tags on the pending-thread path."""
    tagged = await _thread(async_db, default_user.id, "X-Men")
    session = await _session_with_thread(async_db, default_user.id, tagged, pending=True)
    await _tag_and_assign(async_db, default_user, tagged, "Physical")

    response = await auth_client.get(f"/api/v1/sessions/{session.id}")
    assert response.status_code == 200, response.text
    active = response.json()["active_thread"]
    assert active is not None
    assert active["id"] == tagged.id
    assert [tag["name"] for tag in active["tags"]] == ["Physical"]


@pytest.mark.asyncio
async def test_current_session_rolled_thread_exposes_tags(
    auth_client: AsyncClient,
    async_db: AsyncSession,
    default_user: User,
) -> None:
    """The current-session payload carries tags on the rolled-thread path."""
    tagged = await _thread(async_db, default_user.id, "Fantastic Four")
    session = await _session_with_thread(async_db, default_user.id, tagged, pending=False)
    await _tag_and_assign(async_db, default_user, tagged, "Physical")

    response = await auth_client.get("/api/v1/sessions/current/")
    assert response.status_code == 200, response.text
    data = response.json()
    assert data["id"] == session.id
    active = data["active_thread"]
    assert active is not None
    assert active["id"] == tagged.id
    assert [tag["name"] for tag in active["tags"]] == ["Physical"]


@pytest.mark.asyncio
async def test_untagged_active_thread_reports_empty_tag_list(
    auth_client: AsyncClient,
    async_db: AsyncSession,
    default_user: User,
) -> None:
    """An untagged active thread carries an empty tags list, not a missing field."""
    untagged = await _thread(async_db, default_user.id, "Untagged Saga")
    session = await _session_with_thread(async_db, default_user.id, untagged, pending=False)

    response = await auth_client.get(f"/api/v1/sessions/{session.id}")
    assert response.status_code == 200, response.text
    active = response.json()["active_thread"]
    assert active is not None
    assert active["tags"] == []


@pytest.mark.asyncio
async def test_history_rows_never_leak_another_users_private_tag(
    auth_client: AsyncClient,
    async_db: AsyncSession,
    default_user: User,
) -> None:
    """Another user's private tag stays invisible on a History row."""
    from tests.conftest import get_or_create_user_async

    other = await get_or_create_user_async(async_db, username="session_tag_visibility_other")
    thread = await _thread(async_db, default_user.id, "Namor")
    await _session_with_thread(async_db, default_user.id, thread, pending=False)

    foreign_created = await TagService(async_db).create_tag(
        other, "Other User Secret", color="blue", scope="private"
    )
    # Assigning a foreign private tag is not reachable through TagService, so the
    # row is written directly to prove the read path filters it.
    async_db.add(
        TagAssignment(
            tag_id=foreign_created.tag.id,
            target_type="Thread",
            target_id=thread.id,
            created_at=datetime.now(UTC),
        )
    )
    await async_db.commit()

    response = await auth_client.get("/api/v1/sessions/")
    assert response.status_code == 200, response.text
    rows = response.json()["sessions"]
    active = next(
        row["active_thread"]
        for row in rows
        if row["active_thread"] and row["active_thread"]["id"] == thread.id
    )
    assert active["tags"] == []
