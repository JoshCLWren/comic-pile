"""B.P.R.D. golden-path regression coverage for canonical Reading Plans.

This fixture encodes the production reader state audited in recovery issue #2366:
Plague of Frogs and The Dead are complete, Black Flame #1 is read, the War on
Frogs interleave through #4 is read, and Black Flame #2 is the next unread item.

The test proves two product invariants:
1. A strict canonical Reading Plan makes Black Flame the only current B.P.R.D.
   Roll candidate while War on Frogs #3 remains blocked.
2. Appending the next B.P.R.D. phase with source provenance does not disturb the
   current reading position or create an earlier candidate.
"""

from __future__ import annotations

from datetime import UTC, datetime

import pytest
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.issue import Issue
from app.models.thread import Thread
from comic_pile.queue import get_roll_pool
from tests.conftest import get_or_create_user_async


async def _make_thread(
    db: AsyncSession,
    *,
    user_id: int,
    title: str,
    queue_position: int,
    active: bool,
) -> Thread:
    thread = Thread(
        title=title,
        format="comic",
        issues_remaining=0,
        queue_position=queue_position,
        status="active" if active else "completed",
        user_id=user_id,
        total_issues=0,
        reading_progress="in_progress" if active else "completed",
        created_at=datetime.now(UTC),
    )
    db.add(thread)
    await db.flush()
    return thread


async def _add_issue(
    db: AsyncSession,
    *,
    thread: Thread,
    issue_number: str,
    position: int,
    read: bool,
) -> Issue:
    issue = Issue(
        thread_id=thread.id,
        issue_number=issue_number,
        position=position,
        status="read" if read else "unread",
    )
    db.add(issue)
    await db.flush()
    thread.total_issues += 1
    if not read:
        thread.issues_remaining += 1
        if thread.next_unread_issue_id is None:
            thread.next_unread_issue_id = issue.id
    return issue


def _plan_node(issue: Issue, position: int, *, source: str | None = None) -> dict[str, object]:
    node: dict[str, object] = {
        "id": f"issue-{issue.id}",
        "node_type": "issue",
        "ref_id": issue.id,
        "lane_id": "main",
        "position": position,
    }
    if source is not None:
        node.update(
            {
                "source_role": "core",
                "source_confidence": "high",
                "source_explanation": "B.P.R.D. source reading order",
                "source_paths": [source],
                "source_cbl_placements": [
                    {"source_path": source, "position": position + 1}
                ],
            }
        )
    return node


@pytest.mark.asyncio
async def test_bprd_strict_plan_keeps_current_position_when_next_phase_is_appended(
    auth_client: AsyncClient,
    async_db: AsyncSession,
) -> None:
    user = await get_or_create_user_async(async_db)

    plague = await _make_thread(
        async_db,
        user_id=user.id,
        title="B.P.R.D.: PLAGUE OF FROGS",
        queue_position=100,
        active=False,
    )
    dead = await _make_thread(
        async_db,
        user_id=user.id,
        title="B.P.R.D.: THE DEAD",
        queue_position=101,
        active=False,
    )
    black_flame = await _make_thread(
        async_db,
        user_id=user.id,
        title="B.P.R.D.: THE BLACK FLAME",
        queue_position=5,
        active=True,
    )
    war_on_frogs = await _make_thread(
        async_db,
        user_id=user.id,
        title="B.P.R.D.: WAR ON FROGS",
        queue_position=6,
        active=True,
    )

    pf = [
        await _add_issue(async_db, thread=plague, issue_number=str(n), position=n, read=True)
        for n in range(1, 6)
    ]
    the_dead = [
        await _add_issue(async_db, thread=dead, issue_number=str(n), position=n, read=True)
        for n in range(1, 7)
    ]
    bf = [
        await _add_issue(
            async_db,
            thread=black_flame,
            issue_number=str(n),
            position=n,
            read=(n == 1),
        )
        for n in range(1, 7)
    ]
    wof1 = await _add_issue(async_db, thread=war_on_frogs, issue_number="1", position=1, read=True)
    revival = await _add_issue(
        async_db,
        thread=war_on_frogs,
        issue_number="Revival",
        position=2,
        read=True,
    )
    wof2 = await _add_issue(async_db, thread=war_on_frogs, issue_number="2", position=3, read=True)
    wof4 = await _add_issue(async_db, thread=war_on_frogs, issue_number="4", position=4, read=True)
    wof3 = await _add_issue(async_db, thread=war_on_frogs, issue_number="3", position=5, read=False)
    await async_db.commit()

    current_order = [
        *pf,
        *the_dead,
        bf[0],
        wof1,
        revival,
        wof2,
        wof4,
        *bf[1:],
        wof3,
    ]
    assert len(current_order) == 22

    create = await auth_client.post(
        "/api/v1/continuity-plans/",
        json={
            "name": "B.P.R.D.",
            "ordering_mode": "strict_sequential",
            "lanes": [{"id": "main", "name": "Reading order", "order": 0}],
            "nodes": [_plan_node(issue, index) for index, issue in enumerate(current_order)],
        },
    )
    assert create.status_code == 201, create.text
    plan_id = create.json()["id"]

    initial_pool = await get_roll_pool(user.id, async_db)
    bprd_pool = [thread for thread in initial_pool if thread.title.startswith("B.P.R.D.:")]
    assert [thread.id for thread in bprd_pool] == [black_flame.id]
    assert black_flame.next_unread_issue_id == bf[1].id
    assert war_on_frogs.next_unread_issue_id == wof3.id
    assert black_flame.is_blocked is False
    assert war_on_frogs.is_blocked is True

    universal_machine = await _make_thread(
        async_db,
        user_id=user.id,
        title="B.P.R.D.: THE UNIVERSAL MACHINE",
        queue_position=7,
        active=True,
    )
    garden_of_souls = await _make_thread(
        async_db,
        user_id=user.id,
        title="B.P.R.D.: GARDEN OF SOULS",
        queue_position=8,
        active=True,
    )
    killing_ground = await _make_thread(
        async_db,
        user_id=user.id,
        title="B.P.R.D.: KILLING GROUND",
        queue_position=9,
        active=True,
    )

    next_phase: list[Issue] = []
    for thread in (universal_machine, garden_of_souls, killing_ground):
        for n in range(1, 6):
            next_phase.append(
                await _add_issue(
                    async_db,
                    thread=thread,
                    issue_number=str(n),
                    position=n,
                    read=False,
                )
            )
    await async_db.commit()

    source_path = "B.P.R.D. Plague of Frogs Omnibus Vol. 3.cbl"
    expanded_order = [*current_order, *next_phase]
    update = await auth_client.put(
        f"/api/v1/continuity-plans/{plan_id}",
        json={
            "name": "B.P.R.D.",
            "ordering_mode": "strict_sequential",
            "lanes": [{"id": "main", "name": "Reading order", "order": 0}],
            "nodes": [
                _plan_node(issue, index, source=source_path if index >= 22 else None)
                for index, issue in enumerate(expanded_order)
            ],
        },
    )
    assert update.status_code == 200, update.text
    body = update.json()
    assert len(body["nodes"]) == 37
    assert body["nodes"][22]["source_paths"] == [source_path]
    assert body["nodes"][22]["source_cbl_placements"] == [
        {"source_path": source_path, "position": 23}
    ]

    pool_after_append = await get_roll_pool(user.id, async_db)
    bprd_pool_after_append = [
        thread for thread in pool_after_append if thread.title.startswith("B.P.R.D.:")
    ]
    assert [thread.id for thread in bprd_pool_after_append] == [black_flame.id]
    assert black_flame.next_unread_issue_id == bf[1].id
    assert war_on_frogs.is_blocked is True
    assert universal_machine.is_blocked is True
    assert garden_of_souls.is_blocked is True
    assert killing_ground.is_blocked is True
