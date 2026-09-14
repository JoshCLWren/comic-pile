"""End-to-end API coverage for user-authored CBL lists."""

from copy import deepcopy
from datetime import UTC, datetime
from unittest.mock import AsyncMock

import pytest
from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.continuity_plan import ContinuityPlan
from app.models.continuity_rule import ContinuityRule
from app.models.issue import Issue
from app.models.thread import Thread
from app.models.user import User
from app.services import custom_cbl as custom_cbl_service
from tests.conftest import get_or_create_user_async


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
async def test_custom_cbl_create_edit_export_and_apply_without_synthetic_threads(
    auth_client: AsyncClient,
    async_db: AsyncSession,
) -> None:
    """A custom CBL anchors source order at an existing real issue without fake threads."""
    user = await get_or_create_user_async(async_db)
    starman = await _issue(
        async_db,
        user_id=user.id,
        title="Starman",
        issue_number="55",
        queue_position=1,
    )
    starman_next = Issue(
        thread_id=starman.thread_id,
        issue_number="56",
        position=2,
        status="unread",
    )
    async_db.add(starman_next)
    await async_db.flush()
    all_star = await _issue(
        async_db,
        user_id=user.id,
        title="All-Star Comics",
        issue_number="1",
        queue_position=2,
    )
    jsa = await _issue(
        async_db,
        user_id=user.id,
        title="JSA",
        issue_number="1",
        queue_position=3,
    )
    await async_db.commit()

    created = await auth_client.post(
        "/api/v1/custom-cbls",
        json={
            "name": "Starman + JSA",
            "description": "My bridge into JSA",
            "issue_ids": [starman.id, all_star.id, jsa.id],
        },
    )
    assert created.status_code == 201, created.text
    custom = created.json()
    assert [entry["series_name"] for entry in custom["entries"]] == [
        "Starman",
        "All-Star Comics",
        "JSA",
    ]
    assert [entry["issue_number"] for entry in custom["entries"]] == ["55", "1", "1"]

    updated = await auth_client.put(
        f"/api/v1/custom-cbls/{custom['id']}",
        json={
            "name": "Starman + JSA",
            "description": "My bridge into JSA",
            "issue_ids": [starman.id, jsa.id, all_star.id],
        },
    )
    assert updated.status_code == 200, updated.text
    assert [entry["issue_id"] for entry in updated.json()["entries"]] == [
        starman.id,
        jsa.id,
        all_star.id,
    ]

    exported = await auth_client.get(f"/api/v1/custom-cbls/{custom['id']}/export")
    assert exported.status_code == 200
    assert 'Series="Starman" Number="55"' in exported.text
    assert 'Series="JSA" Number="1"' in exported.text

    plan = await auth_client.post(
        "/api/v1/continuity-plans/",
        json=_plan_payload([starman.id, starman_next.id]),
    )
    assert plan.status_code == 201, plan.text

    applied = await auth_client.post(
        f"/api/v1/custom-cbls/{custom['id']}/reading-plans/{plan.json()['id']}:apply",
        json={},
    )
    assert applied.status_code == 200, applied.text
    body = applied.json()
    assert body["skipped_existing_issue_ids"] == [starman.id]
    assert body["added_issue_ids"] == [jsa.id, all_star.id]
    assert [node["ref_id"] for node in body["nodes"]] == [
        starman.id,
        jsa.id,
        all_star.id,
        starman_next.id,
    ]
    assert body["nodes"][0]["source_paths"] == [f"custom-cbl:{custom['id']}"]
    assert body["nodes"][1]["source_paths"] == [f"custom-cbl:{custom['id']}"]

    threads = (
        await async_db.execute(select(Thread).where(Thread.user_id == user.id).order_by(Thread.id))
    ).scalars().all()
    assert [thread.title for thread in threads] == ["Starman", "All-Star Comics", "JSA"]


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


@pytest.mark.asyncio
async def test_custom_cbl_strict_plan_application_uses_canonical_rule_compiler(
    auth_client: AsyncClient,
    async_db: AsyncSession,
) -> None:
    """Applying custom material to a strict plan recompiles adjacent hard gates."""
    user = await get_or_create_user_async(async_db)
    first = await _issue(
        async_db,
        user_id=user.id,
        title="Starman",
        issue_number="55",
        queue_position=1,
    )
    second = await _issue(
        async_db,
        user_id=user.id,
        title="All-Star Comics",
        issue_number="1",
        queue_position=2,
    )
    third = await _issue(
        async_db,
        user_id=user.id,
        title="JSA",
        issue_number="1",
        queue_position=3,
    )
    await async_db.commit()

    custom = await auth_client.post(
        "/api/v1/custom-cbls",
        json={"name": "Strict bridge", "issue_ids": [first.id, second.id, third.id]},
    )
    assert custom.status_code == 201, custom.text
    plan = await auth_client.post(
        "/api/v1/continuity-plans/",
        json=_plan_payload([first.id], mode="strict_sequential"),
    )
    assert plan.status_code == 201, plan.text

    applied = await auth_client.post(
        f"/api/v1/custom-cbls/{custom.json()['id']}/reading-plans/{plan.json()['id']}:apply",
        json={},
    )
    assert applied.status_code == 200, applied.text
    assert applied.json()["skipped_existing_issue_ids"] == [first.id]

    rules = (
        await async_db.execute(
            select(ContinuityRule)
            .where(ContinuityRule.user_id == user.id)
            .order_by(ContinuityRule.id)
        )
    ).scalars().all()
    assert [(rule.source_id, rule.target_id) for rule in rules] == [
        (first.id, second.id),
        (second.id, third.id),
    ]


@pytest.mark.asyncio
async def test_custom_cbl_skips_existing_issue_in_another_lane(
    auth_client: AsyncClient,
    async_db: AsyncSession,
) -> None:
    """Applying a list never moves or duplicates an issue that already lives in another lane."""
    user = await get_or_create_user_async(async_db)
    anchor = await _issue(
        async_db,
        user_id=user.id,
        title="Starman",
        issue_number="55",
        queue_position=1,
    )
    existing_other_lane = await _issue(
        async_db,
        user_id=user.id,
        title="All-Star Comics",
        issue_number="1",
        queue_position=2,
    )
    new_issue = await _issue(
        async_db,
        user_id=user.id,
        title="JSA",
        issue_number="1",
        queue_position=3,
    )
    await async_db.commit()

    custom = await auth_client.post(
        "/api/v1/custom-cbls",
        json={
            "name": "Cross-lane bridge",
            "issue_ids": [anchor.id, existing_other_lane.id, new_issue.id],
        },
    )
    assert custom.status_code == 201, custom.text

    plan = await auth_client.post(
        "/api/v1/continuity-plans/",
        json={
            "name": "Two-lane plan",
            "ordering_mode": "informational",
            "lanes": [
                {"id": "main", "name": "Main", "order": 0},
                {"id": "side", "name": "Side", "order": 1},
            ],
            "nodes": [
                {
                    "id": "anchor",
                    "node_type": "issue",
                    "ref_id": anchor.id,
                    "lane_id": "main",
                    "position": 0,
                },
                {
                    "id": "existing-side",
                    "node_type": "issue",
                    "ref_id": existing_other_lane.id,
                    "lane_id": "side",
                    "position": 0,
                },
            ],
        },
    )
    assert plan.status_code == 201, plan.text

    applied = await auth_client.post(
        f"/api/v1/custom-cbls/{custom.json()['id']}/reading-plans/{plan.json()['id']}:apply",
        json={"lane_id": "main"},
    )
    assert applied.status_code == 200, applied.text
    body = applied.json()
    assert body["added_issue_ids"] == [new_issue.id]
    assert body["skipped_existing_issue_ids"] == [anchor.id, existing_other_lane.id]

    matching = [node for node in body["nodes"] if node["ref_id"] == existing_other_lane.id]
    assert len(matching) == 1
    assert matching[0]["lane_id"] == "side"


@pytest.mark.asyncio
async def test_custom_cbl_strict_apply_rolls_back_when_blocked_refresh_fails(
    auth_client: AsyncClient,
    async_db: AsyncSession,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A strict apply cannot persist plan changes without its blocked-state projection."""
    user = await get_or_create_user_async(async_db)
    first = await _issue(
        async_db,
        user_id=user.id,
        title="Starman",
        issue_number="55",
        queue_position=1,
    )
    second = await _issue(
        async_db,
        user_id=user.id,
        title="JSA",
        issue_number="1",
        queue_position=2,
    )
    await async_db.commit()

    custom = await auth_client.post(
        "/api/v1/custom-cbls",
        json={"name": "Atomic bridge", "issue_ids": [first.id, second.id]},
    )
    assert custom.status_code == 201, custom.text
    plan = await auth_client.post(
        "/api/v1/continuity-plans/",
        json=_plan_payload([first.id], mode="strict_sequential"),
    )
    assert plan.status_code == 201, plan.text
    plan_id = plan.json()["id"]

    persisted = await async_db.get(ContinuityPlan, plan_id)
    assert persisted is not None
    before_nodes = deepcopy(persisted.nodes_json)

    monkeypatch.setattr(
        custom_cbl_service,
        "refresh_user_blocked_status",
        AsyncMock(side_effect=RuntimeError("projection failed")),
    )

    with pytest.raises(RuntimeError, match="projection failed"):
        await custom_cbl_service.apply_custom_cbl_for_user(
            async_db,
            user_id=user.id,
            list_id=custom.json()["id"],
            plan_id=plan_id,
            lane_id=None,
        )

    restored = await async_db.get(ContinuityPlan, plan_id)
    assert restored is not None
    await async_db.refresh(restored)
    assert restored.nodes_json == before_nodes
