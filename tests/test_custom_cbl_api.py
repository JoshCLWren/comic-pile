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
from app.models.dependency import Dependency
from app.models.issue import Issue
from app.models.thread import Thread
from app.models.user import User
from app.services import custom_cbl as custom_cbl_service
from tests.conftest import get_or_create_user_async


@pytest.mark.asyncio
async def test_custom_cbl_explicit_targets_survive_reorder_apply_and_resave(
    auth_client: AsyncClient,
    async_db: AsyncSession,
) -> None:
    """One source gates both intended targets after reorder and unchanged save."""
    user = await get_or_create_user_async(async_db)
    issues = [
        await _issue(async_db, user_id=user.id, title=title, issue_number="1", queue_position=index)
        for index, title in enumerate(["Source", "Unrelated", "Target A", "Target B"], 1)
    ]
    ids = [issue.id for issue in issues]
    await async_db.commit()
    created = await auth_client.post(
        "/api/v1/custom-cbls",
        json={
            "name": "Explicit fan-out",
            "issue_ids": ids,
            "checkpoint_targets": {str(ids[0]): ids[2:]},
        },
    )
    assert created.status_code == 201, created.text
    list_id = created.json()["id"]
    reordered = [ids[0], ids[3], ids[1], ids[2]]
    # Old clients omit target metadata. A membership edit must preserve it.
    updated = await auth_client.put(
        f"/api/v1/custom-cbls/{list_id}",
        json={
            "name": "Explicit fan-out",
            "issue_ids": reordered,
        },
    )
    assert updated.status_code == 200, updated.text
    assert updated.json()["entries"][0]["checkpoint_target_issue_ids"] == ids[2:]
    plan_response = await auth_client.post(
        "/api/v1/continuity-plans/", json=_plan_payload(ids, mode="strict_sequential")
    )
    assert plan_response.status_code == 201, plan_response.text
    plan_id = plan_response.json()["id"]
    applied = await auth_client.post(
        f"/api/v1/custom-cbls/{list_id}/reading-plans/{plan_id}:apply", json={}
    )
    assert applied.status_code == 200, applied.text
    pairs = set(
        (
            await async_db.execute(select(Dependency.source_issue_id, Dependency.target_issue_id))
        ).all()
    )
    assert pairs == {(ids[0], ids[2]), (ids[0], ids[3])}
    original_ids = set((await async_db.execute(select(Dependency.id))).scalars())
    got = await auth_client.get(f"/api/v1/continuity-plans/{plan_id}")
    assert got.status_code == 200, got.text
    payload = {key: got.json()[key] for key in ("name", "ordering_mode", "lanes", "nodes")}
    for node in payload["nodes"]:
        node.pop("checkpoint_target_ref_id", None)
        node.pop("checkpoint_target_ref_ids", None)
    saved = await auth_client.put(f"/api/v1/continuity-plans/{plan_id}", json=payload)
    assert saved.status_code == 200, saved.text
    reapplied = await auth_client.post(
        f"/api/v1/custom-cbls/{list_id}/reading-plans/{plan_id}:apply", json={}
    )
    assert reapplied.status_code == 200, reapplied.text
    assert set((await async_db.execute(select(Dependency.id))).scalars()) == original_ids


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
        (
            await async_db.execute(
                select(Thread).where(Thread.user_id == user.id).order_by(Thread.id)
            )
        )
        .scalars()
        .all()
    )
    assert [thread.title for thread in threads] == ["Starman", "All-Star Comics", "JSA"]


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
async def test_custom_cbl_apply_without_checkpoint_does_not_invent_item_read(
    auth_client: AsyncClient,
    async_db: AsyncSession,
) -> None:
    """Applying an ordered CBL copies membership only; Roll stays natural unless flagged."""
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
        json={"name": "Order only", "issue_ids": [first.id, second.id]},
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
    rules = (
        (await async_db.execute(select(ContinuityRule).where(ContinuityRule.user_id == user.id)))
        .scalars()
        .all()
    )
    assert rules == []


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
    """Applying a custom CBL copies flagged checkpoints onto the next lane entries."""
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
        json={
            "name": "Strict bridge",
            "issue_ids": [first.id, second.id, third.id],
            "checkpoint_issue_ids": [first.id, second.id],
        },
    )
    assert custom.status_code == 201, custom.text
    assert [entry["is_checkpoint"] for entry in custom.json()["entries"]] == [
        True,
        True,
        False,
    ]
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
    assert [
        node["is_checkpoint"]
        for node in applied.json()["nodes"]
        if node["ref_id"] in {first.id, second.id, third.id}
    ] == [
        True,
        True,
        False,
    ]

    rules = (
        (
            await async_db.execute(
                select(ContinuityRule)
                .where(ContinuityRule.user_id == user.id)
                .order_by(ContinuityRule.id)
            )
        )
        .scalars()
        .all()
    )
    assert [(rule.source_id, rule.target_id, rule.satisfaction_type) for rule in rules] == [
        (first.id, second.id, "checkpoint"),
        (second.id, third.id, "checkpoint"),
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
