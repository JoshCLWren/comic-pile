"""Production-shaped Option E parity evidence for Planetary / Authority (#4254).

The fixture mirrors the read-only production observations recorded in the
issue: Reading List #1000018 has 145 strict entries, Plan #29 retains 144
historical rows, Issue #1119158 is list-only at position 32, and the first four
shared entries have a different order. The checks are intentionally read-only:
Option E keeps the owned Reading List as the single order authority and never
rewrites historical Plan membership to make the two shapes identical.
"""

from __future__ import annotations

from datetime import UTC, datetime

import pytest
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import get_reading_execution_settings
from app.models.continuity_plan import ContinuityPlan
from app.models.custom_cbl import CustomCBLEntry, CustomCBLList
from app.models.issue import Issue
from app.models.reading_plan_membership import ReadingPlanIssue, ReadingPlanSource
from app.models.thread import Thread
from app.services.reading_eligibility_service import load_eligibility_snapshot
from scripts.report_custom_cbl_plan_reconciliation import Snapshot, reconcile
from tests.conftest import get_or_create_user_async

OWNER_ID = 1
THREAD_ID = 4001
PLAN_ID = 29
LIST_ID = 1000018
HISTORICAL_SOURCE_ID = 1000049
MISSING_LIST_ISSUE_ID = 1119158
EARLY_LIST_ORDER = [26500, 26520, 26525, 26496]
EARLY_PLAN_ORDER = [26520, 26500, 26496, 26525]
EARLY_FRONTIER_POSITION = 14


def _production_order() -> list[int]:
    """Return the 145-entry list order with the extra Issue at position 32."""
    remaining = [500000 + index for index in range(140)]
    return [
        *EARLY_LIST_ORDER,
        *remaining[:28],
        MISSING_LIST_ISSUE_ID,
        *remaining[28:],
    ]


def _production_snapshot() -> tuple[Snapshot, list[int]]:
    """Build the read-only census snapshot for the observed production shape."""
    list_order = _production_order()
    shared_order = [issue_id for issue_id in list_order if issue_id != MISSING_LIST_ISSUE_ID]
    stale_plan_order = [*EARLY_PLAN_ORDER, *shared_order[4:]]
    custom_list = CustomCBLList(
        id=LIST_ID,
        user_id=OWNER_ID,
        name="Planetary / Authority",
        mode="strict",
    )
    plan = ContinuityPlan(
        id=PLAN_ID,
        user_id=OWNER_ID,
        name="Planetary / Authority",
        ordering_mode="strict_sequential",
        nodes_json=[],
        lanes_json=[{"id": "main", "name": "Main", "order": 0}],
    )
    entries = [
        CustomCBLEntry(
            id=index + 1,
            list_id=LIST_ID,
            issue_id=issue_id,
            position=index,
            gate="none",
            skipped=False,
            is_checkpoint=False,
            checkpoint_target_issue_ids=[],
        )
        for index, issue_id in enumerate(list_order)
    ]
    memberships = [
        ReadingPlanIssue(
            plan_id=PLAN_ID,
            occurrence_id=f"plan-{index}",
            issue_id=issue_id,
            lane_id="main",
            display_position=index,
            is_checkpoint=False,
        )
        for index, issue_id in enumerate(stale_plan_order)
    ]
    sources = [
        ReadingPlanSource(
            id=HISTORICAL_SOURCE_ID,
            plan_id=PLAN_ID,
            raw_source_path="comicvine:4050-18250",
            custom_cbl_list_id=None,
        ),
        ReadingPlanSource(
            id=HISTORICAL_SOURCE_ID + 1,
            plan_id=PLAN_ID,
            raw_source_path=f"custom-cbl:{LIST_ID}",
            custom_cbl_list_id=LIST_ID,
        ),
    ]
    issues = [
        Issue(
            id=issue_id,
            thread_id=THREAD_ID,
            issue_number=str(index + 1),
            position=index + 1,
            status="read" if index < EARLY_FRONTIER_POSITION else "unread",
        )
        for index, issue_id in enumerate(list_order)
    ]
    return Snapshot(
        lists=[custom_list],
        entries=entries,
        plans=[plan],
        memberships=memberships,
        sources=sources,
        issues=issues,
    ), list_order


def test_production_census_reports_exact_4254_parity() -> None:
    """The read-only census names the exact extra Issue and early-order drift."""
    snapshot, list_order = _production_snapshot()
    result = reconcile(snapshot, OWNER_ID)
    rows = result["lists"]
    assert isinstance(rows, list) and len(rows) == 1
    row = rows[0]
    assert row["status"] == "paired"
    assert row["list_id"] == LIST_ID
    assert row["plan_id"] == PLAN_ID
    assert row["list_count"] == 145
    assert row["plan_count"] == 144
    assert row["first_unread_position"] == EARLY_FRONTIER_POSITION
    assert row["durable_list_link_ids"] == [LIST_ID]
    assert [item["issue_id"] for item in row["list_only"]] == [MISSING_LIST_ISSUE_ID]
    assert row["plan_only"] == []
    assert row["order_conflict"] is True
    assert row["shared_order_list"][:4] == EARLY_LIST_ORDER
    assert row["shared_order_plan"][:4] == EARLY_PLAN_ORDER
    # Removing the extra list Issue leaves the remaining sequence aligned.
    assert row["shared_order_list"][4:] == row["shared_order_plan"][4:]
    assert row["shared_order_list"] == [
        issue_id for issue_id in list_order if issue_id != MISSING_LIST_ISSUE_ID
    ]
    assert {item["issue_id"] for item in row["position_conflicts"]} >= set(EARLY_LIST_ORDER)
    assert "membership_difference" in row["anomalies"]
    assert "shared_issue_order_conflict" in row["anomalies"]
    # The linked List is the authority while ComicVine provenance is retained.
    linked = [
        source for source in row["sources"] if source["raw_source_path"].startswith("custom-cbl:")
    ]
    assert len(linked) == 1
    assert linked[0]["custom_cbl_list_id"] == LIST_ID
    assert linked[0]["foreign_or_missing_list_link"] is False
    historical = [
        source
        for source in row["sources"]
        if source["raw_source_path"] == "comicvine:4050-18250"
    ]
    assert len(historical) == 1
    assert historical[0]["custom_cbl_list_id"] is None
    # Reconciliation is a report: historical Plan positions are unchanged.
    assert [row.display_position for row in snapshot.memberships] == list(range(144))
    assert [row.issue_id for row in snapshot.memberships][:4] == EARLY_PLAN_ORDER


@pytest.mark.asyncio
async def test_option_e_reader_serves_list_authority_and_first_unread_frontier(
    auth_client: AsyncClient,
    async_db: AsyncSession,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A stale 144-row Plan renders the 145-entry List and its entry-15 frontier."""
    user = await get_or_create_user_async(async_db)
    list_order = _production_order()
    thread = Thread(
        user_id=user.id,
        title="Planetary / Authority",
        format="comic",
        issues_remaining=len(list_order) - EARLY_FRONTIER_POSITION,
        total_issues=len(list_order),
        queue_position=1,
        status="active",
        reading_progress="in_progress",
        created_at=datetime.now(UTC),
    )
    async_db.add(thread)
    await async_db.flush()
    issues: dict[int, Issue] = {}
    for index, issue_id in enumerate(list_order):
        issue = Issue(
            thread_id=thread.id,
            issue_number=str(index + 1),
            position=index + 1,
            status="read" if index < EARLY_FRONTIER_POSITION else "unread",
        )
        async_db.add(issue)
        issues[issue_id] = issue
    await async_db.flush()
    thread.next_unread_issue_id = issues[list_order[EARLY_FRONTIER_POSITION]].id
    reading_list = CustomCBLList(
        user_id=user.id,
        name="Planetary / Authority",
        mode="strict",
    )
    plan = ContinuityPlan(
        user_id=user.id,
        name="Planetary / Authority",
        ordering_mode="strict_sequential",
        lanes_json=[{"id": "main", "name": "Main", "order": 0}],
        nodes_json=[],
    )
    async_db.add_all([reading_list, plan])
    await async_db.flush()
    async_db.add_all([
        CustomCBLEntry(
            list_id=reading_list.id,
            issue_id=issues[issue_id].id,
            position=index,
        )
        for index, issue_id in enumerate(list_order)
    ])
    shared_order = [issue_id for issue_id in list_order if issue_id != MISSING_LIST_ISSUE_ID]
    stale_plan_order = [*EARLY_PLAN_ORDER, *shared_order[4:]]
    async_db.add_all([
        ReadingPlanIssue(
            plan_id=plan.id,
            occurrence_id=f"plan-{index}",
            issue_id=issues[issue_id].id,
            lane_id="main",
            display_position=index,
        )
        for index, issue_id in enumerate(stale_plan_order)
    ])
    async_db.add_all([
        ReadingPlanSource(
            plan_id=plan.id,
            raw_source_path="comicvine:4050-18250",
            custom_cbl_list_id=None,
        ),
        ReadingPlanSource(
            plan_id=plan.id,
            raw_source_path=f"custom-cbl:{reading_list.id}",
            custom_cbl_list_id=reading_list.id,
        ),
    ])
    await async_db.commit()
    monkeypatch.setenv("OPTION_E_ENABLED", "true")
    monkeypatch.setenv(
        "OPTION_E_APPROVED_PREVIEW", "local-test-fixture-no-production-approval"
    )
    get_reading_execution_settings.cache_clear()
    try:
        response = await auth_client.get(f"/api/v1/continuity-plans/{plan.id}/reader")
        assert response.status_code == 200, response.text
        body = response.json()
        assert body["execution_mode"] == "option_e"
        assert body["ordering_mode"] == "strict_sequential"
        reader_issues = body["lanes"][0]["issues"]
        assert [row["issue_id"] for row in reader_issues] == [
            issues[issue_id].id for issue_id in list_order
        ]
        assert reader_issues[32]["issue_id"] == issues[MISSING_LIST_ISSUE_ID].id
        assert body["progress"] == {"total_issues": 145, "read_issues": 14}
        assert [row["issue_id"] for row in body["available_now"]] == [
            issues[list_order[EARLY_FRONTIER_POSITION]].id
        ]
        assert reader_issues[EARLY_FRONTIER_POSITION]["availability"] == "available"
        assert reader_issues[EARLY_FRONTIER_POSITION + 1]["availability"] == "later"
        # The Plan edit route resolves this owned source to the List editor.
        linked_source = next(
            source
            for source in body["sources"]
            if source["raw_source_path"].startswith("custom-cbl:")
        )
        assert linked_source["raw_source_path"] == f"custom-cbl:{reading_list.id}"
        assert linked_source["display_name"] == "Planetary / Authority"
        assert any(
            source["raw_source_path"] == "comicvine:4050-18250"
            for source in body["sources"]
        )
    finally:
        get_reading_execution_settings.cache_clear()


@pytest.mark.asyncio
async def test_roll_eligibility_ignores_plan_membership_and_durable_link(
    async_db: AsyncSession,
) -> None:
    """Adding the Plan -> List source must not move the Roll candidate or frontier.

    Roll/Queue eligibility is built from owner-scoped Threads, Issues, Reading
    Lists, List entries, exclusions, overlap decisions and reader prerequisites.
    It never reads continuity-plan membership or ``reading_plan_sources``. This
    loads the same production shape before Plan membership, after the stale
    144-row membership, and after the durable ``custom-cbl`` source.
    """
    user = await get_or_create_user_async(async_db)
    list_order = _production_order()
    thread = Thread(
        user_id=user.id,
        title="Planetary / Authority",
        format="comic",
        issues_remaining=len(list_order) - EARLY_FRONTIER_POSITION,
        total_issues=len(list_order),
        queue_position=1,
        status="active",
        reading_progress="in_progress",
        created_at=datetime.now(UTC),
    )
    async_db.add(thread)
    await async_db.flush()
    issues: dict[int, Issue] = {}
    for index, issue_id in enumerate(list_order):
        issue = Issue(
            thread_id=thread.id,
            issue_number=str(index + 1),
            position=index + 1,
            status="read" if index < EARLY_FRONTIER_POSITION else "unread",
        )
        async_db.add(issue)
        issues[issue_id] = issue
    await async_db.flush()
    reading_list = CustomCBLList(
        user_id=user.id,
        name="Planetary / Authority",
        mode="strict",
    )
    plan = ContinuityPlan(
        user_id=user.id,
        name="Planetary / Authority",
        ordering_mode="strict_sequential",
        lanes_json=[{"id": "main", "name": "Main", "order": 0}],
        nodes_json=[],
    )
    async_db.add_all([reading_list, plan])
    await async_db.flush()
    async_db.add_all([
        CustomCBLEntry(
            list_id=reading_list.id,
            issue_id=issues[issue_id].id,
            position=index,
        )
        for index, issue_id in enumerate(list_order)
    ])
    await async_db.flush()

    expected_frontier = issues[list_order[EARLY_FRONTIER_POSITION]].id
    states = [await load_eligibility_snapshot(async_db, user.id)]

    shared_order = [issue_id for issue_id in list_order if issue_id != MISSING_LIST_ISSUE_ID]
    stale_plan_order = [*EARLY_PLAN_ORDER, *shared_order[4:]]
    async_db.add_all([
        ReadingPlanIssue(
            plan_id=plan.id,
            occurrence_id=f"plan-{index}",
            issue_id=issues[issue_id].id,
            lane_id="main",
            display_position=index,
        )
        for index, issue_id in enumerate(stale_plan_order)
    ])
    await async_db.flush()
    states.append(await load_eligibility_snapshot(async_db, user.id))

    async_db.add_all([
        ReadingPlanSource(
            plan_id=plan.id,
            raw_source_path="comicvine:4050-18250",
            custom_cbl_list_id=None,
        ),
        ReadingPlanSource(
            plan_id=plan.id,
            raw_source_path=f"custom-cbl:{reading_list.id}",
            custom_cbl_list_id=reading_list.id,
        ),
    ])
    await async_db.flush()
    states.append(await load_eligibility_snapshot(async_db, user.id))

    for state in states:
        assert state.candidate_ids() == frozenset({thread.id})
        assert state.threads[thread.id].eligible is True
        assert state.threads[thread.id].next_issue_id == expected_frontier
        assert state.unread_counts[thread.id] == len(list_order) - EARLY_FRONTIER_POSITION
