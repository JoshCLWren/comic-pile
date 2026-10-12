"""Phase B of #2553: strict Reading Plan enforcement without adjacent blankets.

These PostgreSQL tests are the fail-before / pass-after regressions for the
named acceptance cases. Production data is never mutated.
"""

from __future__ import annotations

from collections.abc import Sequence
from datetime import UTC, datetime
from pathlib import Path

import pytest
from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.continuity_plan import ContinuityPlan
from app.models.continuity_rule import ContinuityRule
from app.models.dependency import Dependency
from app.models.issue import Issue
from app.models.reading_plan_membership import ReadingPlanIssue
from app.models.thread import Thread
from app.schemas.continuity_plan import ContinuityPlanNode
from app.services.continuity_plan_writer import plan_rule_marker, replace_compiled_rules
from app.services.reading_plan_normalization import (
    dry_run_plan_membership_reconcile,
    reconcile_plan_membership_from_nodes,
)
from app.services.strict_plan_constraints import (
    IssueThreadIndex,
    load_issue_thread_index,
    strict_plan_item_read_pairs,
)
from comic_pile.dependencies import (
    _get_blocked_thread_ids_uncached,
    get_blocking_explanations,
    refresh_user_blocked_status,
)
from comic_pile.queue import get_bounded_roll_pool_rows
from tests.conftest import get_or_create_user_async

_REPO_ROOT = Path(__file__).resolve().parents[1]


async def _make_series(
    db: AsyncSession,
    *,
    user_id: int,
    title: str,
    numbers: Sequence[str],
    queue_position: int,
    read_through: int = 0,
) -> tuple[Thread, list[Issue]]:
    """Create one owned Thread with ordered issues and a consistent frontier."""
    unread = max(len(numbers) - read_through, 0)
    thread = Thread(
        title=title,
        format="comic",
        issues_remaining=unread,
        queue_position=queue_position,
        status="active" if unread else "completed",
        user_id=user_id,
        total_issues=len(numbers),
        reading_progress="unstarted" if read_through == 0 else (
            "completed" if unread == 0 else "in_progress"
        ),
        created_at=datetime.now(UTC),
    )
    db.add(thread)
    await db.flush()
    issues: list[Issue] = []
    next_unread: int | None = None
    for position, number in enumerate(numbers, start=1):
        status = "read" if position <= read_through else "unread"
        issue = Issue(
            thread_id=thread.id,
            issue_number=number,
            position=position,
            status=status,
            read_at=datetime.now(UTC) if status == "read" else None,
        )
        db.add(issue)
        await db.flush()
        if status == "unread" and next_unread is None:
            next_unread = issue.id
        issues.append(issue)
    thread.next_unread_issue_id = next_unread
    return thread, issues


def _nodes(issues: list[Issue], *, start: int = 0) -> list[ContinuityPlanNode]:
    """Build one-lane issue nodes in the given list order."""
    return [
        ContinuityPlanNode(
            id=f"issue-{issue.id}",
            node_type="issue",
            ref_id=issue.id,
            lane_id="main",
            position=start + offset,
            convergence_gate=[],
        )
        for offset, issue in enumerate(issues)
    ]


def _plan_payload(
    name: str,
    issues: list[Issue],
    *,
    mode: str = "strict_sequential",
) -> dict[str, object]:
    """Build a one-lane plan create/update payload."""
    return {
        "name": name,
        "ordering_mode": mode,
        "lanes": [{"id": "main", "name": "Main", "order": 0}],
        "nodes": [
            {
                "id": f"issue-{issue.id}",
                "node_type": "issue",
                "ref_id": issue.id,
                "lane_id": "main",
                "position": position,
                "is_checkpoint": False,
                "convergence_gate": None,
            }
            for position, issue in enumerate(issues)
        ],
    }


async def _roll_ids(user_id: int, db: AsyncSession) -> set[int]:
    """Return currently Roll-eligible thread ids in the bounded pool."""
    await refresh_user_blocked_status(user_id, db)
    rows = await get_bounded_roll_pool_rows(user_id, db, current_die=20)
    return {row[0].id for row in rows}


async def _compiled_pairs(
    db: AsyncSession, *, user_id: int, plan_id: int
) -> set[tuple[int, int]]:
    """Return plan-owned compiled item_read pairs."""
    rules = (
        await db.execute(
            select(ContinuityRule).where(
                ContinuityRule.user_id == user_id,
                ContinuityRule.note == plan_rule_marker(plan_id),
            )
        )
    ).scalars().all()
    return {(rule.source_id, rule.target_id) for rule in rules}


def test_strict_compiler_has_no_title_exemption() -> None:
    """Wild Hunt protection is series-start geometry, not a title special case."""
    source = (_REPO_ROOT / "app/services/strict_plan_constraints.py").read_text()
    writer = (_REPO_ROOT / "app/services/continuity_plan_writer.py").read_text()
    for banned in ("title ==", "thread.title", ".ilike("):
        assert banned not in source
        assert banned not in writer


def test_thread_entry_pairs_skip_same_thread_and_non_starts() -> None:
    """Pure selection: only a later series start is gated by the prior required issue."""
    killing_ground = [101, 102]
    wild_hunt = [201, 202, 203]
    later_start = [301]
    nodes = _nodes_from_ids(killing_ground + wild_hunt + later_start)
    index = {
        101: IssueThreadIndex(1, 1, True),
        102: IssueThreadIndex(1, 2, False),
        201: IssueThreadIndex(2, 1, True),
        202: IssueThreadIndex(2, 2, False),
        203: IssueThreadIndex(2, 3, False),
        301: IssueThreadIndex(3, 1, True),
    }
    assert strict_plan_item_read_pairs(nodes, index) == [(102, 201), (203, 301)]


def test_in_progress_series_omitted_earlier_issues_are_not_starts() -> None:
    """Wild Hunt #3 is not a series start merely because #1-2 are absent from the plan."""
    nodes = _nodes_from_ids([102, 203, 301])
    index = {
        102: IssueThreadIndex(1, 2, False),
        203: IssueThreadIndex(2, 3, False),
        301: IssueThreadIndex(3, 1, True),
    }
    # Wild Hunt #3 is not a target. The later series start waits on the nearest
    # preceding required issue from another Thread, which is Wild Hunt #3.
    assert strict_plan_item_read_pairs(nodes, index) == [(203, 301)]


def _nodes_from_ids(issue_ids: list[int]) -> list[ContinuityPlanNode]:
    """Build nodes from synthetic issue ids for pure selection tests."""
    return [
        ContinuityPlanNode(
            id=f"n-{issue_id}",
            node_type="issue",
            ref_id=issue_id,
            lane_id="main",
            position=position,
            convergence_gate=[],
        )
        for position, issue_id in enumerate(issue_ids)
    ]


@pytest.mark.asyncio
async def test_starman_jsa_shared_prerequisite_survives_independent_plans(
    auth_client: AsyncClient,
    async_db: AsyncSession,
) -> None:
    """Starman #55 gates the JSA start; plans stay independent; one read satisfies both."""
    user = await get_or_create_user_async(async_db)
    starman, starman_issues = await _make_series(
        async_db,
        user_id=user.id,
        title="Starman",
        numbers=["54", "55", "56"],
        queue_position=1,
        read_through=1,
    )
    jsa, jsa_issues = await _make_series(
        async_db,
        user_id=user.id,
        title="JSA (Robinson / Goyer / Johns)",
        numbers=["1", "2"],
        queue_position=2,
    )
    starman_55 = starman_issues[1]
    jsa_start = jsa_issues[0]
    async_db.add(
        Dependency(
            source_issue_id=starman_55.id,
            target_issue_id=jsa_start.id,
            note="Launch the Robinson/Goyer/Johns JSA path alongside Starman after Starman #55.",
        )
    )
    await async_db.commit()

    starman_plan = await auth_client.post(
        "/api/v1/continuity-plans/",
        json=_plan_payload("Starman", starman_issues, mode="strict_sequential"),
    )
    jsa_plan = await auth_client.post(
        "/api/v1/continuity-plans/",
        json=_plan_payload("JSA", jsa_issues, mode="strict_sequential"),
    )
    assert starman_plan.status_code == 201, starman_plan.text
    assert jsa_plan.status_code == 201, jsa_plan.text
    starman_plan_id = starman_plan.json()["id"]
    jsa_plan_id = jsa_plan.json()["id"]
    # Same-thread adjacency is not compiled; the shared standalone edge is the gate.
    assert await _compiled_pairs(async_db, user_id=user.id, plan_id=starman_plan_id) == set()
    assert await _compiled_pairs(async_db, user_id=user.id, plan_id=jsa_plan_id) == set()

    roll_ids = await _roll_ids(user.id, async_db)
    assert starman.id in roll_ids
    assert jsa.id not in roll_ids
    reasons = await get_blocking_explanations(jsa.id, user.id, async_db)
    assert [reason.label for reason in reasons] == ["Blocked by Starman: #55"]

    starman_55.status = "read"
    starman_55.read_at = datetime.now(UTC)
    starman.next_unread_issue_id = starman_issues[2].id
    starman.issues_remaining = 1
    await async_db.flush()
    roll_after = await _roll_ids(user.id, async_db)
    assert {starman.id, jsa.id} <= roll_after
    assert await get_blocking_explanations(jsa.id, user.id, async_db) == []

    deleted = await auth_client.delete(f"/api/v1/continuity-plans/{starman_plan_id}")
    assert deleted.status_code == 204
    remaining = (
        await async_db.execute(
            select(Dependency).where(
                Dependency.source_issue_id == starman_55.id,
                Dependency.target_issue_id == jsa_start.id,
            )
        )
    ).scalar_one_or_none()
    assert remaining is not None
    assert remaining.note is not None and remaining.note.startswith("Launch the Robinson")
    assert jsa_plan_id == jsa_plan.json()["id"]
    assert await async_db.get(ContinuityPlan, jsa_plan_id) is not None


@pytest.mark.asyncio
async def test_xmen_cable_xforce_preserves_genuine_prereqs_not_suggested_order(
    auth_client: AsyncClient,
    async_db: AsyncSession,
) -> None:
    """Interleaved suggested-order hops are not compiled; UXRO-style edges still block."""
    user = await get_or_create_user_async(async_db)
    uncanny, uncanny_all = await _make_series(
        async_db,
        user_id=user.id,
        title="Uncanny X-Men",
        numbers=["300", "377", "378", "379"],
        queue_position=1,
        read_through=1,
    )
    cable, cable_all = await _make_series(
        async_db,
        user_id=user.id,
        title="Cable",
        numbers=["63", "76", "77", "78"],
        queue_position=2,
        read_through=1,
    )
    xforce, xforce_all = await _make_series(
        async_db,
        user_id=user.id,
        title="X-Force",
        numbers=["90", "101", "102"],
        queue_position=3,
        read_through=1,
    )
    uncanny_issues = uncanny_all[1:]
    cable_issues = cable_all[1:]
    xforce_issues = xforce_all[1:]
    genuine = Dependency(
        source_issue_id=cable_issues[2].id,
        target_issue_id=xforce_issues[0].id,
        note="UXRO Era Ten: Cable #78 -> X-Force #101",
    )
    async_db.add(genuine)
    await async_db.commit()

    interleaved = [
        uncanny_issues[0],
        cable_issues[0],
        uncanny_issues[1],
        cable_issues[1],
        uncanny_issues[2],
        cable_issues[2],
        xforce_issues[0],
        xforce_issues[1],
    ]
    created = await auth_client.post(
        "/api/v1/continuity-plans/",
        json=_plan_payload("Late-90s X-Men Reading Order", interleaved),
    )
    assert created.status_code == 201, created.text
    plan_id = created.json()["id"]
    compiled = await _compiled_pairs(async_db, user_id=user.id, plan_id=plan_id)
    assert compiled == set()
    note = (
        await async_db.execute(
            select(Dependency.note).where(
                Dependency.source_issue_id == cable_issues[2].id,
                Dependency.target_issue_id == xforce_issues[0].id,
            )
        )
    ).scalar_one()
    assert note == "UXRO Era Ten: Cable #78 -> X-Force #101"

    roll_ids = await _roll_ids(user.id, async_db)
    assert uncanny.id in roll_ids
    assert cable.id in roll_ids
    assert xforce.id not in roll_ids

    cable_issues[2].status = "read"
    cable_issues[2].read_at = datetime.now(UTC)
    cable.next_unread_issue_id = None
    cable.issues_remaining = 0
    await async_db.flush()
    roll_after = await _roll_ids(user.id, async_db)
    assert xforce.id in roll_after


@pytest.mark.asyncio
async def test_mignolaverse_wild_hunt_continues_without_blanket_restrictions(
    auth_client: AsyncClient,
    async_db: AsyncSession,
) -> None:
    """Killing Ground before Wild Hunt stays strict; Wild Hunt #3 remains available."""
    user = await get_or_create_user_async(async_db)
    killing_ground, kg_issues = await _make_series(
        async_db,
        user_id=user.id,
        title="B.P.R.D.: Killing Ground",
        numbers=["1", "2", "3", "4", "5"],
        queue_position=1,
    )
    wild_hunt, wh_issues = await _make_series(
        async_db,
        user_id=user.id,
        title="Hellboy: The Wild Hunt",
        numbers=["1", "2", "3", "4"],
        queue_position=2,
        read_through=2,
    )
    later, later_issues = await _make_series(
        async_db,
        user_id=user.id,
        title="Hellboy in Hell",
        numbers=["1", "2"],
        queue_position=3,
    )
    await async_db.commit()

    ordered = kg_issues + wh_issues + later_issues
    created = await auth_client.post(
        "/api/v1/continuity-plans/",
        json=_plan_payload("Mignolaverse", ordered),
    )
    assert created.status_code == 201, created.text
    body = created.json()
    assert body["ordering_mode"] == "strict_sequential"
    assert body["name"] == "Mignolaverse"
    compiled = await _compiled_pairs(async_db, user_id=user.id, plan_id=body["id"])
    assert compiled == {
        (kg_issues[-1].id, wh_issues[0].id),
        (wh_issues[-1].id, later_issues[0].id),
    }
    assert (wh_issues[1].id, wh_issues[2].id) not in compiled
    assert (kg_issues[-1].id, wh_issues[2].id) not in compiled

    roll_ids = await _roll_ids(user.id, async_db)
    assert wild_hunt.id in roll_ids
    assert later.id not in roll_ids
    blocked = await _get_blocked_thread_ids_uncached(user.id, async_db)
    assert wild_hunt.id not in blocked
    assert later.id in blocked
    reasons = await get_blocking_explanations(later.id, user.id, async_db)
    assert reasons[0].issue_number == "4"


@pytest.mark.asyncio
async def test_absolute_universe_later_series_are_gated_without_same_thread_edges(
    auth_client: AsyncClient,
    async_db: AsyncSession,
) -> None:
    """Later Absolute titles are not Roll-eligible; same-title progression is not a Dependency."""
    user = await get_or_create_user_async(async_db)
    batman, batman_issues = await _make_series(
        async_db,
        user_id=user.id,
        title="Absolute Batman",
        numbers=["1", "2"],
        queue_position=1,
    )
    superman, superman_issues = await _make_series(
        async_db,
        user_id=user.id,
        title="Absolute Superman",
        numbers=["1", "2"],
        queue_position=2,
    )
    wonder_woman, ww_issues = await _make_series(
        async_db,
        user_id=user.id,
        title="Absolute Wonder Woman",
        numbers=["1"],
        queue_position=3,
    )
    async_db.add(
        Dependency(
            source_issue_id=batman_issues[0].id,
            target_issue_id=batman_issues[1].id,
            note="cbl-order:source:absolute-universe:1->2",
        )
    )
    async_db.add(
        Dependency(
            source_issue_id=batman_issues[1].id,
            target_issue_id=superman_issues[0].id,
            note="cbl-order:source:absolute-universe:2->3",
        )
    )
    await async_db.commit()

    ordered = batman_issues + superman_issues + ww_issues
    created = await auth_client.post(
        "/api/v1/continuity-plans/",
        json=_plan_payload("Absolute Universe", ordered),
    )
    assert created.status_code == 201, created.text
    plan_id = created.json()["id"]
    compiled = await _compiled_pairs(async_db, user_id=user.id, plan_id=plan_id)
    assert compiled == {
        (batman_issues[1].id, superman_issues[0].id),
        (superman_issues[1].id, ww_issues[0].id),
    }
    assert (batman_issues[0].id, batman_issues[1].id) not in compiled

    roll_ids = await _roll_ids(user.id, async_db)
    assert batman.id in roll_ids
    assert superman.id not in roll_ids
    assert wonder_woman.id not in roll_ids
    same_thread_cbl = (
        await async_db.execute(
            select(Dependency.note).where(
                Dependency.source_issue_id == batman_issues[0].id,
                Dependency.target_issue_id == batman_issues[1].id,
            )
        )
    ).scalar_one()
    assert same_thread_cbl is not None
    assert same_thread_cbl.startswith("cbl-order:source:")
    promoted = (
        await async_db.execute(
            select(Dependency.note).where(
                Dependency.source_issue_id == batman_issues[1].id,
                Dependency.target_issue_id == superman_issues[0].id,
            )
        )
    ).scalar_one()
    assert promoted is not None
    assert promoted.startswith("canonical:rule:")

    batman_issues[0].status = "read"
    batman_issues[0].read_at = datetime.now(UTC)
    batman.next_unread_issue_id = batman_issues[1].id
    batman.issues_remaining = 1
    await async_db.flush()
    still_gated = await _roll_ids(user.id, async_db)
    assert superman.id not in still_gated

    batman_issues[1].status = "read"
    batman_issues[1].read_at = datetime.now(UTC)
    batman.next_unread_issue_id = None
    batman.issues_remaining = 0
    await async_db.flush()
    after_batman = await _roll_ids(user.id, async_db)
    assert superman.id in after_batman
    assert wonder_woman.id not in after_batman


@pytest.mark.asyncio
async def test_informational_plan_adds_no_hard_blockers(
    auth_client: AsyncClient,
    async_db: AsyncSession,
) -> None:
    """Imported CBL-shaped informational order never compiles Roll blockers."""
    user = await get_or_create_user_async(async_db)
    first, first_issues = await _make_series(
        async_db, user_id=user.id, title="Info A", numbers=["1"], queue_position=1
    )
    second, second_issues = await _make_series(
        async_db, user_id=user.id, title="Info B", numbers=["1"], queue_position=2
    )
    await async_db.commit()
    created = await auth_client.post(
        "/api/v1/continuity-plans/",
        json=_plan_payload(
            "Imported CBL",
            first_issues + second_issues,
            mode="informational",
        ),
    )
    assert created.status_code == 201, created.text
    assert created.json()["ordering_mode"] == "informational"
    rules = (
        await async_db.execute(
            select(ContinuityRule).where(ContinuityRule.user_id == user.id)
        )
    ).scalars().all()
    assert rules == []
    roll_ids = await _roll_ids(user.id, async_db)
    assert {first.id, second.id} <= roll_ids


@pytest.mark.asyncio
async def test_strict_plan_lifecycle_create_edit_strictness_delete(
    auth_client: AsyncClient,
    async_db: AsyncSession,
) -> None:
    """Create, re-save, edit, change strictness, and delete keep blockers aligned."""
    user = await get_or_create_user_async(async_db)
    first, first_issues = await _make_series(
        async_db, user_id=user.id, title="Lifecycle A", numbers=["1"], queue_position=1
    )
    second, second_issues = await _make_series(
        async_db, user_id=user.id, title="Lifecycle B", numbers=["1"], queue_position=2
    )
    third, third_issues = await _make_series(
        async_db, user_id=user.id, title="Lifecycle C", numbers=["1"], queue_position=3
    )
    await async_db.commit()
    payload = _plan_payload("Lifecycle", first_issues + second_issues)
    created = await auth_client.post("/api/v1/continuity-plans/", json=payload)
    assert created.status_code == 201, created.text
    plan_id = created.json()["id"]
    assert await _compiled_pairs(async_db, user_id=user.id, plan_id=plan_id) == {
        (first_issues[0].id, second_issues[0].id),
    }
    assert second.id in await _get_blocked_thread_ids_uncached(user.id, async_db)

    resave = await auth_client.put(f"/api/v1/continuity-plans/{plan_id}", json=payload)
    assert resave.status_code == 200, resave.text
    assert await _compiled_pairs(async_db, user_id=user.id, plan_id=plan_id) == {
        (first_issues[0].id, second_issues[0].id),
    }

    edited = _plan_payload("Lifecycle", first_issues + third_issues)
    updated = await auth_client.put(f"/api/v1/continuity-plans/{plan_id}", json=edited)
    assert updated.status_code == 200, updated.text
    assert await _compiled_pairs(async_db, user_id=user.id, plan_id=plan_id) == {
        (first_issues[0].id, third_issues[0].id),
    }
    blocked = await _get_blocked_thread_ids_uncached(user.id, async_db)
    assert third.id in blocked
    assert second.id not in blocked

    informational = _plan_payload(
        "Lifecycle", first_issues + third_issues, mode="informational"
    )
    relaxed = await auth_client.put(
        f"/api/v1/continuity-plans/{plan_id}", json=informational
    )
    assert relaxed.status_code == 200, relaxed.text
    assert relaxed.json()["ordering_mode"] == "informational"
    assert await _compiled_pairs(async_db, user_id=user.id, plan_id=plan_id) == set()
    assert third.id not in await _get_blocked_thread_ids_uncached(user.id, async_db)

    restored = await auth_client.put(f"/api/v1/continuity-plans/{plan_id}", json=edited)
    assert restored.status_code == 200, restored.text
    assert restored.json()["ordering_mode"] == "strict_sequential"
    assert await _compiled_pairs(async_db, user_id=user.id, plan_id=plan_id) == {
        (first_issues[0].id, third_issues[0].id),
    }

    peer = await auth_client.post(
        "/api/v1/continuity-plans/",
        json=_plan_payload("Peer", first_issues + third_issues),
    )
    # Equivalent standalone reuse: the second plan must not destroy the first gate.
    assert peer.status_code in {201, 409}, peer.text

    deleted = await auth_client.delete(f"/api/v1/continuity-plans/{plan_id}")
    assert deleted.status_code == 204
    remaining_edge = (
        await async_db.execute(
            select(Dependency).where(
                Dependency.source_issue_id == first_issues[0].id,
                Dependency.target_issue_id == third_issues[0].id,
            )
        )
    ).scalar_one_or_none()
    if peer.status_code == 201:
        assert remaining_edge is not None
    else:
        assert remaining_edge is None


@pytest.mark.asyncio
async def test_two_plans_share_prerequisite_and_deletion_is_plan_local(
    auth_client: AsyncClient,
    async_db: AsyncSession,
) -> None:
    """Deleting one plan retires only its compiled restrictions, not a shared standalone edge."""
    user = await get_or_create_user_async(async_db)
    source, source_issues = await _make_series(
        async_db, user_id=user.id, title="Shared Source", numbers=["1"], queue_position=1
    )
    target, target_issues = await _make_series(
        async_db, user_id=user.id, title="Shared Target", numbers=["1"], queue_position=2
    )
    async_db.add(
        Dependency(
            source_issue_id=source_issues[0].id,
            target_issue_id=target_issues[0].id,
            note="shared standalone prerequisite",
        )
    )
    await async_db.commit()
    first = await auth_client.post(
        "/api/v1/continuity-plans/",
        json=_plan_payload("Plan P", source_issues + target_issues),
    )
    second = await auth_client.post(
        "/api/v1/continuity-plans/",
        json=_plan_payload("Plan Q", source_issues + target_issues),
    )
    assert first.status_code == 201, first.text
    assert second.status_code == 201, second.text
    deleted = await auth_client.delete(f"/api/v1/continuity-plans/{first.json()['id']}")
    assert deleted.status_code == 204
    surviving = (
        await async_db.execute(
            select(Dependency).where(
                Dependency.source_issue_id == source_issues[0].id,
                Dependency.target_issue_id == target_issues[0].id,
            )
        )
    ).scalar_one()
    assert surviving.note == "shared standalone prerequisite"
    roll_ids = await _roll_ids(user.id, async_db)
    assert source.id in roll_ids
    assert target.id not in roll_ids


@pytest.mark.asyncio
async def test_absolute_universe_membership_gap_and_dangling_node_reconcile(
    async_db: AsyncSession,
) -> None:
    """Plan JSON with extra nodes and a missing issue id rebuilds only real memberships."""
    user = await get_or_create_user_async(async_db)
    _thread, issues = await _make_series(
        async_db,
        user_id=user.id,
        title="Absolute Batman",
        numbers=["1", "2", "3"],
        queue_position=1,
    )
    await async_db.commit()
    dangling_id = 1117318
    plan = ContinuityPlan(
        user_id=user.id,
        name="Absolute Universe",
        ordering_mode="strict_sequential",
        lanes_json=[{"id": "main", "name": "Main", "order": 0}],
        nodes_json=[
            {
                "id": f"issue-{issue.id}",
                "node_type": "issue",
                "ref_id": issue.id,
                "lane_id": "main",
                "position": position,
            }
            for position, issue in enumerate(issues)
        ]
        + [
            {
                "id": "dangling",
                "node_type": "issue",
                "ref_id": dangling_id,
                "lane_id": "main",
                "position": 3,
            }
        ],
    )
    async_db.add(plan)
    await async_db.flush()
    async_db.add(
        ReadingPlanIssue(
            plan_id=plan.id,
            occurrence_id=f"issue-{issues[0].id}",
            issue_id=issues[0].id,
            lane_id="main",
            display_position=0,
            is_checkpoint=False,
        )
    )
    await async_db.commit()
    await async_db.refresh(plan)

    dry = await dry_run_plan_membership_reconcile(async_db, plan=plan)
    assert dry.inserted_issue_ids == (issues[1].id, issues[2].id)
    assert dry.skipped_missing_issue_ids == (dangling_id,)
    membership_before_dry = (
        await async_db.execute(
            select(ReadingPlanIssue.issue_id).where(ReadingPlanIssue.plan_id == plan.id)
        )
    ).scalars().all()
    assert list(membership_before_dry) == [issues[0].id]

    report = await reconcile_plan_membership_from_nodes(async_db, plan=plan)
    await async_db.commit()
    assert report.skipped_missing_issue_ids == (dangling_id,)
    assert report.membership_count == 3
    assert report.inserted_issue_ids == (issues[1].id, issues[2].id)
    assert report.removed_issue_ids == ()
    assert report.before.plan_owned_item_read_pairs == ()
    assert report.after.plan_owned_item_read_pairs == ()
    assert report.before.roll_blocking_pairs == report.after.roll_blocking_pairs
    rows = (
        await async_db.execute(
            select(ReadingPlanIssue.issue_id)
            .where(ReadingPlanIssue.plan_id == plan.id)
            .order_by(ReadingPlanIssue.display_position)
        )
    ).scalars().all()
    assert list(rows) == [issue.id for issue in issues]
    refreshed = await async_db.get(ContinuityPlan, plan.id)
    assert refreshed is not None
    assert len(refreshed.nodes_json) == 4
    assert refreshed.ordering_mode == "strict_sequential"

    await replace_compiled_rules(
        async_db,
        user_id=user.id,
        plan=plan,
        nodes=_nodes(issues),
        ordering_mode="strict_sequential",
    )
    await async_db.commit()
    assert await _compiled_pairs(async_db, user_id=user.id, plan_id=plan.id) == set()


@pytest.mark.asyncio
async def test_absolute_universe_membership_repair_does_not_compile_restrictions(
    async_db: AsyncSession,
) -> None:
    """#3486: JSON is intended membership; repair must not re-save into blockers.

    Production plan 20 has 105 JSON issue nodes and 76 membership rows. The
    missing 29 are the tail, including later series starts. Re-saving the
    whole JSON through the old adjacent compiler would emit a blocker per
    hop. This repair copies existing Issue refs into membership only.
    """
    user = await get_or_create_user_async(async_db)
    batman, batman_issues = await _make_series(
        async_db,
        user_id=user.id,
        title="Absolute Batman",
        numbers=["18", "19", "20"],
        queue_position=1,
        read_through=3,
    )
    green_arrow, ga_issues = await _make_series(
        async_db,
        user_id=user.id,
        title="Absolute Green Arrow",
        numbers=["1", "2", "3"],
        queue_position=2,
        read_through=1,
    )
    catwoman, catwoman_issues = await _make_series(
        async_db,
        user_id=user.id,
        title="Absolute Catwoman",
        numbers=["1", "2", "3"],
        queue_position=3,
    )
    cassandra, cassandra_issues = await _make_series(
        async_db,
        user_id=user.id,
        title="Absolute Cassandra Cain: The Shadow's Hand",
        numbers=["1"],
        queue_position=4,
    )
    genuine = Dependency(
        source_issue_id=catwoman_issues[2].id,
        target_issue_id=cassandra_issues[0].id,
        note="Read Absolute Catwoman #3 before Absolute Cassandra Cain #1.",
    )
    async_db.add(genuine)
    await async_db.flush()
    # First 76 analog: only Batman is in the membership table.
    json_issues = batman_issues + ga_issues + catwoman_issues + cassandra_issues
    plan = ContinuityPlan(
        user_id=user.id,
        name="Absolute Universe",
        ordering_mode="strict_sequential",
        lanes_json=[{"id": "main", "name": "Main", "order": 0}],
        nodes_json=[
            {
                "id": f"issue-{issue.id}",
                "node_type": "issue",
                "ref_id": issue.id,
                "lane_id": "main",
                "position": position,
            }
            for position, issue in enumerate(json_issues)
        ],
    )
    async_db.add(plan)
    await async_db.flush()
    for position, issue in enumerate(batman_issues):
        async_db.add(
            ReadingPlanIssue(
                plan_id=plan.id,
                occurrence_id=f"issue-{issue.id}",
                issue_id=issue.id,
                lane_id="main",
                display_position=position,
                is_checkpoint=False,
            )
        )
    adjacent = ContinuityRule(
        user_id=user.id,
        source_type="issue",
        source_id=batman_issues[0].id,
        target_type="issue",
        target_id=batman_issues[1].id,
        satisfaction_type="item_read",
        note=plan_rule_marker(plan.id),
    )
    async_db.add(adjacent)
    await async_db.commit()
    await async_db.refresh(plan)
    await refresh_user_blocked_status(user.id, async_db)

    roll_before = await _roll_ids(user.id, async_db)
    assert green_arrow.id in roll_before
    assert catwoman.id in roll_before
    assert cassandra.id not in roll_before
    assert batman.id not in roll_before or batman.issues_remaining == 0

    dry = await dry_run_plan_membership_reconcile(async_db, plan=plan)
    assert dry.before.membership_issue_ids == tuple(
        issue.id for issue in batman_issues
    )
    missing = tuple(issue.id for issue in ga_issues + catwoman_issues + cassandra_issues)
    assert dry.inserted_issue_ids == missing
    assert dry.after.plan_owned_item_read_pairs == dry.before.plan_owned_item_read_pairs
    assert dry.after.plan_owned_item_read_pairs == (
        (batman_issues[0].id, batman_issues[1].id),
    )
    assert dry.after.roll_blocking_pairs == (
        (catwoman_issues[2].id, cassandra_issues[0].id),
    )
    assert dry.before.roll_blocking_pairs == ()
    still_one_member_row = (
        await async_db.execute(
            select(ReadingPlanIssue).where(ReadingPlanIssue.plan_id == plan.id)
        )
    ).scalars().all()
    assert len(still_one_member_row) == 3
    assert await _compiled_pairs(async_db, user_id=user.id, plan_id=plan.id) == {
        (batman_issues[0].id, batman_issues[1].id),
    }

    report = await reconcile_plan_membership_from_nodes(async_db, plan=plan)
    await async_db.commit()
    assert report.inserted_issue_ids == missing
    assert report.removed_issue_ids == ()
    assert report.membership_count == 10
    assert report.after.plan_owned_item_read_pairs == report.before.plan_owned_item_read_pairs
    assert report.after.plan_linked_dependency_pairs == ()
    assert report.after.roll_blocking_pairs == (
        (catwoman_issues[2].id, cassandra_issues[0].id),
    )
    refreshed = await async_db.get(ContinuityPlan, plan.id)
    assert refreshed is not None
    assert len(refreshed.nodes_json) == 10
    assert refreshed.ordering_mode == "strict_sequential"
    assert await _compiled_pairs(async_db, user_id=user.id, plan_id=plan.id) == {
        (batman_issues[0].id, batman_issues[1].id),
    }

    roll_after = await _roll_ids(user.id, async_db)
    assert green_arrow.id in roll_after
    assert catwoman.id in roll_after
    assert cassandra.id not in roll_after
    # Projected compile is thread-entry, not one blocker per JSON hop.
    assert (ga_issues[0].id, ga_issues[1].id) not in report.projected_thread_entry_pairs
    assert (catwoman_issues[0].id, cassandra_issues[0].id) not in (
        report.projected_thread_entry_pairs
    )
    assert (batman_issues[-1].id, ga_issues[0].id) in report.projected_thread_entry_pairs
    assert (ga_issues[-1].id, catwoman_issues[0].id) in report.projected_thread_entry_pairs

    await replace_compiled_rules(
        async_db,
        user_id=user.id,
        plan=plan,
        nodes=_nodes(json_issues),
        ordering_mode="strict_sequential",
    )
    await async_db.commit()
    compiled = await _compiled_pairs(async_db, user_id=user.id, plan_id=plan.id)
    assert (ga_issues[0].id, ga_issues[1].id) not in compiled
    assert (batman_issues[0].id, batman_issues[1].id) not in compiled
    assert compiled == set(report.projected_thread_entry_pairs)
    roll_compiled = await _roll_ids(user.id, async_db)
    assert green_arrow.id in roll_compiled
    assert cassandra.id not in roll_compiled


@pytest.mark.asyncio
async def test_queue_and_roll_agree_on_strict_thread_entry(
    auth_client: AsyncClient,
    async_db: AsyncSession,
) -> None:
    """Queue explanations and Roll eligibility use the same canonical edge."""
    user = await get_or_create_user_async(async_db)
    lead, lead_issues = await _make_series(
        async_db, user_id=user.id, title="Lead Series", numbers=["1"], queue_position=1
    )
    follow, follow_issues = await _make_series(
        async_db, user_id=user.id, title="Follow Series", numbers=["1"], queue_position=2
    )
    await async_db.commit()
    created = await auth_client.post(
        "/api/v1/continuity-plans/",
        json=_plan_payload("Queue Roll", lead_issues + follow_issues),
    )
    assert created.status_code == 201, created.text
    blocked = await _get_blocked_thread_ids_uncached(user.id, async_db)
    roll_ids = await _roll_ids(user.id, async_db)
    reasons = await get_blocking_explanations(follow.id, user.id, async_db)
    assert follow.id in blocked
    assert follow.id not in roll_ids
    assert lead.id in roll_ids
    assert [reason.label for reason in reasons] == ["Blocked by Lead Series: #1"]
    info = await auth_client.post(f"/api/v1/threads/{follow.id}:getBlockingInfo")
    assert info.status_code == 200, info.text
    assert info.json()["is_blocked"] is True
    assert info.json()["blocking_reasons"] == ["Blocked by Lead Series: #1"]


@pytest.mark.asyncio
async def test_load_issue_thread_index_uses_whole_thread_minimum(
    async_db: AsyncSession,
) -> None:
    """Natural start is the Thread minimum, not the first plan member."""
    user = await get_or_create_user_async(async_db)
    _thread, issues = await _make_series(
        async_db,
        user_id=user.id,
        title="Hellboy: The Wild Hunt",
        numbers=["1", "2", "3"],
        queue_position=1,
        read_through=2,
    )
    await async_db.commit()
    index = await load_issue_thread_index(async_db, [issues[2].id])
    assert index[issues[2].id].is_thread_natural_start is False
    assert index[issues[2].id].position == 3
