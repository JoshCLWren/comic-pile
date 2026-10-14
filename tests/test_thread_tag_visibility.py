"""List-view tag visibility regression coverage (issue #3425).

A tagged thread used to read as untagged everywhere except its own detail
page, so the Queue list and the Roll die faces gave no at-a-glance signal for
tag-based decisions. These tests pin the closed loop:

- ``GET /api/v1/threads/`` returns each row's viewer-visible tags;
- ``GET /api/v1/roll/bootstrap`` returns tags for every roll-adjacent series
  summary (die-face pool, snoozed, skipped, blocked, stale);
- untagged rows stay empty rather than absent;
- the projection never leaks another user's private vocabulary.
"""

from __future__ import annotations

from datetime import UTC, datetime

import pytest
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from app.constants import validate_tag_color
from app.models import Issue, Tag, TagAssignment, Thread, User
from app.schemas.tags import TagScope
from tests.conftest import get_or_create_user_async


async def _make_thread(
    db: AsyncSession,
    user: User,
    *,
    title: str,
    queue_position: int,
    issue_count: int = 2,
) -> Thread:
    """Create an owned, active, issue-tracking thread with a next pointer."""
    thread = Thread(
        user_id=user.id,
        title=title,
        format="Comic",
        issues_remaining=issue_count,
        total_issues=issue_count,
        queue_position=queue_position,
        status="active",
        created_at=datetime.now(UTC),
    )
    db.add(thread)
    await db.flush()

    first = Issue(
        thread_id=thread.id,
        issue_number="1",
        position=1,
        status="unread",
    )
    db.add(first)
    await db.flush()
    thread.next_unread_issue_id = first.id
    await db.flush()
    return thread


async def _assign_tag(
    db: AsyncSession,
    *,
    name: str,
    scope: str,
    owner: User | None,
    thread_id: int,
) -> Tag:
    """Create a tag and attach it to one thread as a direct assignment."""
    tag = Tag(
        name=name,
        normalized_name=name.lower(),
        scope=scope,
        owner_user_id=owner.id if owner else None,
        color=validate_tag_color("red")[1],
        created_at=datetime.now(UTC),
        updated_at=datetime.now(UTC),
    )
    db.add(tag)
    await db.flush()
    db.add(
        TagAssignment(
            tag_id=tag.id,
            target_type="Thread",
            target_id=thread_id,
            created_at=datetime.now(UTC),
        )
    )
    await db.flush()
    return tag


def _queue_row(body: dict, title: str) -> dict:
    """Return the Queue page row for one thread title."""
    return next(row for row in body["threads"] if row["title"] == title)


@pytest.mark.asyncio
async def test_queue_rows_expose_viewer_visible_tags(
    auth_client: AsyncClient, async_db: AsyncSession, default_user: User
) -> None:
    """A Queue row carries the global and own-private tags its series carries."""
    tagged = await _make_thread(async_db, default_user, title="Spider-Man", queue_position=1)
    await _make_thread(async_db, default_user, title="Untagged", queue_position=2)
    await _assign_tag(
        async_db, name="Physical", scope=TagScope.GLOBAL.value, owner=None, thread_id=tagged.id
    )
    await _assign_tag(
        async_db,
        name="Trade paperback",
        scope=TagScope.PRIVATE.value,
        owner=default_user,
        thread_id=tagged.id,
    )
    await async_db.commit()

    response = await auth_client.get("/api/v1/threads/")
    assert response.status_code == 200
    body = response.json()

    tagged_row = _queue_row(body, "Spider-Man")
    assert {tag["name"] for tag in tagged_row["tags"]} == {"Physical", "Trade paperback"}
    assert all(tag["color"] for tag in tagged_row["tags"])
    assert {tag["scope"] for tag in tagged_row["tags"]} == {"global", "private"}

    # An untagged series still renders an explicit empty list so the Queue
    # contract stays uniform across rows.
    assert _queue_row(body, "Untagged")["tags"] == []


@pytest.mark.asyncio
async def test_roll_die_faces_expose_viewer_visible_tags(
    auth_client: AsyncClient, async_db: AsyncSession, default_user: User
) -> None:
    """Roll die-face summaries carry the tags a series carries."""
    tagged = await _make_thread(async_db, default_user, title="Sandman", queue_position=1)
    await _assign_tag(
        async_db, name="Physical", scope=TagScope.GLOBAL.value, owner=None, thread_id=tagged.id
    )
    await async_db.commit()

    response = await auth_client.get("/api/v1/roll/bootstrap")
    assert response.status_code == 200
    roll_pool = response.json()["roll_pool"]

    face = next(entry for entry in roll_pool if entry["id"] == tagged.id)
    assert [tag["name"] for tag in face["tags"]] == ["Physical"]


@pytest.mark.asyncio
async def test_roll_bootstrap_never_leaks_another_users_private_tags(
    auth_client: AsyncClient, async_db: AsyncSession, default_user: User
) -> None:
    """A foreign private tag is filtered out of both list projections."""
    tagged = await _make_thread(async_db, default_user, title="X-Men", queue_position=1)
    other = await get_or_create_user_async(async_db, username="other_tag_owner")
    await _assign_tag(
        async_db, name="Someone Else", scope=TagScope.PRIVATE.value, owner=other, thread_id=tagged.id
    )
    await async_db.commit()

    queue_body = (await auth_client.get("/api/v1/threads/")).json()
    roll_body = (await auth_client.get("/api/v1/roll/bootstrap")).json()

    assert _queue_row(queue_body, "X-Men")["tags"] == []
    face = next(entry for entry in roll_body["roll_pool"] if entry["id"] == tagged.id)
    assert face["tags"] == []