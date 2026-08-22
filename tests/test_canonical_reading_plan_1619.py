"""Issue #1619: continuity_plans is canonical; reading_orders is legacy import/export.

Covers:
- issue-level multi-series plan survives save/reopen/execution without flattening
- legacy reading orders remain readable and adoptable without data loss
- duplicate/conflicting entries are rejected before mutation
- cross-series boundaries and within-series progression behave per #257
- informational vs strict_sequential controls blocking; queue/roll use one contract
"""

from __future__ import annotations

from datetime import UTC, datetime

import pytest
from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.continuity_plan import ContinuityPlan
from app.models.continuity_rule import ContinuityRule
from app.models.issue import Issue
from app.models.reading_order import ReadingOrder, ReadingOrderItem
from app.models.thread import Thread
from tests.conftest import get_or_create_user_async


async def _make_thread(async_db: AsyncSession, *, user_id: int, title: str) -> Thread:
    """Create an owned thread."""
    thread = Thread(
        title=title,
        format="comic",
        issues_remaining=1,
        queue_position=10,
        status="active",
        user_id=user_id,
        total_issues=1,
        reading_progress="unstarted",
        created_at=datetime.now(UTC),
    )
    async_db.add(thread)
    await async_db.flush()
    return thread


async def _make_issue_for_thread(
    async_db: AsyncSession, *, thread: Thread, issue_number: str, position: int
) -> Issue:
    issue = Issue(thread_id=thread.id, issue_number=issue_number, position=position, status="unread")
    async_db.add(issue)
    await async_db.flush()
    return issue


@pytest.mark.asyncio
async def test_issue_level_multi_series_plan_round_trips_and_is_readiness_executable(
    auth_client: AsyncClient, async_db: AsyncSession
) -> None:
    """Issue-level entries across multiple series survive save/reopen without thread flattening."""
    user = await get_or_create_user_async(async_db)
    t_a = await _make_thread(async_db, user_id=user.id, title="X-Men")
    t_b = await _make_thread(async_db, user_id=user.id, title="Avengers")
    t_c = await _make_thread(async_db, user_id=user.id, title="New Mutants")
    i_a1 = await _make_issue_for_thread(async_db, thread=t_a, issue_number="1", position=1)
    i_a2 = await _make_issue_for_thread(async_db, thread=t_a, issue_number="2", position=2)
    i_b1 = await _make_issue_for_thread(async_db, thread=t_b, issue_number="10", position=1)
    i_c1 = await _make_issue_for_thread(async_db, thread=t_c, issue_number="1", position=1)
    await async_db.commit()

    payload = {
        "name": "X of Swords",
        "ordering_mode": "informational",
        "lanes": [
            {"id": "main", "name": "Main", "order": 0},
            {"id": "parallel", "name": "Parallel", "order": 1},
        ],
        "nodes": [
            {"id": f"issue-{i_a1.id}", "node_type": "issue", "ref_id": i_a1.id, "lane_id": "main", "position": 0},
            {"id": f"issue-{i_a2.id}", "node_type": "issue", "ref_id": i_a2.id, "lane_id": "main", "position": 1},
            {"id": f"issue-{i_b1.id}", "node_type": "issue", "ref_id": i_b1.id, "lane_id": "main", "position": 2},
            {"id": f"issue-{i_c1.id}", "node_type": "issue", "ref_id": i_c1.id, "lane_id": "parallel", "position": 0},
        ],
    }
    created = await auth_client.post("/api/v1/continuity-plans/", json=payload)
    assert created.status_code == 201, created.text
    plan_id = created.json()["id"]
    # reopen via GET
    reopened = await auth_client.get(f"/api/v1/continuity-plans/{plan_id}")
    assert reopened.status_code == 200
    nodes_by_id = {n["id"]: n for n in reopened.json()["nodes"]}
    assert len(nodes_by_id) == 4
    assert all(n["node_type"] == "issue" for n in nodes_by_id.values())
    # lanes preserved, not flattened to thread positions
    assert {l["id"] for l in reopened.json()["lanes"]} == {"main", "parallel"}
    # readiness executes without flattening to thread queue_position
    readiness = await auth_client.get(f"/api/v1/continuity-plans/{plan_id}/readiness")
    assert readiness.status_code == 200, readiness.text
    body = readiness.json()
    assert body["ordering_mode"] == "informational"
    assert len(body["nodes"]) == 4
    # no diagnosis spuriously treats cross-series boundary as blocking
    assert all(node["is_readable"] for node in body["nodes"])


@pytest.mark.asyncio
async def test_legacy_reading_orders_remain_readable(auth_client: AsyncClient, async_db: AsyncSession) -> None:
    """Legacy reading_orders endpoint still serves data verbatim (backward compat)."""
    user = await get_or_create_user_async(async_db)
    t = await _make_thread(async_db, user_id=user.id, title="Legacy Thread")
    await async_db.commit()
    order = ReadingOrder(name="My Order", description="legacy", user_id=user.id)
    async_db.add(order)
    await async_db.flush()
    async_db.add(ReadingOrderItem(reading_order_id=order.id, thread_id=t.id, position=1))
    await async_db.commit()

    listed = await auth_client.get("/api/v1/reading-orders/")
    assert listed.status_code == 200, listed.text
    assert any(o["name"] == "My Order" for o in listed.json()["reading_orders"])
    thread_orders = await auth_client.get(f"/api/v1/threads/{t.id}/reading-orders")
    assert thread_orders.status_code == 200, thread_orders.text
    assert len(thread_orders.json()["reading_orders"]) == 1


@pytest.mark.asyncio
async def test_adopt_legacy_reading_order_without_data_loss(
    auth_client: AsyncClient, async_db: AsyncSession
) -> None:
    """A legacy order can be adopted into a canonical plan without losing or mutating it."""
    user = await get_or_create_user_async(async_db)
    t1 = await _make_thread(async_db, user_id=user.id, title="Adopt A")
    t2 = await _make_thread(async_db, user_id=user.id, title="Adopt B")
    await async_db.commit()
    order = ReadingOrder(name="Adopt Me", description="legacy adopt", user_id=user.id)
    async_db.add(order)
    await async_db.flush()
    async_db.add(ReadingOrderItem(reading_order_id=order.id, thread_id=t1.id, position=2))
    async_db.add(ReadingOrderItem(reading_order_id=order.id, thread_id=t2.id, position=1))
    await async_db.commit()

    adopted = await auth_client.post(
        "/api/v1/continuity-plans/from-reading-order",
        json={"reading_order_id": order.id, "plan_name": "Adopted Plan"},
    )
    assert adopted.status_code == 201, adopted.text
    plan_body = adopted.json()
    assert plan_body["name"] == "Adopted Plan"
    assert plan_body["ordering_mode"] == "informational"
    # canonical plan orders by source position, not creation order
    assert [n["ref_id"] for n in plan_body["nodes"]] == [t2.id, t1.id]
    assert all(n["node_type"] == "thread" for n in plan_body["nodes"])
    # source reading order unchanged
    items = (
        await async_db.execute(select(ReadingOrderItem).where(ReadingOrderItem.reading_order_id == order.id))
    ).scalars().all()
    assert len(items) == 2
    assert plan_body["user_id"] == user.id


@pytest.mark.asyncio
async def test_adopt_rejects_duplicate_thread_entries(
    auth_client: AsyncClient, async_db: AsyncSession
) -> None:
    """Duplicate thread ids in a legacy order are rejected before any plan is created."""
    user = await get_or_create_user_async(async_db)
    t = await _make_thread(async_db, user_id=user.id, title="Dup Thread")
    await async_db.commit()
    order = ReadingOrder(name="Dup Order", user_id=user.id)
    async_db.add(order)
    await async_db.flush()
    async_db.add(ReadingOrderItem(reading_order_id=order.id, thread_id=t.id, position=1))
    async_db.add(ReadingOrderItem(reading_order_id=order.id, thread_id=t.id, position=2))
    await async_db.commit()

    before = (await async_db.execute(select(ContinuityPlan).where(ContinuityPlan.user_id == user.id))).scalars().all()
    resp = await auth_client.post(
        "/api/v1/continuity-plans/from-reading-order", json={"reading_order_id": order.id}
    )
    assert resp.status_code == 409, resp.text
    assert resp.json()["detail"]["code"] == "duplicate_thread"
    after = (await async_db.execute(select(ContinuityPlan).where(ContinuityPlan.user_id == user.id))).scalars().all()
    assert len(after) == len(before)


@pytest.mark.asyncio
async def test_adopt_preserves_cross_series_boundaries_without_hard_edges(
    auth_client: AsyncClient, async_db: AsyncSession
) -> None:
    """Adopting a cross-series reading order remains informational (zero blocking rules)."""
    user = await get_or_create_user_async(async_db)
    threads = [await _make_thread(async_db, user_id=user.id, title=f"Series {i}") for i in range(3)]
    await async_db.commit()
    order = ReadingOrder(name="Cross-series", user_id=user.id)
    async_db.add(order)
    await async_db.flush()
    for idx, t in enumerate(threads):
        async_db.add(ReadingOrderItem(reading_order_id=order.id, thread_id=t.id, position=idx + 1))
    await async_db.commit()

    adopted = await auth_client.post(
        "/api/v1/continuity-plans/from-reading-order", json={"reading_order_id": order.id}
    )
    assert adopted.status_code == 201, adopted.text
    plan_id = adopted.json()["id"]
    rules = (await async_db.execute(select(ContinuityRule).where(ContinuityRule.user_id == user.id))).scalars().all()
    assert rules == [], "informational adoption must create zero continuity rules"
    readiness = await auth_client.get(f"/api/v1/continuity-plans/{plan_id}/readiness")
    assert readiness.status_code == 200
    assert readiness.json()["summary"]["blocked"] == 0


@pytest.mark.asyncio
async def test_informational_plan_creates_zero_blocking_rules_while_strict_creates_explicit_edges(
    auth_client: AsyncClient, async_db: AsyncSession
) -> None:
    """Queue/Roll use one canonical contract: informational = no block, strict = explicit gates."""
    user = await get_or_create_user_async(async_db)
    t_a = await _make_thread(async_db, user_id=user.id, title="Strict A")
    t_b = await _make_thread(async_db, user_id=user.id, title="Strict B")
    i1 = await _make_issue_for_thread(async_db, thread=t_a, issue_number="1", position=1)
    i2 = await _make_issue_for_thread(async_db, thread=t_b, issue_number="1", position=1)
    await async_db.commit()

    info_payload = {
        "name": "Informational",
        "ordering_mode": "informational",
        "lanes": [{"id": "main", "name": "Main", "order": 0}],
        "nodes": [
            {"id": "a", "node_type": "issue", "ref_id": i1.id, "lane_id": "main", "position": 0},
            {"id": "b", "node_type": "issue", "ref_id": i2.id, "lane_id": "main", "position": 1},
        ],
    }
    info = await auth_client.post("/api/v1/continuity-plans/", json=info_payload)
    assert info.status_code == 201, info.text
    rules_after_info = (await async_db.execute(select(ContinuityRule).where(ContinuityRule.user_id == user.id))).scalars().all()
    assert rules_after_info == []

    strict_payload = {
        "name": "Strict",
        "ordering_mode": "strict_sequential",
        "lanes": [{"id": "main", "name": "Main", "order": 0}],
        "nodes": [
            {"id": "s-a", "node_type": "issue", "ref_id": i1.id, "lane_id": "main", "position": 0},
            {"id": "s-b", "node_type": "issue", "ref_id": i2.id, "lane_id": "main", "position": 1},
        ],
    }
    strict = await auth_client.post("/api/v1/continuity-plans/", json=strict_payload)
    assert strict.status_code == 201, strict.text
    strict_id = strict.json()["id"]
    rules_after_strict = (
        await async_db.execute(select(ContinuityRule).where(ContinuityRule.user_id == user.id).order_by(ContinuityRule.id))
    ).scalars().all()
    assert len(rules_after_strict) == 1
    assert rules_after_strict[0].note == f"continuity-plan:{strict_id}"
    assert rules_after_strict[0].source_id == i1.id and rules_after_strict[0].target_id == i2.id


@pytest.mark.asyncio
async def test_within_series_progression_is_not_a_hard_edge(
    auth_client: AsyncClient, async_db: AsyncSession
) -> None:
    """Ordinary Issue.position order inside one thread never becomes blocking without explicit intent."""
    user = await get_or_create_user_async(async_db)
    t = await _make_thread(async_db, user_id=user.id, title="Within Series")
    i1 = await _make_issue_for_thread(async_db, thread=t, issue_number="1", position=1)
    i2 = await _make_issue_for_thread(async_db, thread=t, issue_number="2", position=2)
    await async_db.commit()

    payload = {
        "name": "Within Series Informational",
        "ordering_mode": "informational",
        "lanes": [{"id": "main", "name": "Main", "order": 0}],
        "nodes": [
            {"id": "i1", "node_type": "issue", "ref_id": i1.id, "lane_id": "main", "position": 0},
            {"id": "i2", "node_type": "issue", "ref_id": i2.id, "lane_id": "main", "position": 1},
        ],
    }
    resp = await auth_client.post("/api/v1/continuity-plans/", json=payload)
    assert resp.status_code == 201, resp.text
    rules = (await async_db.execute(select(ContinuityRule).where(ContinuityRule.user_id == user.id))).scalars().all()
    assert rules == []
    readiness = await auth_client.get(f"/api/v1/continuity-plans/{resp.json()['id']}/readiness")
    assert readiness.status_code == 200
    # Both issues unread but nothing hard-blocks; both are readable
    assert all(n["is_readable"] for n in readiness.json()["nodes"])


@pytest.mark.asyncio
async def test_projection_remains_export_only_and_does_not_reintroduce_peer_source(
    auth_client: AsyncClient, async_db: AsyncSession
) -> None:
    """Plan readability does not require consulting both plan and reading order."""
    user = await get_or_create_user_async(async_db)
    t = await _make_thread(async_db, user_id=user.id, title="Solo")
    i = await _make_issue_for_thread(async_db, thread=t, issue_number="1", position=1)
    await async_db.commit()

    plan_payload = {
        "name": "Export-only check",
        "ordering_mode": "informational",
        "lanes": [{"id": "main", "name": "Main", "order": 0}],
        "nodes": [{"id": "n1", "node_type": "issue", "ref_id": i.id, "lane_id": "main", "position": 0}],
    }
    plan_resp = await auth_client.post("/api/v1/continuity-plans/", json=plan_payload)
    assert plan_resp.status_code == 201, plan_resp.text
    plan_id = plan_resp.json()["id"]

    # readiness alone determines next position; reading_orders not consulted
    readiness = await auth_client.get(f"/api/v1/continuity-plans/{plan_id}/readiness")
    assert readiness.status_code == 200
    assert readiness.json()["nodes"][0]["label"]  # human label without reading_orders

    # projection exists but is not required for execution decisions
    order = ReadingOrder(name="Export target", user_id=user.id)
    async_db.add(order)
    await async_db.flush()
    await async_db.commit()
    preview = await auth_client.post(
        f"/api/v1/continuity-plans/{plan_id}/reading-orders/project-preview",
        json={"reading_order_id": order.id},
    )
    # issue nodes cannot be exported to thread-only reading orders — reported as conflict, not silent loss
    assert preview.status_code == 200
    assert any(c["code"] == "non_thread_node" for c in preview.json()["conflicts"])
