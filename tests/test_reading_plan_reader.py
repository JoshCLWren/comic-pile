"""Reader-facing Reading Plan progress, availability, and blocker view."""

from datetime import UTC, datetime

import pytest
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import get_reading_execution_settings
from app.models.custom_cbl import CustomCBLEntry, CustomCBLList
from app.models.reading_plan_membership import ReadingPlanSource
from app.models.dependency import Dependency
from app.models.custom_cbl import CustomCBLList, CustomCBLEntry
from app.models.reading_plan_membership import ReadingPlanSource
from app.config import get_reading_execution_settings
from app.models.issue import Issue
from app.models.thread import Thread
from tests.conftest import get_or_create_user_async


async def _make_issue(
    async_db: AsyncSession,
    *,
    user_id: int,
    title: str,
    issue_number: str,
    status: str = "unread",
    position: int = 1,
) -> Issue:
    """Create one owned issue and point the thread's next unread at it when unread."""
    thread = Thread(
        title=title,
        format="comic",
        issues_remaining=0 if status == "read" else 1,
        queue_position=1,
        status="active",
        user_id=user_id,
        total_issues=1,
        reading_progress="completed" if status == "read" else "unstarted",
        created_at=datetime.now(UTC),
    )
    async_db.add(thread)
    await async_db.flush()
    issue = Issue(
        thread_id=thread.id,
        issue_number=issue_number,
        position=position,
        status=status,
    )
    async_db.add(issue)
    await async_db.flush()
    thread.next_unread_issue_id = None if status == "read" else issue.id
    await async_db.flush()
    return issue


def _node(occurrence_id: str, issue_id: int, position: int, lane_id: str = "main") -> dict[str, object]:
    """Build one issue plan node."""
    return {
        "id": occurrence_id,
        "node_type": "issue",
        "ref_id": issue_id,
        "lane_id": lane_id,
        "position": position,
    }


def _plan_payload(name: str, nodes: list[dict[str, object]]) -> dict[str, object]:
    """Build a one-lane informational plan payload."""
    lane_ids = sorted({str(node["lane_id"]) for node in nodes})
    lanes = [
        {"id": lane_id, "name": "Main" if lane_id == "main" else lane_id.title(), "order": index}
        for index, lane_id in enumerate(lane_ids)
    ]
    return {
        "name": name,
        "ordering_mode": "informational",
        "lanes": lanes,
        "nodes": nodes,
    }


async def _create_plan(
    auth_client: AsyncClient, name: str, nodes: list[dict[str, object]]
) -> int:
    """Create a plan through the public API and return its id."""
    response = await auth_client.post(
        "/api/v1/continuity-plans/", json=_plan_payload(name, nodes)
    )
    assert response.status_code == 201, response.text
    return int(response.json()["id"])


@pytest.mark.asyncio
async def test_reader_view_not_found(
    auth_client: AsyncClient,
) -> None:
    """Unknown plans 404 instead of leaking an empty reader payload."""
    response = await auth_client.get("/api/v1/continuity-plans/987654321/reader")
    assert response.status_code == 404


@pytest.mark.asyncio
async def test_available_now_is_next_unread_without_blockers(
    auth_client: AsyncClient, async_db: AsyncSession
) -> None:
    """The thread's next unread plan issue is available when no Dependency blocks it."""
    user = await get_or_create_user_async(async_db)
    read_issue = await _make_issue(
        async_db, user_id=user.id, title="Hellboy", issue_number="1", status="read"
    )
    next_issue = await _make_issue(
        async_db, user_id=user.id, title="Hellboy", issue_number="2"
    )
    await async_db.commit()
    plan_id = await _create_plan(
        auth_client,
        "Hellboy",
        [_node("h1", read_issue.id, 0), _node("h2", next_issue.id, 1)],
    )

    response = await auth_client.get(f"/api/v1/continuity-plans/{plan_id}/reader")
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["plan_id"] == plan_id
    assert body["name"] == "Hellboy"
    assert body["progress"] == {"total_issues": 2, "read_issues": 1}
    assert [row["issue_id"] for row in body["available_now"]] == [next_issue.id]
    assert body["blocked_next"] == []
    available = body["available_now"][0]
    assert available["availability"] == "available"
    assert available["thread_title"] == "Hellboy"
    assert available["issue_number"] == "2"
    assert available["blockers"] == []


@pytest.mark.asyncio
async def test_blocked_next_uses_canonical_dependency_not_cbl_order(
    auth_client: AsyncClient, async_db: AsyncSession
) -> None:
    """Unread next issues are blocked by genuine Dependency edges, not CBL-order notes."""
    user = await get_or_create_user_async(async_db)
    prelude = await _make_issue(
        async_db, user_id=user.id, title="X-Men", issue_number="95"
    )
    later = await _make_issue(
        async_db, user_id=user.id, title="Cable", issue_number="75"
    )
    decoy = await _make_issue(
        async_db, user_id=user.id, title="Wolverine", issue_number="1"
    )
    hard = Dependency(source_issue_id=prelude.id, target_issue_id=later.id)
    inert = Dependency(
        source_issue_id=decoy.id,
        target_issue_id=later.id,
        note="cbl-order:source:abc:1->2",
    )
    async_db.add_all([hard, inert])
    await async_db.commit()
    plan_id = await _create_plan(
        auth_client,
        "Age of Apocalypse",
        [
            _node("x95", prelude.id, 0),
            _node("c75", later.id, 1),
            _node("w1", decoy.id, 2),
        ],
    )

    response = await auth_client.get(f"/api/v1/continuity-plans/{plan_id}/reader")
    assert response.status_code == 200, response.text
    body = response.json()
    blocked_ids = [row["issue_id"] for row in body["blocked_next"]]
    assert later.id in blocked_ids
    later_row = next(row for row in body["blocked_next"] if row["issue_id"] == later.id)
    assert later_row["availability"] == "blocked"
    assert [blocker["issue_id"] for blocker in later_row["blockers"]] == [prelude.id]
    assert later_row["blockers"][0]["explanation"] == "Blocked by X-Men: #95"
    assert decoy.id not in [blocker["issue_id"] for blocker in later_row["blockers"]]
    available_ids = {row["issue_id"] for row in body["available_now"]}
    assert prelude.id in available_ids
    assert decoy.id in available_ids
    assert later.id not in available_ids


@pytest.mark.asyncio
async def test_reader_ignores_foreign_owned_incoming_blockers(
    auth_client: AsyncClient, async_db: AsyncSession
) -> None:
    """Foreign source threads are not blockers, matching the canonical evaluator."""
    user = await get_or_create_user_async(async_db)
    other = await get_or_create_user_async(async_db, username=f"foreign_blocker_{user.id}")
    later = await _make_issue(
        async_db, user_id=user.id, title="Cable", issue_number="75"
    )
    foreign = await _make_issue(
        async_db, user_id=other.id, title="Foreign Prelude", issue_number="1"
    )
    async_db.add(Dependency(source_issue_id=foreign.id, target_issue_id=later.id))
    await async_db.commit()
    plan_id = await _create_plan(
        auth_client,
        "Age of Apocalypse",
        [_node("c75", later.id, 0)],
    )

    response = await auth_client.get(f"/api/v1/continuity-plans/{plan_id}/reader")
    assert response.status_code == 200, response.text
    body = response.json()
    assert [row["issue_id"] for row in body["available_now"]] == [later.id]
    assert body["blocked_next"] == []
    available = body["available_now"][0]
    assert available["availability"] == "available"
    assert available["blockers"] == []


@pytest.mark.asyncio
async def test_later_unread_is_neither_available_nor_blocked_next(
    auth_client: AsyncClient, async_db: AsyncSession
) -> None:
    """Only the thread frontier is available/blocked next; later issues stay later."""
    user = await get_or_create_user_async(async_db)
    thread = Thread(
        title="B.P.R.D.",
        format="comic",
        issues_remaining=2,
        queue_position=1,
        status="active",
        user_id=user.id,
        total_issues=2,
        reading_progress="unstarted",
        created_at=datetime.now(UTC),
    )
    async_db.add(thread)
    await async_db.flush()
    first = Issue(thread_id=thread.id, issue_number="1", position=1, status="unread")
    second = Issue(thread_id=thread.id, issue_number="2", position=2, status="unread")
    async_db.add_all([first, second])
    await async_db.flush()
    thread.next_unread_issue_id = first.id
    await async_db.commit()
    plan_id = await _create_plan(
        auth_client,
        "Plague of Frogs",
        [_node("b1", first.id, 0), _node("b2", second.id, 1)],
    )

    response = await auth_client.get(f"/api/v1/continuity-plans/{plan_id}/reader")
    assert response.status_code == 200, response.text
    body = response.json()
    assert [row["issue_id"] for row in body["available_now"]] == [first.id]
    assert body["blocked_next"] == []
    second_row = next(
        row
        for lane in body["lanes"]
        for row in lane["issues"]
        if row["issue_id"] == second.id
    )
    assert second_row["availability"] == "later"


@pytest.mark.asyncio
async def test_reader_preserves_source_provenance(
    auth_client: AsyncClient, async_db: AsyncSession
) -> None:
    """CBL source snapshots remain visible as provenance, not as blockers."""
    user = await get_or_create_user_async(async_db)
    issue = await _make_issue(
        async_db, user_id=user.id, title="Hellboy", issue_number="1"
    )
    await async_db.commit()
    payload = _plan_payload(
        "Seed of Destruction",
        [
            {
                **_node("h1", issue.id, 0),
                "source_paths": ["Dark Horse/Hellboy/Seed of Destruction.cbl"],
            }
        ],
    )
    created = await auth_client.post("/api/v1/continuity-plans/", json=payload)
    assert created.status_code == 201, created.text
    plan_id = int(created.json()["id"])

    response = await auth_client.get(f"/api/v1/continuity-plans/{plan_id}/reader")
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["sources"][0]["raw_source_path"] == (
        "Dark Horse/Hellboy/Seed of Destruction.cbl"
    )
    assert body["available_now"][0]["source_paths"] == [
        "Dark Horse/Hellboy/Seed of Destruction.cbl"
    ]
    assert body["blocked_next"] == []


@pytest.mark.asyncio
async def test_option_e_plan_reader_follows_live_list_not_stale_plan_nodes(
    auth_client: AsyncClient,
    async_db: AsyncSession,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Source-linked Plan, List, and Roll use one order even when old plan data drifts."""
    user = await get_or_create_user_async(async_db)
    first = await _make_issue(async_db, user_id=user.id, title="Planetary", issue_number="1")
    second = await _make_issue(async_db, user_id=user.id, title="Authority", issue_number="1")
    legacy = await _make_issue(
        async_db, user_id=user.id, title="Removed legacy plan entry", issue_number="1",
    )
    await async_db.commit()
    plan_id = await _create_plan(
        auth_client, "Planetary / Authority",
        [_node("outdated", legacy.id, 0), _node("second", second.id, 1)],
    )
    reading_list = CustomCBLList(
        name="Planetary / Authority", user_id=user.id, mode="strict",
    )
    async_db.add(reading_list)
    await async_db.flush()
    async_db.add_all([
        CustomCBLEntry(list_id=reading_list.id, position=0, issue_id=first.id),
        CustomCBLEntry(list_id=reading_list.id, position=1, issue_id=second.id),
        ReadingPlanSource(
            plan_id=plan_id,
            raw_source_path=f"custom-cbl:{reading_list.id}",
            custom_cbl_list_id=reading_list.id,
        ),
    ])
    await async_db.commit()
    monkeypatch.setenv("OPTION_E_ENABLED", "true")
    monkeypatch.setenv(
        "OPTION_E_APPROVED_PREVIEW", "local-test-fixture-no-production-approval",
    )
    get_reading_execution_settings.cache_clear()
    try:
        plan_response = await auth_client.get(
            f"/api/v1/continuity-plans/{plan_id}/reader",
        )
        list_response = await auth_client.get(
            f"/api/v1/custom-cbls/{reading_list.id}/reader",
        )
        assert plan_response.status_code == 200, plan_response.text
        assert list_response.status_code == 200, list_response.text
        plan = plan_response.json()
        source = list_response.json()
        plan_rows = [row for lane in plan["lanes"] for row in lane["issues"]]
        assert [row["issue_id"] for row in plan_rows] == [
            row["issue_id"] for row in source["entries"]
        ] == [first.id, second.id]
        assert [row["availability"] for row in plan_rows] == [
            row["availability"] for row in source["entries"]
        ] == ["available", "blocked"]
        assert legacy.id not in [row["issue_id"] for row in plan_rows]
        assert plan["ordering_mode"] == "strict_sequential"
        assert plan["progress"] == {"total_issues": 2, "read_issues": 0}
        assert [row["issue_id"] for row in plan["available_now"]] == [first.id]
        assert [row["issue_id"] for row in plan["blocked_next"]] == [second.id]
        assert plan["blocked_next"][0]["blockers"][0]["issue_id"] == first.id
        from comic_pile.queue import get_bounded_roll_pool_rows
        roll_pool = await get_bounded_roll_pool_rows(user.id, async_db, 20)
        assert first.thread_id in [thread.id for thread, *_ in roll_pool]
        assert second.thread_id not in [thread.id for thread, *_ in roll_pool]
    finally:
        get_reading_execution_settings.cache_clear()


@pytest.mark.asyncio
async def test_option_e_plan_reader_rejects_two_persisted_list_sources(
    auth_client: AsyncClient,
    async_db: AsyncSession,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Two identically named lists cannot be selected by guessing."""
    user = await get_or_create_user_async(async_db)
    issue = await _make_issue(async_db, user_id=user.id, title="Same title", issue_number="1")
    await async_db.commit()
    plan_id = await _create_plan(auth_client, "Same title", [_node("a", issue.id, 0)])
    lists = [
        CustomCBLList(name="Same title", user_id=user.id, mode="loose")
        for _ in range(2)
    ]
    async_db.add_all(lists)
    await async_db.flush()
    async_db.add_all([
        ReadingPlanSource(
            plan_id=plan_id,
            raw_source_path=f"custom-cbl:{item.id}",
            custom_cbl_list_id=item.id,
        )
        for item in lists
    ])
    await async_db.commit()
    monkeypatch.setenv("OPTION_E_ENABLED", "true")
    monkeypatch.setenv("OPTION_E_APPROVED_PREVIEW", "local-test-fixture-no-production-approval")
    get_reading_execution_settings.cache_clear()
    try:
        response = await auth_client.get(f"/api/v1/continuity-plans/{plan_id}/reader")
        assert response.status_code == 409
    finally:
        get_reading_execution_settings.cache_clear()


@pytest.mark.asyncio
async def test_option_e_new_plan_is_linked_at_creation_and_legacy_edit_rejected(
    auth_client: AsyncClient,
    async_db: AsyncSession,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """New Plan writes cannot reopen an alternate, editable issue authority."""
    user = await get_or_create_user_async(async_db)
    issue = await _make_issue(async_db, user_id=user.id, title="New series", issue_number="1")
    await async_db.commit()
    monkeypatch.setenv("OPTION_E_ENABLED", "true")
    monkeypatch.setenv("OPTION_E_APPROVED_PREVIEW", "local-test-fixture-no-production-approval")
    get_reading_execution_settings.cache_clear()
    try:
        payload = _plan_payload("Owned Plan", [_node("owned-1", issue.id, 0)])
        created = await auth_client.post("/api/v1/continuity-plans/", json=payload)
        assert created.status_code == 201, created.text
        plan_id = created.json()["id"]
        reader = await auth_client.get(f"/api/v1/continuity-plans/{plan_id}/reader")
        assert reader.status_code == 200, reader.text
        body = reader.json()
        assert body["execution_mode"] == "option_e"
        list_sources = [
            source for source in body["sources"]
            if source["raw_source_path"].startswith("custom-cbl:")
        ]
        assert len(list_sources) == 1
        list_id = int(list_sources[0]["raw_source_path"].split(":")[1])
        linked = await auth_client.get(f"/api/v1/custom-cbls/{list_id}/reader")
        assert linked.status_code == 200
        assert [entry["issue_id"] for entry in linked.json()["entries"]] == [issue.id]
        assert [issue_row["issue_id"] for issue_row in body["lanes"][0]["issues"]] == [issue.id]
        legacy_edit = await auth_client.put(
            f"/api/v1/continuity-plans/{plan_id}", json=payload,
        )
        assert legacy_edit.status_code == 409
        assert legacy_edit.json()["detail"]["code"] == "reading_list_is_authoritative"
    finally:
        get_reading_execution_settings.cache_clear()


@pytest.mark.asyncio
async def test_option_e_reader_rejects_plan_missing_explicit_link(
    auth_client: AsyncClient,
    async_db: AsyncSession,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Do not fall back to legacy order for an unconverted active Plan."""
    user = await get_or_create_user_async(async_db)
    issue = await _make_issue(async_db, user_id=user.id, title="Old series", issue_number="1")
    await async_db.commit()
    plan_id = await _create_plan(auth_client, "Legacy Plan", [_node("old", issue.id, 0)])
    monkeypatch.setenv("OPTION_E_ENABLED", "true")
    monkeypatch.setenv("OPTION_E_APPROVED_PREVIEW", "local-test-fixture-no-production-approval")
    get_reading_execution_settings.cache_clear()
    try:
        reader = await auth_client.get(f"/api/v1/continuity-plans/{plan_id}/reader")
        assert reader.status_code == 409
        assert "no linked authoritative Reading List" in reader.json()["detail"]
    finally:
        get_reading_execution_settings.cache_clear()


@pytest.mark.asyncio
async def test_option_e_identically_named_lists_resolve_only_explicit_link(
    auth_client: AsyncClient,
    async_db: AsyncSession,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Duplicate names and identical membership never create a guessed authority."""
    user = await get_or_create_user_async(async_db)
    issue = await _make_issue(async_db, user_id=user.id, title="Same series", issue_number="1")
    await async_db.commit()
    plan_id = await _create_plan(auth_client, "Same title", [_node("x", issue.id, 0)])
    lists = [
        CustomCBLList(user_id=user.id, name="Same title", mode="strict"),
        CustomCBLList(user_id=user.id, name="Same title", mode="loose"),
    ]
    async_db.add_all(lists)
    await async_db.flush()
    for item in lists:
        async_db.add(CustomCBLEntry(
            list_id=item.id, issue_id=issue.id, position=0,
        ))
    async_db.add(ReadingPlanSource(
        plan_id=plan_id,
        raw_source_path=f"custom-cbl:{lists[1].id}",
        custom_cbl_list_id=lists[1].id,
    ))
    await async_db.commit()
    monkeypatch.setenv("OPTION_E_ENABLED", "true")
    monkeypatch.setenv("OPTION_E_APPROVED_PREVIEW", "local-test-fixture-no-production-approval")
    get_reading_execution_settings.cache_clear()
    try:
        reader = await auth_client.get(f"/api/v1/continuity-plans/{plan_id}/reader")
        assert reader.status_code == 200, reader.text
        assert reader.json()["ordering_mode"] == "informational"
        assert reader.json()["lanes"][0]["issues"][0]["source_paths"] == [
            f"custom-cbl:{lists[1].id}",
        ]
    finally:
        get_reading_execution_settings.cache_clear()


@pytest.mark.asyncio
async def test_option_e_reader_uses_owned_list_order_and_membership_not_legacy_plan(
    auth_client: AsyncClient, async_db: AsyncSession, monkeypatch: pytest.MonkeyPatch,
) -> None:
    """An edited list is the single authority even when the Plan omits an Issue."""
    user = await get_or_create_user_async(async_db)
    first = await _make_issue(
        async_db, user_id=user.id, title="Planetary", issue_number="1",
    )
    second = await _make_issue(
        async_db, user_id=user.id, title="The Authority", issue_number="1",
    )
    list_only = await _make_issue(
        async_db, user_id=user.id, title="Planetary", issue_number="2",
    )
    await async_db.commit()
    # A deliberately stale Plan has the first two Issues reversed and omits #2.
    plan_id = await _create_plan(
        auth_client, "Planetary / Authority",
        [_node("stale-authority", second.id, 0), _node("stale-planetary", first.id, 1)],
    )
    reading_list = CustomCBLList(
        user_id=user.id, name="Planetary / Authority", mode="strict",
    )
    async_db.add(reading_list)
    await async_db.flush()
    async_db.add_all([
        CustomCBLEntry(list_id=reading_list.id, issue_id=first.id, position=0),
        CustomCBLEntry(list_id=reading_list.id, issue_id=second.id, position=1),
        CustomCBLEntry(list_id=reading_list.id, issue_id=list_only.id, position=2),
        ReadingPlanSource(
            plan_id=plan_id, raw_source_path=f"custom-cbl:{reading_list.id}",
            custom_cbl_list_id=reading_list.id,
        ),
    ])
    await async_db.commit()
    monkeypatch.setenv("OPTION_E_ENABLED", "true")
    monkeypatch.setenv(
        "OPTION_E_APPROVED_PREVIEW", "local-test-fixture-no-production-approval",
    )
    get_reading_execution_settings.cache_clear()
    try:
        plan_response = await auth_client.get(
            f"/api/v1/continuity-plans/{plan_id}/reader"
        )
        list_response = await auth_client.get(
            f"/api/v1/custom-cbls/{reading_list.id}/reader"
        )
        assert plan_response.status_code == 200, plan_response.text
        assert list_response.status_code == 200, list_response.text
        plan = plan_response.json()
        canonical = list_response.json()
        plan_issues = plan["lanes"][0]["issues"]
        assert [row["issue_id"] for row in plan_issues] == [
            first.id, second.id, list_only.id,
        ]
        assert [row["issue_id"] for row in plan_issues] == [
            row["issue_id"] for row in canonical["entries"]
        ]
        assert [row["availability"] for row in plan_issues] == [
            row["availability"] for row in canonical["entries"]
        ]
        assert plan["progress"]["total_issues"] == 3
        assert plan["ordering_mode"] == "strict_sequential"
        assert plan["execution_mode"] == "option_e"
        assert plan["available_now"][0]["issue_id"] == first.id
    finally:
        get_reading_execution_settings.cache_clear()


@pytest.mark.asyncio
async def test_option_e_reader_uses_loose_list_mode_not_stale_strict_plan(
    auth_client: AsyncClient, async_db: AsyncSession, monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Legacy Plan strict mode cannot reimpose gates on a loose Reading List."""
    user = await get_or_create_user_async(async_db)
    first = await _make_issue(
        async_db, user_id=user.id, title="Absolute Batman", issue_number="1",
    )
    second = await _make_issue(
        async_db, user_id=user.id, title="Absolute Wonder Woman", issue_number="1",
    )
    await async_db.commit()
    plan_id = await _create_plan(
        auth_client, "Absolute Universe",
        [_node("a1", first.id, 0), _node("a2", second.id, 1)],
    )
    reading_list = CustomCBLList(
        user_id=user.id, name="Absolute Universe", mode="loose",
    )
    async_db.add(reading_list)
    await async_db.flush()
    async_db.add_all([
        CustomCBLEntry(list_id=reading_list.id, issue_id=first.id, position=0),
        CustomCBLEntry(list_id=reading_list.id, issue_id=second.id, position=1),
        ReadingPlanSource(
            plan_id=plan_id, raw_source_path=f"custom-cbl:{reading_list.id}",
            custom_cbl_list_id=reading_list.id,
        ),
    ])
    await async_db.commit()
    monkeypatch.setenv("OPTION_E_ENABLED", "true")
    monkeypatch.setenv(
        "OPTION_E_APPROVED_PREVIEW", "local-test-fixture-no-production-approval",
    )
    get_reading_execution_settings.cache_clear()
    try:
        response = await auth_client.get(f"/api/v1/continuity-plans/{plan_id}/reader")
        assert response.status_code == 200, response.text
        body = response.json()
        assert body["ordering_mode"] == "informational"
        assert {row["issue_id"] for row in body["available_now"]} == {
            first.id, second.id,
        }
    finally:
        get_reading_execution_settings.cache_clear()
