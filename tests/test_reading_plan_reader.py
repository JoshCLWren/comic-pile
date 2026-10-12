"""Reader-facing Reading Plan progress, availability, and blocker view."""

from datetime import UTC, datetime

import pytest
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.dependency import Dependency
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
