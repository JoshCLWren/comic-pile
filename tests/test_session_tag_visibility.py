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

from sqlalchemy.ext.asyncio import AsyncSession

from app.models import Event, ReadingSession, Thread, User
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




