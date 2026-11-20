"""Coverage for projecting a continuity plan into an existing reading order."""

from __future__ import annotations

from collections.abc import AsyncIterator
from datetime import UTC, datetime

import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth import create_access_token
from app.csrf import CSRF_COOKIE_NAME, CSRF_HEADER_NAME, generate_csrf_token
from app.database import get_db
from app.main import app
from app.models import Thread
from app.models.continuity_plan import ContinuityPlan
from app.models.reading_order import ReadingOrder, ReadingOrderItem
from app.models.user import User
from app.schemas.continuity_plan import (
    ContinuityPlanLane,
    ContinuityPlanNode,
    ContinuityPlanWrite,
)


@pytest_asyncio.fixture
async def projection_client(async_db: AsyncSession) -> AsyncIterator[AsyncClient]:
    """Authenticated HTTP client that uses the provided async_db session."""
    from tests.conftest import get_or_create_user_async

    user = await get_or_create_user_async(async_db)

    async def _override_db() -> AsyncIterator[AsyncSession]:
        yield async_db

    app.dependency_overrides[get_db] = _override_db
    transport = ASGITransport(app=app, raise_app_exceptions=False)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        csrf_token = generate_csrf_token()
        ac.cookies.set(CSRF_COOKIE_NAME, csrf_token)
        ac.headers.update({CSRF_HEADER_NAME: csrf_token})
        token = create_access_token(data={"sub": user.username, "jti": "test"})
        ac.headers.update({"Authorization": f"Bearer {token}"})
        yield ac
    app.dependency_overrides.clear()


async def _make_thread(async_db: AsyncSession, *, user_id: int, title: str) -> Thread:
    """Create and persist a minimal owned thread."""
    thread = Thread(
        title=title,
        format="comic",
        issues_remaining=1,
        queue_position=1,
        status="active",
        user_id=user_id,
        total_issues=1,
        reading_progress="unstarted",
        created_at=datetime.now(UTC),
    )
    async_db.add(thread)
    await async_db.flush()
    return thread


def _build_plan_payload(
    *,
    mode: str,
    lanes: list[dict[str, object]],
    nodes: list[dict[str, object]],
) -> ContinuityPlanWrite:
    """Construct a validated ContinuityPlanWrite instance for tests."""
    return ContinuityPlanWrite(
        name="Projected reading order",
        ordering_mode=mode,
        lanes=[ContinuityPlanLane(**lane) for lane in lanes],
        nodes=[ContinuityPlanNode(**node) for node in nodes],
    )


async def _make_reading_order(
    async_db: AsyncSession, *, user_id: int, name: str = "Reading order"
) -> ReadingOrder:
    """Create and persist a minimal owned reading order."""
    order = ReadingOrder(name=name, description="plan projection test", user_id=user_id)
    async_db.add(order)
    await async_db.flush()
    return order


async def _make_plan(
    async_db: AsyncSession, *, user_id: int, payload: ContinuityPlanWrite
) -> ContinuityPlan:
    """Create and persist a continuity plan from a validated payload."""
    plan = ContinuityPlan(
        user_id=user_id,
        name=payload.name,
        ordering_mode=payload.ordering_mode,
        lanes_json=[lane.model_dump() for lane in payload.lanes],
        nodes_json=[node.model_dump() for node in payload.nodes],
    )
    async_db.add(plan)
    await async_db.flush()
    return plan


async def test_sequential_plan_preview_is_deterministic_and_incremental(
    projection_client: AsyncClient, async_db: AsyncSession
) -> None:
    """A sequential plan yields deterministic, ordered entries per lane."""
    user = (await async_db.execute(select(User).limit(1))).scalar_one()
    threads = [
        await _make_thread(async_db, user_id=user.id, title=f"Thread {index}") for index in range(3)
    ]
    await async_db.commit()
    payload = _build_plan_payload(
        mode="informational",
        lanes=[{"id": "main", "name": "Main", "order": 0}],
        nodes=[
            {
                "id": f"node-{thread.id}",
                "node_type": "thread",
                "ref_id": thread.id,
                "lane_id": "main",
                "position": index,
                "convergence_gate": [],
            }
            for index, thread in enumerate(threads)
        ],
    )
    plan = await _make_plan(async_db, user_id=user.id, payload=payload)
    order = await _make_reading_order(async_db, user_id=user.id)
    await async_db.commit()

    response = await projection_client.post(
        f"/api/v1/continuity-plans/{plan.id}/reading-orders/project-preview",
        json={"reading_order_id": order.id},
    )
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["plan_id"] == plan.id
    assert body["reading_order_id"] == order.id
    assert body["conflicts"] == []
    assert [entry["position"] for entry in body["entries"]] == [1, 2, 3]
    assert all(entry["source"] == "added" for entry in body["entries"])
    assert [entry["thread_id"] for entry in body["entries"]] == [thread.id for thread in threads]

    repeat = await projection_client.post(
        f"/api/v1/continuity-plans/{plan.id}/reading-orders/project-preview",
        json={"reading_order_id": order.id},
    )
    assert repeat.status_code == 200
    assert repeat.json()["entries"] == body["entries"]


async def test_parallel_plan_uses_documented_flattening_policy(
    projection_client: AsyncClient, async_db: AsyncSession
) -> None:
    """Parallel lanes are flattened lane-order then position, deterministically."""
    user = (await async_db.execute(select(User).limit(1))).scalar_one()
    threads_by_lane: dict[str, list[Thread]] = {}
    for lane_label in ("alpha", "bravo", "charlie"):
        threads_by_lane[lane_label] = [
            await _make_thread(async_db, user_id=user.id, title=f"{lane_label}-{index}")
            for index in range(2)
        ]
    await async_db.commit()

    payload = _build_plan_payload(
        mode="informational",
        lanes=[
            {"id": "alpha", "name": "Alpha", "order": 0},
            {"id": "bravo", "name": "Bravo", "order": 1},
            {"id": "charlie", "name": "Charlie", "order": 2},
        ],
        nodes=[
            {
                "id": f"{lane}-{thread.id}",
                "node_type": "thread",
                "ref_id": thread.id,
                "lane_id": lane,
                "position": position,
                "convergence_gate": [],
            }
            for lane, threads in threads_by_lane.items()
            for position, thread in enumerate(threads)
        ],
    )
    plan = await _make_plan(async_db, user_id=user.id, payload=payload)
    order = await _make_reading_order(async_db, user_id=user.id)
    await async_db.commit()

    response = await projection_client.post(
        f"/api/v1/continuity-plans/{plan.id}/reading-orders/project-preview",
        json={"reading_order_id": order.id},
    )
    assert response.status_code == 200, response.text
    entries = response.json()["entries"]
    flat_lanes = [
        thread.title.rsplit("-", 1)[0]
        for thread in [
            threads_by_lane["alpha"][0],
            threads_by_lane["alpha"][1],
            threads_by_lane["bravo"][0],
            threads_by_lane["bravo"][1],
            threads_by_lane["charlie"][0],
            threads_by_lane["charlie"][1],
        ]
    ]
    assert [entry["thread_title"].rsplit("-", 1)[0] for entry in entries] == flat_lanes
    assert [entry["position"] for entry in entries] == [1, 2, 3, 4, 5, 6]


async def test_duplicate_thread_conflict_is_reported_before_mutation(
    projection_client: AsyncClient, async_db: AsyncSession
) -> None:
    """Duplicate thread references in the plan surface as conflicts without mutating."""
    user = (await async_db.execute(select(User).limit(1))).scalar_one()
    thread = await _make_thread(async_db, user_id=user.id, title="Repeat")
    await async_db.commit()
    payload = _build_plan_payload(
        mode="informational",
        lanes=[
            {"id": "alpha", "name": "Alpha", "order": 0},
            {"id": "bravo", "name": "Bravo", "order": 1},
        ],
        nodes=[
            {
                "id": "node-a",
                "node_type": "thread",
                "ref_id": thread.id,
                "lane_id": "alpha",
                "position": 0,
                "convergence_gate": [],
            },
            {
                "id": "node-b",
                "node_type": "thread",
                "ref_id": thread.id,
                "lane_id": "bravo",
                "position": 0,
                "convergence_gate": [],
            },
        ],
    )
    plan = await _make_plan(async_db, user_id=user.id, payload=payload)
    order = await _make_reading_order(async_db, user_id=user.id)
    await async_db.commit()

    preview = await projection_client.post(
        f"/api/v1/continuity-plans/{plan.id}/reading-orders/project-preview",
        json={"reading_order_id": order.id},
    )
    assert preview.status_code == 200
    preview_body = preview.json()
    assert preview_body["entries"] == []
    assert preview_body["conflicts"]
    assert preview_body["conflicts"][0]["code"] == "duplicate_thread"
    assert preview_body["conflicts"][0]["thread_id"] == thread.id

    items = (
        (
            await async_db.execute(
                select(ReadingOrderItem).where(ReadingOrderItem.reading_order_id == order.id)
            )
        )
        .scalars()
        .all()
    )
    assert items == []


async def test_non_thread_node_is_reported_before_mutation(
    projection_client: AsyncClient, async_db: AsyncSession
) -> None:
    """Issue or crossover nodes cannot be projected into a reading order."""
    user = (await async_db.execute(select(User).limit(1))).scalar_one()
    thread = await _make_thread(async_db, user_id=user.id, title="Mixed")
    await async_db.commit()
    payload = _build_plan_payload(
        mode="informational",
        lanes=[{"id": "main", "name": "Main", "order": 0}],
        nodes=[
            {
                "id": "thread-node",
                "node_type": "thread",
                "ref_id": thread.id,
                "lane_id": "main",
                "position": 0,
                "convergence_gate": [],
            },
            {
                "id": "issue-node",
                "node_type": "issue",
                "ref_id": thread.id,
                "lane_id": "main",
                "position": 1,
                "convergence_gate": [],
            },
        ],
    )
    plan = await _make_plan(async_db, user_id=user.id, payload=payload)
    order = await _make_reading_order(async_db, user_id=user.id)
    await async_db.commit()

    preview = await projection_client.post(
        f"/api/v1/continuity-plans/{plan.id}/reading-orders/project-preview",
        json={"reading_order_id": order.id},
    )
    assert preview.status_code == 200
    body = preview.json()
    assert any(conflict["code"] == "non_thread_node" for conflict in body["conflicts"])

    items = (
        (
            await async_db.execute(
                select(ReadingOrderItem).where(ReadingOrderItem.reading_order_id == order.id)
            )
        )
        .scalars()
        .all()
    )
    assert items == []


async def test_unowned_plan_is_not_found(
    projection_client: AsyncClient, async_db: AsyncSession
) -> None:
    """A plan belonging to another user is rejected without leaking existence."""
    user = (await async_db.execute(select(User).limit(1))).scalar_one()
    order = await _make_reading_order(async_db, user_id=user.id)
    await async_db.commit()

    response = await projection_client.post(
        "/api/v1/continuity-plans/999999/reading-orders/project-preview",
        json={"reading_order_id": order.id},
    )
    assert response.status_code == 404


async def test_projection_with_unowned_reading_order_is_not_found(
    projection_client: AsyncClient, async_db: AsyncSession
) -> None:
    """A reading order belonging to another user is rejected without leaking existence."""
    from tests.conftest import get_or_create_user_async

    user = (await async_db.execute(select(User).limit(1))).scalar_one()
    other = await get_or_create_user_async(async_db, username=f"other_{user.id}")
    thread = await _make_thread(async_db, user_id=user.id, title="Mine")
    await async_db.commit()
    payload = _build_plan_payload(
        mode="informational",
        lanes=[{"id": "main", "name": "Main", "order": 0}],
        nodes=[
            {
                "id": f"node-{thread.id}",
                "node_type": "thread",
                "ref_id": thread.id,
                "lane_id": "main",
                "position": 0,
                "convergence_gate": [],
            }
        ],
    )
    plan = await _make_plan(async_db, user_id=user.id, payload=payload)
    order = ReadingOrder(name="Foreign", user_id=other.id)
    async_db.add(order)
    await async_db.commit()

    response = await projection_client.post(
        f"/api/v1/continuity-plans/{plan.id}/reading-orders/project-preview",
        json={"reading_order_id": order.id},
    )
    assert response.status_code == 404


async def test_malformed_plan_nodes_are_rejected_as_conflict(
    projection_client: AsyncClient, async_db: AsyncSession
) -> None:
    """Invalid persisted plan nodes surface a malformed_plan conflict, not a crash."""
    user = (await async_db.execute(select(User).limit(1))).scalar_one()
    thread = await _make_thread(async_db, user_id=user.id, title="Valid")
    await async_db.commit()
    payload = _build_plan_payload(
        mode="informational",
        lanes=[{"id": "main", "name": "Main", "order": 0}],
        nodes=[
            {
                "id": f"node-{thread.id}",
                "node_type": "thread",
                "ref_id": thread.id,
                "lane_id": "main",
                "position": 0,
                "convergence_gate": [],
            }
        ],
    )
    plan = await _make_plan(async_db, user_id=user.id, payload=payload)
    plan.nodes_json = [{"id": "broken", "node_type": "issue"}]  # missing ref_id/lane/position
    order = await _make_reading_order(async_db, user_id=user.id)
    await async_db.commit()

    response = await projection_client.post(
        f"/api/v1/continuity-plans/{plan.id}/reading-orders/project-preview",
        json={"reading_order_id": order.id},
    )
    assert response.status_code == 409
    assert response.json()["detail"]["code"] == "malformed_plan"


async def test_missing_thread_conflict_is_reported(
    projection_client: AsyncClient, async_db: AsyncSession
) -> None:
    """A plan node referencing an unowned thread blocks projection with a conflict."""
    user = (await async_db.execute(select(User).limit(1))).scalar_one()
    from tests.conftest import get_or_create_user_async

    other = await get_or_create_user_async(async_db, username=f"foreign_{user.id}")
    foreign_thread = await _make_thread(async_db, user_id=other.id, title="Not mine")
    await async_db.commit()
    payload = _build_plan_payload(
        mode="informational",
        lanes=[{"id": "main", "name": "Main", "order": 0}],
        nodes=[
            {
                "id": f"node-{foreign_thread.id}",
                "node_type": "thread",
                "ref_id": foreign_thread.id,
                "lane_id": "main",
                "position": 0,
                "convergence_gate": [],
            }
        ],
    )
    plan = await _make_plan(async_db, user_id=user.id, payload=payload)
    order = await _make_reading_order(async_db, user_id=user.id)
    await async_db.commit()

    preview = await projection_client.post(
        f"/api/v1/continuity-plans/{plan.id}/reading-orders/project-preview",
        json={"reading_order_id": order.id},
    )
    assert preview.status_code == 200
    body = preview.json()
    assert any(conflict["code"] == "missing_thread" for conflict in body["conflicts"])


async def test_existing_entries_are_marked_existing_in_preview(
    projection_client: AsyncClient, async_db: AsyncSession
) -> None:
    """Threads already at their projected position are reported as existing."""
    user = (await async_db.execute(select(User).limit(1))).scalar_one()
    thread = await _make_thread(async_db, user_id=user.id, title="Stays put")
    await async_db.commit()
    payload = _build_plan_payload(
        mode="informational",
        lanes=[{"id": "main", "name": "Main", "order": 0}],
        nodes=[
            {
                "id": f"node-{thread.id}",
                "node_type": "thread",
                "ref_id": thread.id,
                "lane_id": "main",
                "position": 0,
                "convergence_gate": [],
            }
        ],
    )
    plan = await _make_plan(async_db, user_id=user.id, payload=payload)
    order = await _make_reading_order(async_db, user_id=user.id)
    async_db.add(
        ReadingOrderItem(
            reading_order_id=order.id, thread_id=thread.id, position=1, issue_number=None
        )
    )
    await async_db.commit()

    preview = await projection_client.post(
        f"/api/v1/continuity-plans/{plan.id}/reading-orders/project-preview",
        json={"reading_order_id": order.id},
    )
    assert preview.status_code == 200
    body = preview.json()
    assert body["entries"][0]["source"] == "existing"


async def test_strict_empty_plan_previews_as_empty(
    projection_client: AsyncClient, async_db: AsyncSession
) -> None:
    """A Strict plan with 0 lanes and 0 steps is a valid empty plan (#5614).

    It persists through ``ContinuityPlanWrite`` and its projection is an empty
    sequence rather than a malformed-plan conflict.
    """
    user = (await async_db.execute(select(User).limit(1))).scalar_one()
    payload = _build_plan_payload(mode="strict_sequential", lanes=[], nodes=[])
    plan = await _make_plan(async_db, user_id=user.id, payload=payload)
    order = await _make_reading_order(async_db, user_id=user.id)
    await async_db.commit()

    preview = await projection_client.post(
        f"/api/v1/continuity-plans/{plan.id}/reading-orders/project-preview",
        json={"reading_order_id": order.id},
    )
    assert preview.status_code == 200, preview.text
    body = preview.json()
    assert body["plan_id"] == plan.id
    assert body["plan_ordering_mode"] == "strict_sequential"
    assert body["entries"] == []
    assert body["conflicts"] == []
    assert body["total_positions"] == 0
    assert body["dropped_node_ids"] == []


