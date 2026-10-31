"""Thread tags must be visible on Queue rows and Roll die faces (issue #3425).

A tagged series used to look untagged everywhere except its own detail page,
so there was no at-a-glance signal for tag-based decisions such as "which
series are physical?" before rolling. These tests lock the list-surface
contract:

- Queue rows and Roll bootstrap rows carry the thread's visible direct tags
- an untagged thread reports an empty list rather than dropping the field
- the viewer's own private tags are included and another user's private tag is
  never leaked into a row they cannot edit
- the batch hydration used by both surfaces stays a single bounded read and
  returns nothing at all for an empty page
"""

from __future__ import annotations

from datetime import UTC, datetime

import pytest
from httpx import AsyncClient
from sqlalchemy import event, select
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession

from app.models import TagAssignment, Thread, User
from app.services.tag_inheritance_service import TagInheritanceService
from app.services.tag_service import TagService
from tests.conftest import get_or_create_user_async


async def _active_thread(
    db: AsyncSession,
    user_id: int,
    title: str,
    queue_position: int,
) -> Thread:
    """Insert one active, queued, unblocked thread owned by ``user_id``."""
    thread = Thread(
        user_id=user_id,
        title=title,
        format="Comic",
        issues_remaining=3,
        queue_position=queue_position,
        status="active",
        created_at=datetime.now(UTC),
    )
    db.add(thread)
    await db.commit()
    await db.refresh(thread)
    return thread


async def _private_tag(db: AsyncSession, user: User, name: str):
    """Create and return one private tag owned by ``user``."""
    created = await TagService(db).create_tag(user, name, color="blue", scope="private")
    return created.tag


@pytest.mark.asyncio
async def test_queue_rows_expose_visible_thread_tags(
    auth_client: AsyncClient,
    async_db: AsyncSession,
    default_user: User,
) -> None:
    """A Queue row carries the thread's direct tags; an untagged row carries none."""
    tagged = await _active_thread(async_db, default_user.id, "Spider-Man", 1)
    await _active_thread(async_db, default_user.id, "Untagged Saga", 2)

    physical = await _private_tag(async_db, default_user, "Physical")
    await TagService(async_db).assign_tag(
        default_user, physical.id, "Thread", tagged.id
    )

    response = await auth_client.get("/api/v1/threads/")
    assert response.status_code == 200, response.text
    rows = {row["title"]: row for row in response.json()["threads"]}

    assert [tag["name"] for tag in rows["Spider-Man"]["tags"]] == ["Physical"]
    assert rows["Spider-Man"]["tags"][0]["color"] == physical.color
    assert rows["Spider-Man"]["tags"][0]["scope"] == "private"
    assert rows["Untagged Saga"]["tags"] == []


@pytest.mark.asyncio
async def test_queue_rows_never_leak_another_users_private_tag(
    auth_client: AsyncClient,
    async_db: AsyncSession,
    default_user: User,
) -> None:
    """Another user's private tag stays invisible even if assigned to the row."""
    other = await get_or_create_user_async(async_db, username="tag_visibility_other")
    thread = await _active_thread(async_db, default_user.id, "Namor", 1)

    foreign = await _private_tag(async_db, other, "Other User Secret")
    # Assigning a foreign private tag is not reachable through TagService, so the
    # row is written directly to prove the read path filters it rather than
    # relying on the write path to prevent it.
    async_db.add(
        TagAssignment(
            tag_id=foreign.id,
            target_type="Thread",
            target_id=thread.id,
            created_at=datetime.now(UTC),
        )
    )
    await async_db.commit()

    response = await auth_client.get("/api/v1/threads/")
    assert response.status_code == 200, response.text
    rows = {row["title"]: row for row in response.json()["threads"]}

    assert rows["Namor"]["tags"] == []


@pytest.mark.asyncio
async def test_batch_tag_hydration_is_one_bounded_read(
    async_db: AsyncSession,
    db_engine: AsyncEngine,
    default_user: User,
) -> None:
    """Every requested thread resolves from one query regardless of page size."""
    for position in range(1, 4):
        await _active_thread(async_db, default_user.id, f"Batched {position}", position)

    physical = await _private_tag(async_db, default_user, "Physical")
    thread_ids = list(
        (
            await async_db.execute(
                select(Thread.id).where(Thread.user_id == default_user.id)
            )
        ).scalars()
    )
    for thread_id in thread_ids:
        await TagService(async_db).assign_tag(
            default_user, physical.id, "Thread", thread_id
        )

    select_statements: list[str] = []

    def _capture_statement(
        conn: object,
        cursor: object,
        statement: str,
        parameters: object,
        context: object,
        executemany: bool,
    ) -> None:
        if statement.lstrip().upper().startswith("SELECT"):
            select_statements.append(statement)

    event.listen(db_engine.sync_engine, "before_cursor_execute", _capture_statement)
    try:
        tags_by_thread = await TagInheritanceService(
            async_db
        ).get_threads_direct_tags(default_user.id, thread_ids)
    finally:
        event.remove(
            db_engine.sync_engine, "before_cursor_execute", _capture_statement
        )

    assert len(select_statements) == 1, select_statements
    assert set(tags_by_thread) == set(thread_ids)
    for tags in tags_by_thread.values():
        assert [tag.name for tag in tags] == ["Physical"]


@pytest.mark.asyncio
async def test_batch_tag_hydration_issues_no_query_for_an_empty_page(
    async_db: AsyncSession,
    db_engine: AsyncEngine,
    default_user: User,
) -> None:
    """An empty Queue page must not spend a query on tag hydration."""
    select_statements: list[str] = []

    def _capture_statement(
        conn: object,
        cursor: object,
        statement: str,
        parameters: object,
        context: object,
        executemany: bool,
    ) -> None:
        if statement.lstrip().upper().startswith("SELECT"):
            select_statements.append(statement)

    event.listen(db_engine.sync_engine, "before_cursor_execute", _capture_statement)
    try:
        tags_by_thread = await TagInheritanceService(
            async_db
        ).get_threads_direct_tags(default_user.id, [])
    finally:
        event.remove(
            db_engine.sync_engine, "before_cursor_execute", _capture_statement
        )

    assert tags_by_thread == {}
    assert select_statements == []
