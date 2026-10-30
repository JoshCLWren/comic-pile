"""Regression for #4028: CBL integration across browse, overlap, upsert and Roll.

These checks consolidate the closure-critical invariants that the functional
children (#4008-#4027) must jointly satisfy: the shared F2/M1/J2 fixture keeps
JLI rollable while Mister Miracle waits on Fourth World, overlap decisions are
scoped to one reader/list, and the baseline (no choice) still blocks J2.

Pure evaluator cases pin the Option E rules. The database-backed case saves the
overlap choice through the owned Reading List API, reloads both readers from
Postgres, and checks the Roll-visible eligibility result so broken upsert,
snapshot loading, or Roll wiring cannot hide behind hand-built snapshots.
"""

from __future__ import annotations

from collections.abc import Iterator
from dataclasses import replace

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth import create_access_token
from app.config import get_reading_execution_settings
from app.csrf import CSRF_COOKIE_NAME, CSRF_HEADER_NAME, generate_csrf_token
from app.main import app
from app.models import Dependency, Issue, Thread, User
from app.models.external_identity import ExternalIdentity, ThreadExternalSeriesMapping
from app.services.reading_eligibility_service import get_execution_eligibility
from app.services.reading_list_evaluator import (
    ReadingIssue,
    ReadingList,
    ReadingListEntry,
    ReadingPrerequisite,
    ReadingSnapshot,
    ReadingThread,
    SeriesOverlapDecision,
    evaluate,
)
from tests.conftest import get_or_create_user_async

FOURTH_WORLD = "comicvine:volume:fourth-world"
JLI = "comicvine:volume:jli"
MISTER_MIRACLE = "comicvine:volume:mister-miracle"

F1, F2 = 101, 102
J1, M1, J2, M2, J3 = 201, 202, 203, 204, 205

LIST_ID = 10
MISTER_MIRACLE_WAITS = SeriesOverlapDecision(JLI, MISTER_MIRACLE)

#: Durable Comic Vine volume IDs for the Postgres-backed F2/M1/J2 fixture.
FOURTH_WORLD_EXTERNAL_ID = "4010"
JLI_EXTERNAL_ID = "4011"
MISTER_MIRACLE_EXTERNAL_ID = "4012"
JLI_VOLUME_KEY = f"comicvine:{JLI_EXTERNAL_ID}"
MISTER_MIRACLE_VOLUME_KEY = f"comicvine:{MISTER_MIRACLE_EXTERNAL_ID}"


@pytest.fixture
def option_e(monkeypatch: pytest.MonkeyPatch, default_user: User) -> Iterator[None]:
    """Enable Option E for this process with a non-production preview marker."""
    monkeypatch.setenv("OPTION_E_ENABLED", "true")
    monkeypatch.setenv("OPTION_E_APPROVED_PREVIEW", "local-test-fixture-no-production-approval")
    get_reading_execution_settings.cache_clear()
    try:
        yield
    finally:
        get_reading_execution_settings.cache_clear()


def _threads() -> tuple[ReadingThread, ...]:
    return (
        ReadingThread(1, name="Fourth World", comicvine_volume_id=FOURTH_WORLD),
        ReadingThread(2, name="JLI", comicvine_volume_id=JLI),
        ReadingThread(3, name="Mister Miracle", comicvine_volume_id=MISTER_MIRACLE),
    )


def _issues(*, read: frozenset[int]) -> tuple[ReadingIssue, ...]:
    base = (
        ReadingIssue(F1, 1, 1),
        ReadingIssue(F2, 1, 2),
        ReadingIssue(J1, 2, 1),
        ReadingIssue(J2, 2, 2),
        ReadingIssue(J3, 2, 3),
        ReadingIssue(M1, 3, 1),
        ReadingIssue(M2, 3, 2),
    )
    return tuple(
        replace(issue, status="read") if issue.issue_id in read else issue for issue in base
    )


def _snapshot(
    *,
    approved: bool,
    user_id: int,
    read: frozenset[int] = frozenset({J1}),
) -> ReadingSnapshot:
    entries = (
        ReadingListEntry(J1),
        ReadingListEntry(M1),
        ReadingListEntry(J2),
        ReadingListEntry(M2),
        ReadingListEntry(J3),
    )
    decisions = (MISTER_MIRACLE_WAITS,) if approved else ()
    return ReadingSnapshot(
        user_id=user_id,
        threads=_threads(),
        issues=_issues(read=read),
        lists=(
            ReadingList(LIST_ID, "strict", entries, "JLI", decisions),
        ),
        prerequisites=(ReadingPrerequisite(1, F2, M1, "reader", ("reader approved",)),),
    )


def _offers(state: ReadingSnapshot) -> set[int]:
    return {
        result.next_issue_id
        for result in evaluate(state).values()
        if result.eligible and result.next_issue_id is not None
    }


def test_4028_approved_overlap_rolls_j2_while_m1_waits_for_f2(default_user: User) -> None:
    """With the reader's overlap choice, J2 is rollable; M1 stays blocked on F2."""
    state = _snapshot(user_id=default_user.id, approved=True)
    offered = _offers(state)
    assert J2 in offered, "JLI must keep rolling at J2 despite unread M1"
    assert M1 not in offered, "Mister Miracle M1 must still wait on Fourth World F2"
    assert J1 not in offered, "J1 is already read and cannot roll"


def test_4028_baseline_without_choice_blocks_j2_behind_m1(default_user: User) -> None:
    """Without an approved overlap, strict order keeps J2 behind M1."""
    state = _snapshot(user_id=default_user.id, approved=False)
    offered = _offers(state)
    assert J2 not in offered, "J2 must not roll until M1 is read without overlap"
    assert J1 not in offered


def test_4028_m1_unblocks_only_after_f2_is_read(default_user: User) -> None:
    """Fourth World completion releases Mister Miracle M1 for rolling."""
    state = _snapshot(user_id=default_user.id, approved=True, read=frozenset({J1, F1, F2}))
    offered = _offers(state)
    assert M1 in offered, "M1 must become rollable once F2 is read"


def test_4028_overlap_decision_is_per_reader_scoped(default_user: User, sample_user2: User) -> None:
    """A snapshot for a second reader without the decision keeps strict order."""
    second = replace(_snapshot(user_id=default_user.id, approved=False), user_id=sample_user2.id)
    offered = _offers(second)
    assert J2 not in offered


def test_4028_all_threads_present_in_eligibility_result(default_user: User) -> None:
    """Evaluate returns an entry for every active thread, including blocked ones."""
    state = _snapshot(user_id=default_user.id, approved=True)
    result = evaluate(state)
    assert set(result) == {1, 2, 3}, "Fourth World, JLI and Mister Miracle must all report"


async def _volume_series(
    db: AsyncSession,
    *,
    user_id: int,
    title: str,
    queue_position: int,
    volume_external_id: str,
    issue_count: int,
    read_positions: frozenset[int] = frozenset(),
) -> tuple[Thread, list[Issue]]:
    """Create one owned Thread with a confirmed Comic Vine volume and issues.

    Args:
        db: Current transaction.
        user_id: Reader who owns the Thread.
        title: Thread title.
        queue_position: Stable queue position of the Thread.
        volume_external_id: Comic Vine series identifier of the Thread.
        issue_count: Number of issues to create in natural order.
        read_positions: 1-based issue positions that start as read.

    Returns:
        The created Thread and its ordered Issues.
    """
    thread = Thread(
        user_id=user_id,
        title=title,
        format="Comic",
        queue_position=queue_position,
        status="active",
        total_issues=issue_count,
        issues_remaining=issue_count - len(read_positions),
    )
    db.add(thread)
    await db.flush()
    identity = (
        await db.execute(
            select(ExternalIdentity).where(
                ExternalIdentity.provider == "comicvine",
                ExternalIdentity.entity_type == "series",
                ExternalIdentity.external_id == volume_external_id,
            )
        )
    ).scalar_one_or_none()
    if identity is None:
        identity = ExternalIdentity(
            provider="comicvine",
            entity_type="series",
            external_id=volume_external_id,
        )
        db.add(identity)
        await db.flush()
    db.add(
        ThreadExternalSeriesMapping(
            thread_id=thread.id,
            external_identity_id=identity.id,
            status="confirmed",
            evidence_source="test",
        )
    )
    issues = [
        Issue(
            thread_id=thread.id,
            issue_number=str(position),
            position=position,
            status="read" if position in read_positions else "unread",
        )
        for position in range(1, issue_count + 1)
    ]
    db.add_all(issues)
    await db.flush()
    next_unread = next((issue for issue in issues if issue.status != "read"), None)
    thread.next_unread_issue_id = next_unread.id if next_unread is not None else None
    await db.flush()
    return thread, issues


async def _f2_m1_j2_library(
    db: AsyncSession,
    user_id: int,
) -> tuple[Thread, Thread, Thread, list[Issue], list[Issue], list[Issue]]:
    """Seed the shared Fourth World / JLI / Mister Miracle library for one reader.

    Args:
        db: Current transaction.
        user_id: Reader who owns the seeded Threads.

    Returns:
        Fourth World, JLI, and Mister Miracle Threads with their Issues.
    """
    fourth, fourth_issues = await _volume_series(
        db,
        user_id=user_id,
        title="Fourth World",
        queue_position=1,
        volume_external_id=FOURTH_WORLD_EXTERNAL_ID,
        issue_count=2,
    )
    jli, jli_issues = await _volume_series(
        db,
        user_id=user_id,
        title="JLI",
        queue_position=2,
        volume_external_id=JLI_EXTERNAL_ID,
        issue_count=3,
        read_positions=frozenset({1}),
    )
    miracle, miracle_issues = await _volume_series(
        db,
        user_id=user_id,
        title="Mister Miracle",
        queue_position=3,
        volume_external_id=MISTER_MIRACLE_EXTERNAL_ID,
        issue_count=2,
    )
    db.add(
        Dependency(
            source_issue_id=fourth_issues[1].id,
            target_issue_id=miracle_issues[0].id,
            origin="reader",
            classification="A",
            provenance="Explicit reader prerequisite",
        )
    )
    await db.flush()
    return fourth, jli, miracle, fourth_issues, jli_issues, miracle_issues


async def _authenticated_client(user: User) -> AsyncClient:
    """Build one authenticated ASGI client for ``user``.

    Args:
        user: Reader whose bearer token authenticates the client.

    Returns:
        An AsyncClient with CSRF and Authorization headers set.
    """
    client = AsyncClient(transport=ASGITransport(app=app), base_url="http://test")
    csrf_token = generate_csrf_token()
    client.cookies.set(CSRF_COOKIE_NAME, csrf_token)
    client.headers.update({CSRF_HEADER_NAME: csrf_token})
    token = create_access_token(data={"sub": user.username, "jti": f"4028-{user.id}"})
    client.headers.update({"Authorization": f"Bearer {token}"})
    return client


@pytest.mark.asyncio
async def test_4028_saved_overlap_reloads_per_reader_and_shows_on_roll(
    option_e: None,
    auth_client: AsyncClient,
    async_db: AsyncSession,
) -> None:
    """Saving the overlap choice scopes Roll offers to the owning reader only.

    Owner saves JLI-continues-past-Mister-Miracle through the Reading List API.
    After reload, the owner's Roll pool offers J2 while M1 stays blocked on F2.
    A second reader who shares the same Comic Vine volumes but never saved the
    choice still keeps J2 blocked behind M1.
    """
    owner = await get_or_create_user_async(async_db)
    (
        _owner_fourth,
        owner_jli,
        owner_miracle,
        owner_fourth_issues,
        owner_jli_issues,
        owner_miracle_issues,
    ) = await _f2_m1_j2_library(async_db, owner.id)
    other = await get_or_create_user_async(async_db, username="issue_4028_other_reader")
    (
        _other_fourth,
        other_jli,
        _other_miracle,
        _other_fourth_issues,
        other_jli_issues,
        other_miracle_issues,
    ) = await _f2_m1_j2_library(async_db, other.id)
    await async_db.commit()

    owner_j2_id = owner_jli_issues[1].id
    owner_m1_id = owner_miracle_issues[0].id
    owner_f2_id = owner_fourth_issues[1].id
    other_j2_id = other_jli_issues[1].id

    created = await auth_client.post(
        "/api/v1/custom-cbls",
        json={
            "name": "JLI",
            "mode": "strict",
            "issue_ids": [
                owner_jli_issues[0].id,
                owner_miracle_issues[0].id,
                owner_jli_issues[1].id,
                owner_miracle_issues[1].id,
                owner_jli_issues[2].id,
            ],
        },
    )
    assert created.status_code == 201, created.text
    owner_list_id = int(created.json()["id"])

    saved = await auth_client.put(
        f"/api/v1/custom-cbls/{owner_list_id}/overlap-decisions",
        json={
            "continuing_volume_id": JLI_VOLUME_KEY,
            "waiting_volume_id": MISTER_MIRACLE_VOLUME_KEY,
        },
    )
    assert saved.status_code == 200, saved.text
    assert len(saved.json()["decisions"]) == 1

    reloaded = await auth_client.get(f"/api/v1/custom-cbls/{owner_list_id}/overlap-decisions")
    assert reloaded.status_code == 200, reloaded.text
    assert [
        (row["continuing_volume_id"], row["waiting_volume_id"])
        for row in reloaded.json()["decisions"]
    ] == [(JLI_VOLUME_KEY, MISTER_MIRACLE_VOLUME_KEY)]

    other_client = await _authenticated_client(other)
    try:
        other_created = await other_client.post(
            "/api/v1/custom-cbls",
            json={
                "name": "JLI",
                "mode": "strict",
                "issue_ids": [
                    other_jli_issues[0].id,
                    other_miracle_issues[0].id,
                    other_jli_issues[1].id,
                    other_miracle_issues[1].id,
                    other_jli_issues[2].id,
                ],
            },
        )
        assert other_created.status_code == 201, other_created.text
        other_list_id = int(other_created.json()["id"])
        other_set = await other_client.get(
            f"/api/v1/custom-cbls/{other_list_id}/overlap-decisions"
        )
        assert other_set.status_code == 200, other_set.text
        assert other_set.json()["decisions"] == []
    finally:
        await other_client.aclose()

    owner_live = await get_execution_eligibility(async_db, owner.id)
    other_live = await get_execution_eligibility(async_db, other.id)
    assert owner_live is not None
    assert other_live is not None

    owner_jli_result = owner_live.threads[owner_jli.id]
    owner_miracle_result = owner_live.threads[owner_miracle.id]
    assert owner_jli_result.eligible is True
    assert owner_jli_result.next_issue_id == owner_j2_id
    assert owner_miracle_result.eligible is False
    assert owner_miracle_result.next_issue_id == owner_m1_id
    assert any(
        owner_f2_id in blocker.waiting_on_issue_ids
        for blocker in owner_miracle_result.blockers
    ), "Mister Miracle M1 must still wait on Fourth World F2 after the overlap save"

    other_jli_result = other_live.threads[other_jli.id]
    assert other_jli_result.eligible is False
    assert other_j2_id not in {
        result.next_issue_id
        for result in other_live.threads.values()
        if result.eligible and result.next_issue_id is not None
    }

    assert owner_jli.id in owner_live.candidate_ids()
    assert owner_miracle.id not in owner_live.candidate_ids()
    assert other_jli.id not in other_live.candidate_ids()

    # The live eligibility snapshot is the Roll candidate authority after the
    # Python bootstrap removal: JLI is readable at J2 while Miracle stays blocked.
    assert owner_live.threads[owner_jli.id].eligible is True
    assert owner_live.threads[owner_jli.id].next_issue_id == owner_j2_id
    assert owner_live.threads[owner_miracle.id].eligible is False
