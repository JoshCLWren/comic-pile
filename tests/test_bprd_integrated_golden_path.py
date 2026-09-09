"""Integrated B.P.R.D. golden-path acceptance for recovery Step 21.

This is the production-shaped proof required by #2428/#2366.  It deliberately
uses the supported reader workflow rather than updating Reading Plan JSON as a
test shortcut:

Reading Plan -> Roll boundary -> CBL discovery -> preview -> targeted adoption
-> reload -> Roll boundary -> supported issue completion -> newly eligible item.

No production data or legacy CBL execution model is involved.
"""

from __future__ import annotations

from datetime import UTC, datetime

import pytest
from httpx import AsyncClient
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.cbl_reference import CBLSource, CBLSourceEntry, CBLSourceList
from app.models.dependency_group import DependencyGroup
from app.models.external_identity import ExternalIdentity, IssueExternalIdentityMapping
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
        read_at=datetime.now(UTC) if read else None,
    )
    db.add(issue)
    await db.flush()
    thread.total_issues = (thread.total_issues or 0) + 1
    if not read:
        thread.issues_remaining = (thread.issues_remaining or 0) + 1
        if thread.next_unread_issue_id is None:
            thread.next_unread_issue_id = issue.id
    return issue


def _plan_node(issue: Issue, position: int) -> dict[str, object]:
    return {
        "id": f"issue-{issue.id}",
        "node_type": "issue",
        "ref_id": issue.id,
        "lane_id": "main",
        "position": position,
    }


async def _seed_source(
    db: AsyncSession,
    *,
    issues: list[Issue],
    source_path: str,
) -> CBLSourceList:
    """Create a real active CBL list whose entries resolve to canonical issues."""
    source = CBLSource(
        repository="JoshCLWren/CBL-ReadingLists-step21-fixture",
        revision_sha="bprd-step21-rev",
        synced_at=datetime.now(UTC),
    )
    db.add(source)
    await db.flush()

    source_list = CBLSourceList(
        source_id=source.id,
        source_path=source_path,
        name="B.P.R.D. Plague of Frogs Omnibus Vol. 3",
        declared_issue_count=len(issues),
        content_hash="bprd-step21-content",
        revision_sha="bprd-step21-rev",
        active=True,
    )
    db.add(source_list)
    await db.flush()

    for cbl_position, issue in enumerate(issues, start=1):
        identity = ExternalIdentity(
            provider="comicvine",
            entity_type="issue",
            external_id=f"4000-step21-{issue.id}",
            metadata_json={},
        )
        db.add(identity)
        await db.flush()
        db.add(
            IssueExternalIdentityMapping(
                issue_id=issue.id,
                external_identity_id=identity.id,
                status="confirmed",
                evidence_source="step21_golden_path",
            )
        )
        db.add(
            CBLSourceEntry(
                list_id=source_list.id,
                position=cbl_position,
                series_name=issue.thread.title,
                issue_number=issue.issue_number,
                external_issue_identity_id=identity.id,
            )
        )
    await db.commit()
    return source_list


async def _bprd_pool(user_id: int, db: AsyncSession) -> list[Thread]:
    pool = await get_roll_pool(user_id, db)
    return [thread for thread in pool if thread.title.startswith("B.P.R.D.:")]


@pytest.mark.asyncio
async def test_bprd_step21_uses_targeted_adoption_and_advances_roll_boundary(
    auth_client: AsyncClient,
    async_db: AsyncSession,
) -> None:
    """Prove the canonical B.P.R.D. flow end to end without a direct-plan shortcut."""
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

    initial_reload = await auth_client.get(f"/api/v1/continuity-plans/{plan_id}")
    assert initial_reload.status_code == 200, initial_reload.text
    assert [node["ref_id"] for node in initial_reload.json()["nodes"]] == [
        issue.id for issue in current_order
    ]

    initial_pool = await _bprd_pool(user.id, async_db)
    assert [thread.id for thread in initial_pool] == [black_flame.id]
    assert black_flame.next_unread_issue_id == bf[1].id
    assert war_on_frogs.next_unread_issue_id == wof3.id
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

    groups_before = await async_db.scalar(
        select(func.count()).select_from(DependencyGroup).where(DependencyGroup.user_id == user.id)
    )
    source_path = "Dark Horse/B.P.R.D. Plague of Frogs Omnibus Vol. 3.cbl"
    source_list = await _seed_source(async_db, issues=next_phase, source_path=source_path)

    discovery = await auth_client.get("/api/v1/issue-identity/cbl-sources?q=B.P.R.D.")
    assert discovery.status_code == 200, discovery.text
    discovered_ids = [item["id"] for item in discovery.json()]
    assert source_list.id in discovered_ids

    preview_response = await auth_client.get(
        f"/api/v1/issue-identity/cbl/{source_list.id}/adoption-preview"
    )
    assert preview_response.status_code == 200, preview_response.text
    preview = preview_response.json()
    assert preview["total_positions"] == 15
    assert [entry["cbl_position"] for entry in preview["entries"]] == list(range(1, 16))
    assert {entry["adoption_class"] for entry in preview["entries"]} == {"existing"}
    assert {entry["adoption_decision"] for entry in preview["entries"]} == {
        "included_existing"
    }

    commit = await auth_client.post(
        f"/api/v1/cbl/{source_list.id}/reading-plans/{plan_id}/adoption-commit",
        json={
            "entry_decisions": {},
            "series_decisions": [],
            "series_overrides": [],
            "content_hash": preview["source"]["content_hash"],
            "revision_sha": preview["source"]["revision_sha"],
        },
    )
    assert commit.status_code == 200, commit.text
    committed = commit.json()
    assert committed["id"] == plan_id
    assert committed["reused_positions"] == list(range(1, 16))
    assert committed["created_positions"] == []
    assert committed["unresolved_positions"] == []

    reload_after_adoption = await auth_client.get(f"/api/v1/continuity-plans/{plan_id}")
    assert reload_after_adoption.status_code == 200, reload_after_adoption.text
    reloaded = reload_after_adoption.json()
    assert len(reloaded["nodes"]) == 37
    assert reloaded["lanes"] == [{"id": "main", "name": "Reading order", "order": 0}]
    assert [node["ref_id"] for node in reloaded["nodes"][:22]] == [
        issue.id for issue in current_order
    ]
    adopted_nodes = reloaded["nodes"][22:]
    assert [node["ref_id"] for node in adopted_nodes] == [issue.id for issue in next_phase]
    assert {node["lane_id"] for node in adopted_nodes} == {"main"}
    assert [
        placement["source_path"]
        for node in adopted_nodes
        for placement in node.get("source_cbl_placements", [])
    ] == [source_path] * len(adopted_nodes)

    groups_after = await async_db.scalar(
        select(func.count()).select_from(DependencyGroup).where(DependencyGroup.user_id == user.id)
    )
    assert groups_after == groups_before

    pool_after_adoption = await _bprd_pool(user.id, async_db)
    assert [thread.id for thread in pool_after_adoption] == [black_flame.id]
    assert war_on_frogs.is_blocked is True
    assert universal_machine.is_blocked is True
    assert garden_of_souls.is_blocked is True
    assert killing_ground.is_blocked is True

    # Finish the active Black Flame boundary through the same supported issue API
    # used by the reader.  War on Frogs #3 must then become the Roll candidate.
    for issue in bf[1:]:
        marked = await auth_client.post(f"/api/v1/issues/{issue.id}:markRead")
        assert marked.status_code == 204, marked.text
    await async_db.refresh(black_flame)
    await async_db.refresh(war_on_frogs)

    after_black_flame = await _bprd_pool(user.id, async_db)
    assert [thread.id for thread in after_black_flame] == [war_on_frogs.id]
    assert war_on_frogs.next_unread_issue_id == wof3.id
    assert war_on_frogs.is_blocked is False
    assert universal_machine.is_blocked is True

    # Completing the last pre-adoption prerequisite exposes the first issue from
    # the source-adopted phase.  There is no second readiness veto after Roll.
    marked_wof3 = await auth_client.post(f"/api/v1/issues/{wof3.id}:markRead")
    assert marked_wof3.status_code == 204, marked_wof3.text
    await async_db.refresh(war_on_frogs)
    await async_db.refresh(universal_machine)

    after_wof = await _bprd_pool(user.id, async_db)
    assert [thread.id for thread in after_wof] == [universal_machine.id]
    assert universal_machine.next_unread_issue_id == next_phase[0].id
    assert universal_machine.is_blocked is False
    assert garden_of_souls.is_blocked is True
    assert killing_ground.is_blocked is True
