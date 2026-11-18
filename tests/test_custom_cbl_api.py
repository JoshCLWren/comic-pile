"""End-to-end API coverage for user-authored CBL lists."""

from datetime import UTC, datetime

import pytest
from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.custom_cbl import CustomCBLEntry, CustomCBLList
from app.models.issue import Issue
from app.models.thread import Thread
from app.models.user import User
from tests.conftest import get_or_create_user_async


@pytest.mark.asyncio
async def test_inactive_intent_survives_legacy_save(
    auth_client: AsyncClient, async_db: AsyncSession
) -> None:
    """A legacy save retains stored list intent and historical checkpoint targets."""
    user = await get_or_create_user_async(async_db)
    first = await _issue(
        async_db, user_id=user.id, title="First", issue_number="1", queue_position=1
    )
    second = await _issue(
        async_db, user_id=user.id, title="Second", issue_number="1", queue_position=2
    )
    await async_db.commit()
    issue_ids = [first.id, second.id]
    first_id, second_id = issue_ids
    created = await auth_client.post(
        "/api/v1/custom-cbls",
        json={
            "name": "Order",
            "issue_ids": issue_ids,
            "checkpoint_targets": {str(first.id): [second.id]},
        },
    )
    assert created.status_code == 201, created.text
    list_id = created.json()["id"]
    list_row = await async_db.get(CustomCBLList, list_id)
    assert list_row is not None
    assert list_row.mode == "loose"
    list_row.mode = "strict"
    rows = (
        (
            await async_db.execute(
                select(CustomCBLEntry)
                .where(CustomCBLEntry.list_id == list_id)
                .order_by(CustomCBLEntry.position)
            )
        )
        .scalars()
        .all()
    )
    assert [row.gate for row in rows] == ["none", "none"]
    assert [row.skipped for row in rows] == [False, False]
    rows[0].skipped = True
    rows[1].gate = "after_previous"
    await async_db.commit()
    saved = await auth_client.put(
        f"/api/v1/custom-cbls/{list_id}",
        json={
            "name": "Order",
            "issue_ids": issue_ids,
        },
    )
    assert saved.status_code == 200, saved.text
    async_db.expire_all()
    list_row = await async_db.get(CustomCBLList, list_id)
    assert list_row is not None and list_row.mode == "strict"
    rows = (
        (
            await async_db.execute(
                select(CustomCBLEntry)
                .where(CustomCBLEntry.list_id == list_id)
                .order_by(CustomCBLEntry.position)
            )
        )
        .scalars()
        .all()
    )
    assert [(row.issue_id, row.position, row.gate, row.skipped) for row in rows] == [
        (first_id, 0, "none", True),
        (second_id, 1, "after_previous", False),
    ]
    assert rows[0].checkpoint_target_issue_ids == [second_id]
    for response in (saved, await auth_client.get(f"/api/v1/custom-cbls/{list_id}")):
        assert response.status_code == 200
        assert response.json()["mode"] == "strict"
        assert [(entry["gate"], entry["skipped"]) for entry in response.json()["entries"]] == [
            ("none", True),
            ("after_previous", False),
        ]
    listing = await auth_client.get("/api/v1/custom-cbls")
    assert listing.json()[0]["mode"] == "strict"




@pytest.mark.asyncio
async def test_custom_cbl_removed_target_does_not_redirect_checkpoint(
    auth_client: AsyncClient,
    async_db: AsyncSession,
) -> None:
    """Removing the exact target clears the source flag rather than blocking its neighbor."""
    user = await get_or_create_user_async(async_db)
    issues = [
        await _issue(async_db, user_id=user.id, title=title, issue_number="1", queue_position=index)
        for index, title in enumerate(["Source", "Target", "Neighbor"], 1)
    ]
    ids = [issue.id for issue in issues]
    await async_db.commit()
    created = await auth_client.post(
        "/api/v1/custom-cbls",
        json={
            "name": "Remove target",
            "issue_ids": ids,
            "checkpoint_targets": {str(ids[0]): [ids[1]]},
        },
    )
    assert created.status_code == 201, created.text
    updated = await auth_client.put(
        f"/api/v1/custom-cbls/{created.json()['id']}",
        json={
            "name": "Remove target",
            "issue_ids": [ids[0], ids[2]],
            "checkpoint_issue_ids": [ids[0]],
        },
    )
    assert updated.status_code == 200, updated.text
    assert updated.json()["entries"][0]["checkpoint_target_issue_ids"] == []
    assert updated.json()["entries"][0]["is_checkpoint"] is False


@pytest.mark.asyncio
@pytest.mark.parametrize("clear_targets", [False, True])
async def test_custom_cbl_explicit_checkpoint_can_be_disabled_by_existing_client(
    auth_client: AsyncClient,
    async_db: AsyncSession,
    clear_targets: bool,
) -> None:
    """Explicitly empty flag selection clears targets; omission preserves them."""
    user = await get_or_create_user_async(async_db)
    source = await _issue(
        async_db, user_id=user.id, title="Source", issue_number="1", queue_position=1
    )
    target = await _issue(
        async_db, user_id=user.id, title="Target", issue_number="1", queue_position=2
    )
    ids = [source.id, target.id]
    await async_db.commit()
    created = await auth_client.post(
        "/api/v1/custom-cbls",
        json={
            "name": "Disable checkpoint",
            "issue_ids": ids,
            "checkpoint_targets": {str(ids[0]): [ids[1]]},
        },
    )
    assert created.status_code == 201, created.text
    updated = await auth_client.put(
        f"/api/v1/custom-cbls/{created.json()['id']}",
        json={
            "name": "Disable checkpoint",
            "issue_ids": ids,
            "checkpoint_issue_ids": [ids[0]] if clear_targets else [],
            **({"checkpoint_targets": {}} if clear_targets else {}),
        },
    )
    assert updated.status_code == 200, updated.text
    assert updated.json()["entries"][0]["checkpoint_target_issue_ids"] == []
    assert updated.json()["entries"][0]["is_checkpoint"] is False


async def _issue(
    db: AsyncSession,
    *,
    user_id: int,
    title: str,
    issue_number: str,
    queue_position: int,
) -> Issue:
    """Create one canonical owned issue in its real thread."""
    thread = Thread(
        title=title,
        format="comic",
        issues_remaining=1,
        queue_position=queue_position,
        status="active",
        user_id=user_id,
        total_issues=1,
        reading_progress="unstarted",
        created_at=datetime.now(UTC),
    )
    db.add(thread)
    await db.flush()
    issue = Issue(
        thread_id=thread.id,
        issue_number=issue_number,
        position=1,
        status="unread",
    )
    db.add(issue)
    await db.flush()
    return issue


def _plan_payload(issue_ids: list[int], *, mode: str = "informational") -> dict[str, object]:
    """Build a minimal one-lane Reading Plan payload."""
    return {
        "name": "Starman into JSA",
        "ordering_mode": mode,
        "lanes": [{"id": "main", "name": "Main", "order": 0}],
        "nodes": [
            {
                "id": f"issue-{issue_id}",
                "node_type": "issue",
                "ref_id": issue_id,
                "lane_id": "main",
                "position": position,
            }
            for position, issue_id in enumerate(issue_ids)
        ],
    }




@pytest.mark.asyncio
async def test_custom_cbl_rejects_checkpoint_outside_membership(
    auth_client: AsyncClient,
    async_db: AsyncSession,
) -> None:
    """A checkpoint must name an issue that is already in the custom CBL."""
    user = await get_or_create_user_async(async_db)
    owned = await _issue(
        async_db,
        user_id=user.id,
        title="Starman",
        issue_number="55",
        queue_position=1,
    )
    await async_db.commit()

    response = await auth_client.post(
        "/api/v1/custom-cbls",
        json={
            "name": "Bad checkpoint",
            "issue_ids": [owned.id],
            "checkpoint_issue_ids": [owned.id + 999],
        },
    )
    assert response.status_code == 422, response.text




@pytest.mark.asyncio
async def test_custom_cbl_rejects_issue_owned_by_another_user(
    auth_client: AsyncClient,
    async_db: AsyncSession,
) -> None:
    """Custom CBL membership cannot smuggle another user's issue reference."""
    await get_or_create_user_async(async_db)
    other = User(username="other-cbl-user", email="other-cbl@example.com", password_hash="unused")
    async_db.add(other)
    await async_db.flush()
    foreign_issue = await _issue(
        async_db,
        user_id=other.id,
        title="Foreign Series",
        issue_number="1",
        queue_position=1,
    )
    await async_db.commit()

    response = await auth_client.post(
        "/api/v1/custom-cbls",
        json={"name": "Nope", "issue_ids": [foreign_issue.id]},
    )
    assert response.status_code == 422
    assert response.json()["detail"]["code"] == "custom_cbl_issue_not_owned"






