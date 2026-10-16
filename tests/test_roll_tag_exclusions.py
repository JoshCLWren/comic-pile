"""Tests for persistent account-wide tag exclusions in Roll eligibility."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from app.constants import validate_tag_color
from app.models import Tag, TagAssignment, Thread
from app.models.user import User
from app.schemas import RollBootstrapResponse, ThreadExclusionReason
from tests.conftest import get_or_create_user_async

EMPTY_POOL_TAG_DETAIL = "No candidates satisfy the current tag exclusions"


async def _tag(db: AsyncSession, user_id: int, name: str) -> Tag:
    """Persist one private tag owned by the user."""
    tag = Tag(
        name=name,
        normalized_name=name.lower(),
        scope="private",
        owner_user_id=user_id,
        color=validate_tag_color("red")[1],
    )
    db.add(tag)
    await db.flush()
    return tag


async def _thread_with_issue(
    db: AsyncSession, user: User, tag_id: int | None = None, thread_tag_id: int | None = None
) -> tuple[Thread, int]:
    thread = Thread(
        user_id=user.id,
        title="Tagged thread",
        format="Comic",
        issues_remaining=1,
        queue_position=1,
        status="active",
        created_at=datetime.now(UTC),
    )
    db.add(thread)
    await db.flush()

    from app.models.issue import Issue

    issue = Issue(thread_id=thread.id, issue_number="1", position=1, status="unread")
    db.add(issue)
    await db.flush()
    thread.next_unread_issue_id = issue.id

    if tag_id is not None:
        db.add(TagAssignment(tag_id=tag_id, target_type="Issue", target_id=issue.id))
    if thread_tag_id is not None:
        db.add(TagAssignment(tag_id=thread_tag_id, target_type="Thread", target_id=thread.id))
    await db.flush()

    return thread, issue.id


def _bootstrap(payload: RollBootstrapResponse) -> dict[int, ThreadExclusionReason]:
    return {item.thread_id: item for item in payload.excluded_threads}


@pytest.mark.asyncio
async def test_preferences_persist_excluded_tag_ids(
    auth_client: AsyncClient, async_db: AsyncSession
) -> None:
    """Excluded tag IDs persist through the preferences contract."""
    response = await auth_client.patch(
        "/api/v1/users/me/preferences", json={"excluded_tag_ids": [42, 7]}
    )
    assert response.status_code == 200
    assert sorted(response.json()["excluded_tag_ids"]) == [7, 42]

    follow_up = await auth_client.get("/api/v1/users/me/preferences")
    assert follow_up.status_code == 200
    assert sorted(follow_up.json()["excluded_tag_ids"]) == [7, 42]


@pytest.mark.asyncio
async def test_preferences_default_excluded_tag_ids_empty(
    auth_client: AsyncClient, async_db: AsyncSession
) -> None:
    """Users with no preferences row resolve to an empty exclusion list."""
    response = await auth_client.get("/api/v1/users/me/preferences")
    assert response.status_code == 200
    assert response.json()["excluded_tag_ids"] == []


@pytest.mark.asyncio
async def test_bootstrap_excludes_threads_with_excluded_tag(
    auth_client: AsyncClient, async_db: AsyncSession
) -> None:
    """A series whose next unread issue carries an excluded tag is not rollable."""
    user = await get_or_create_user_async(async_db)
    tag = await _tag(async_db, user.id, "Physical")
    tagged, _ = await _thread_with_issue(async_db, user, tag_id=tag.id)
    clean, _ = await _thread_with_issue(async_db, user)
    tagged.last_activity_at = datetime.now(UTC) - timedelta(days=14)
    clean.last_activity_at = datetime.now(UTC) - timedelta(days=14)
    await async_db.commit()

    patched = await auth_client.patch(
        "/api/v1/users/me/preferences", json={"excluded_tag_ids": [tag.id]}
    )
    assert patched.status_code == 200

    response = await auth_client.get("/api/v1/roll/bootstrap")
    assert response.status_code == 200
    payload = RollBootstrapResponse.model_validate(response.json())

    excluded = _bootstrap(payload)
    assert tagged.id in excluded
    assert excluded[tagged.id].reason == "excluded_tag"
    assert tagged.id not in {item.id for item in payload.roll_pool}
    assert clean.id in {item.id for item in payload.roll_pool}
    assert payload.available_threads == 1
    assert payload.stale_thread_count == 1
    assert payload.stale_thread is not None
    assert payload.stale_thread.id == clean.id


@pytest.mark.asyncio
async def test_bootstrap_excludes_threads_with_inherited_thread_tag(
    auth_client: AsyncClient, async_db: AsyncSession
) -> None:
    """Thread-level tags reach the issue through effective-tag inheritance."""
    user = await get_or_create_user_async(async_db)
    tag = await _tag(async_db, user.id, "Physical")
    tagged, _ = await _thread_with_issue(async_db, user, thread_tag_id=tag.id)
    clean, _ = await _thread_with_issue(async_db, user)
    await async_db.commit()

    patched = await auth_client.patch(
        "/api/v1/users/me/preferences", json={"excluded_tag_ids": [tag.id]}
    )
    assert patched.status_code == 200

    response = await auth_client.get("/api/v1/roll/bootstrap")
    assert response.status_code == 200
    payload = RollBootstrapResponse.model_validate(response.json())

    excluded = _bootstrap(payload)
    assert tagged.id in excluded
    assert excluded[tagged.id].reason == "excluded_tag"
    assert clean.id in {item.id for item in payload.roll_pool}


@pytest.mark.asyncio
async def test_roll_never_selects_tag_excluded_thread(
    auth_client: AsyncClient, async_db: AsyncSession
) -> None:
    """A roll with an active exclusion always lands on an eligible series."""
    user = await get_or_create_user_async(async_db)
    tag = await _tag(async_db, user.id, "Physical")
    tagged, _ = await _thread_with_issue(async_db, user, tag_id=tag.id)
    clean, _ = await _thread_with_issue(async_db, user)
    await async_db.commit()

    patched = await auth_client.patch(
        "/api/v1/users/me/preferences", json={"excluded_tag_ids": [tag.id]}
    )
    assert patched.status_code == 200

    response = await auth_client.post("/api/v1/roll/")
    assert response.status_code == 200
    data = response.json()
    assert data["thread_id"] == clean.id
    assert data["thread_id"] != tagged.id


@pytest.mark.asyncio
async def test_roll_v1_add_and_list_exclusions(
    auth_client: AsyncClient, async_db: AsyncSession
) -> None:
    """The versioned Roll endpoints manage exclusions and resolve summaries."""
    user = await get_or_create_user_async(async_db)
    tag = await _tag(async_db, user.id, "Physical")
    await async_db.commit()

    added = await auth_client.post(
        "/api/v1/roll/tag-exclusions", json={"tag_id": tag.id}
    )
    assert added.status_code == 200
    added_data = added.json()
    assert added_data["excluded_tag_ids"] == [tag.id]
    assert [item["name"] for item in added_data["excluded_tags"]] == ["Physical"]
    assert added_data["rerolled"] is False

    listed = await auth_client.get("/api/v1/roll/tag-exclusions")
    assert listed.status_code == 200
    listed_data = listed.json()
    assert listed_data["excluded_tag_ids"] == [tag.id]
    assert [item["id"] for item in listed_data["excluded_tags"]] == [tag.id]


@pytest.mark.asyncio
async def test_roll_v1_remove_exclusion_restores_eligibility(
    auth_client: AsyncClient, async_db: AsyncSession
) -> None:
    """Removing an exclusion makes matching candidates eligible immediately."""
    user = await get_or_create_user_async(async_db)
    tag = await _tag(async_db, user.id, "Physical")
    tagged, _ = await _thread_with_issue(async_db, user, tag_id=tag.id)
    await async_db.commit()

    added = await auth_client.post(
        "/api/v1/roll/tag-exclusions", json={"tag_id": tag.id}
    )
    assert added.status_code == 200

    removed = await auth_client.delete(f"/api/v1/roll/tag-exclusions/{tag.id}")
    assert removed.status_code == 200
    assert removed.json()["excluded_tag_ids"] == []

    response = await auth_client.get("/api/v1/roll/bootstrap")
    assert response.status_code == 200
    payload = RollBootstrapResponse.model_validate(response.json())
    assert tagged.id in {item.id for item in payload.roll_pool}
    assert tagged.id not in _bootstrap(payload)


@pytest.mark.asyncio
async def test_mid_roll_exclusion_auto_rerolls_without_snooze_side_effects(
    auth_client: AsyncClient, async_db: AsyncSession
) -> None:
    """Excluding the pending roll's tag rerolls neutrally (issue #3033)."""
    user = await get_or_create_user_async(async_db)
    tag = await _tag(async_db, user.id, "Physical")
    tagged, _ = await _thread_with_issue(async_db, user, tag_id=tag.id)
    await async_db.commit()

    first_roll = await auth_client.post("/api/v1/roll/")
    assert first_roll.status_code == 200
    assert first_roll.json()["thread_id"] == tagged.id

    clean, _ = await _thread_with_issue(async_db, user)
    await async_db.commit()

    excluded = await auth_client.post(
        "/api/v1/roll/tag-exclusions", json={"tag_id": tag.id}
    )
    assert excluded.status_code == 200
    excluded_data = excluded.json()
    assert excluded_data["rerolled"] is True
    assert excluded_data["roll"] is not None
    assert excluded_data["roll"]["thread_id"] == clean.id

    response = await auth_client.get("/api/v1/roll/bootstrap")
    assert response.status_code == 200
    payload = RollBootstrapResponse.model_validate(response.json())
    assert payload.pending_thread_id == clean.id
    assert payload.snoozed_count == 0
    assert tagged.id not in {item.id for item in payload.snoozed_threads}
    bootstrap_excluded = _bootstrap(payload)
    assert bootstrap_excluded[tagged.id].reason == "excluded_tag"


@pytest.mark.asyncio
async def test_empty_pool_explains_tag_exclusions_and_clears_pending(
    auth_client: AsyncClient, async_db: AsyncSession
) -> None:
    """An exclusion-emptied pool explains itself instead of falling back."""
    user = await get_or_create_user_async(async_db)
    tag = await _tag(async_db, user.id, "Physical")
    tagged, _ = await _thread_with_issue(async_db, user, tag_id=tag.id)
    await async_db.commit()

    first_roll = await auth_client.post("/api/v1/roll/")
    assert first_roll.status_code == 200
    assert first_roll.json()["thread_id"] == tagged.id

    excluded = await auth_client.post(
        "/api/v1/roll/tag-exclusions", json={"tag_id": tag.id}
    )
    assert excluded.status_code == 400
    assert excluded.json()["detail"] == EMPTY_POOL_TAG_DETAIL

    reroll_attempt = await auth_client.post("/api/v1/roll/")
    assert reroll_attempt.status_code == 400
    assert reroll_attempt.json()["detail"] == EMPTY_POOL_TAG_DETAIL

    response = await auth_client.get("/api/v1/roll/bootstrap")
    assert response.status_code == 200
    payload = RollBootstrapResponse.model_validate(response.json())
    assert payload.pending_thread_id is None
    bootstrap_excluded = _bootstrap(payload)
    assert bootstrap_excluded[tagged.id].reason == "excluded_tag"
