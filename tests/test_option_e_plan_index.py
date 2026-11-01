"""Contract tests: Option E Plan index must follow owned List authority, never stale Plan metadata."""

from collections.abc import Iterator
from datetime import UTC, datetime, timedelta

import pytest
from fastapi import HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import get_reading_execution_settings
from app.models.continuity_plan import ContinuityPlan
from app.models.custom_cbl import CustomCBLEntry, CustomCBLList
from app.models.issue import Issue
from app.models.reading_plan_membership import ReadingPlanSource
from app.models.thread import Thread
from app.models.user import User
from app.services.continuity_plan_writer import list_continuity_plan_items


@pytest.fixture
def option_e(monkeypatch: pytest.MonkeyPatch) -> Iterator[None]:
    """Switch to the same Option E policy as the production reader."""
    monkeypatch.setenv("OPTION_E_ENABLED", "true")
    monkeypatch.setenv("OPTION_E_APPROVED_PREVIEW", "isolated-test-fixture")
    get_reading_execution_settings.cache_clear()
    yield
    get_reading_execution_settings.cache_clear()


@pytest.mark.asyncio
async def test_index_uses_list_mode_membership_and_latest_list_timestamp(
    async_db: AsyncSession, default_user: User, option_e: None,
) -> None:
    """A stale strict one-issue Plan must render its three-issue loose List."""
    owner = default_user.id
    earlier = datetime(2026, 10, 20, tzinfo=UTC)
    later = earlier + timedelta(days=7)
    plan = ContinuityPlan(
        user_id=owner,
        name="Ultimate Universe",
        ordering_mode="strict_sequential",
        lanes_json=[
            {"id": "legacy-a", "name": "Legacy A", "order": 0},
            {"id": "legacy-b", "name": "Legacy B", "order": 1},
        ],
        nodes_json=[{"id": "old", "node_type": "issue", "ref_id": 9999,
                     "lane_id": "legacy-a", "position": 0}],
        created_at=earlier,
        updated_at=earlier,
    )
    reading_list = CustomCBLList(
        user_id=owner, name="Ultimate Universe", mode="loose",
        created_at=earlier, updated_at=later,
    )
    thread = Thread(
        user_id=owner, title="Ultimate Test", format="comic",
        issues_remaining=3, total_issues=3, queue_position=1,
        status="active", reading_progress="unstarted", created_at=earlier,
    )
    async_db.add_all([plan, reading_list, thread])
    await async_db.flush()
    issues = [
        Issue(thread_id=thread.id, issue_number=str(n), position=n, status="unread")
        for n in range(1, 4)
    ]
    async_db.add_all(issues)
    await async_db.flush()
    async_db.add(
        ReadingPlanSource(
            plan_id=plan.id,
            raw_source_path=f"custom-cbl:{reading_list.id}",
            custom_cbl_list_id=reading_list.id,
        )
    )
    async_db.add_all([
        CustomCBLEntry(list_id=reading_list.id, issue_id=issue.id, position=i)
        for i, issue in enumerate(issues)
    ])
    await async_db.flush()

    # The second Plan has newer *legacy* Plan metadata, but the first
    # Plan's List was edited more recently. The index must sort by the
    # authoritative List timestamp, rather than the legacy Plan timestamp.
    middle = earlier + timedelta(days=5)
    newer_plan = later + timedelta(days=2)
    other_plan = ContinuityPlan(
        user_id=owner,
        name="Older list, newer Plan",
        ordering_mode="strict_sequential",
        lanes_json=[{"id": "main", "name": "Main", "order": 0}],
        nodes_json=[],
        created_at=earlier,
        updated_at=newer_plan,
    )
    other_list = CustomCBLList(
        user_id=owner, name="Older list, newer Plan", mode="strict",
        created_at=earlier, updated_at=middle,
    )
    async_db.add_all([other_plan, other_list])
    await async_db.flush()
    async_db.add(ReadingPlanSource(
        plan_id=other_plan.id,
        raw_source_path=f"custom-cbl:{other_list.id}",
        custom_cbl_list_id=other_list.id,
    ))
    await async_db.flush()

    items = await list_continuity_plan_items(async_db, user_id=owner)
    filtered_ids = [value.id for value in items if value.id in {plan.id, other_plan.id}]
    assert filtered_ids == [plan.id, other_plan.id]
    item = next(value for value in items if value.id == plan.id)
    assert item.ordering_mode == "informational"
    assert item.step_count == 3
    assert item.lane_count == 1
    assert item.updated_at == later
    assert item.source_names[f"custom-cbl:{reading_list.id}"] == "Ultimate Universe"


@pytest.mark.asyncio
async def test_option_e_index_allows_orphaned_plan_after_list_deletion(
    async_db: AsyncSession, default_user: User, option_e: None,
) -> None:
    """An orphaned plan (linked list deleted) must be listed without authority."""
    now = datetime.now(UTC)
    plan = ContinuityPlan(
        user_id=default_user.id, name="Orphaned Plan",
        ordering_mode="strict_sequential",
        lanes_json=[{"id": "main", "name": "Main", "order": 0}],
        nodes_json=[],
        created_at=now, updated_at=now,
    )
    async_db.add(plan)
    await async_db.flush()
    # No ReadingPlanSource row - the plan is orphaned after its linked list was deleted.
    items = await list_continuity_plan_items(async_db, user_id=default_user.id)
    assert len(items) == 1
    assert items[0].id == plan.id
    assert items[0].name == "Orphaned Plan"
    assert items[0].ordering_mode == "strict_sequential"
    assert items[0].lane_count == 1
    assert items[0].step_count == 0
    # Orphaned plans have empty source_paths since there's no authoritative list
    assert items[0].source_paths == []


@pytest.mark.asyncio
async def test_option_e_index_rejects_ambiguous_plan_authority(
    async_db: AsyncSession, default_user: User, option_e: None,
) -> None:
    """Multiple distinct owned Lists linked to the same Plan must fail clearly."""
    owner = default_user.id
    now = datetime.now(UTC)
    plan = ContinuityPlan(
        user_id=owner, name="Ambiguous Plan",
        ordering_mode="strict_sequential",
        lanes_json=[{"id": "main", "name": "Main", "order": 0}],
        nodes_json=[], created_at=now, updated_at=now,
    )
    async_db.add(plan)
    await async_db.flush()
    list_a = CustomCBLList(user_id=owner, name="List A", mode="loose", created_at=now, updated_at=now)
    list_b = CustomCBLList(user_id=owner, name="List B", mode="strict", created_at=now, updated_at=now)
    async_db.add_all([list_a, list_b])
    await async_db.flush()
    async_db.add_all([
        ReadingPlanSource(plan_id=plan.id, raw_source_path=f"custom-cbl:{list_a.id}", custom_cbl_list_id=list_a.id),
        ReadingPlanSource(plan_id=plan.id, raw_source_path=f"custom-cbl:{list_b.id}", custom_cbl_list_id=list_b.id),
    ])
    await async_db.flush()
    with pytest.raises(HTTPException) as exc:
        await list_continuity_plan_items(async_db, user_id=owner)
    assert exc.value.status_code == 409


@pytest.mark.asyncio
async def test_option_e_index_never_accepts_foreign_list_authority(
    async_db: AsyncSession, default_user: User, option_e: None,
) -> None:
    """A cross-owner List link must not authorize or disclose the foreign List."""
    foreign_owner = User(username="option-e-foreign-authority-owner")
    async_db.add(foreign_owner)
    await async_db.flush()
    now = datetime.now(UTC)
    plan = ContinuityPlan(
        user_id=default_user.id,
        name="Owner's Plan",
        ordering_mode="strict_sequential",
        lanes_json=[{"id": "main", "name": "Main", "order": 0}],
        nodes_json=[],
        created_at=now,
        updated_at=now,
    )
    foreign_list = CustomCBLList(
        user_id=foreign_owner.id,
        name="Private foreign reading order",
        mode="strict",
        created_at=now,
        updated_at=now,
    )
    async_db.add_all([plan, foreign_list])
    await async_db.flush()
    async_db.add(
        ReadingPlanSource(
            plan_id=plan.id,
            raw_source_path=f"custom-cbl:{foreign_list.id}",
            custom_cbl_list_id=foreign_list.id,
        )
    )
    await async_db.flush()

    with pytest.raises(HTTPException) as exc:
        await list_continuity_plan_items(async_db, user_id=default_user.id)
    assert exc.value.status_code == 409
    assert "Private foreign reading order" not in str(exc.value.detail)


@pytest.mark.asyncio
async def test_option_e_index_rejects_multiple_authoritative_lists_for_same_plan(
    async_db: AsyncSession, default_user: User, option_e: None,
) -> None:
    """Multiple distinct owned Lists linked to the same Plan must fail clearly."""
    owner = default_user.id
    now = datetime.now(UTC)
    plan = ContinuityPlan(
        user_id=owner, name="Ambiguous Plan",
        ordering_mode="strict_sequential",
        lanes_json=[{"id": "main", "name": "Main", "order": 0}],
        nodes_json=[], created_at=now, updated_at=now,
    )
    async_db.add(plan)
    await async_db.flush()
    list_a = CustomCBLList(user_id=owner, name="List A", mode="loose", created_at=now, updated_at=now)
    list_b = CustomCBLList(user_id=owner, name="List B", mode="strict", created_at=now, updated_at=now)
    async_db.add_all([list_a, list_b])
    await async_db.flush()
    async_db.add_all([
        ReadingPlanSource(plan_id=plan.id, raw_source_path=f"custom-cbl:{list_a.id}", custom_cbl_list_id=list_a.id),
        ReadingPlanSource(plan_id=plan.id, raw_source_path=f"custom-cbl:{list_b.id}", custom_cbl_list_id=list_b.id),
    ])
    await async_db.flush()
    with pytest.raises(HTTPException) as exc:
        await list_continuity_plan_items(async_db, user_id=owner)
    assert exc.value.status_code == 409
