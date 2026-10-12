"""PostgreSQL idempotency for CBL adoption-commit (#3489 review).

Retries and concurrent workers for the same user and CBL list must never create
a second Reading Plan or repeat comic creation, even when the client never
receives the success response. Owned entries can be excluded individually.
"""

from __future__ import annotations

import asyncio
import uuid
from datetime import UTC, datetime

import pytest
from httpx import AsyncClient
from sqlalchemy import delete, func, select
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)
from sqlalchemy.pool import NullPool

from app.models.cbl_adoption_receipt import CblAdoptionReceipt
from app.models.cbl_reference import CBLSource, CBLSourceEntry, CBLSourceList
from app.models.continuity_plan import ContinuityPlan
from app.models.external_identity import ExternalIdentity, IssueExternalIdentityMapping
from app.models.issue import Issue
from app.models.thread import Thread
from app.models.user import User
from app.services.cbl_plan_adoption import adopt_cbl_material_into_reading_plan
from tests.conftest import get_or_create_user_async, get_test_database_url


def _suffix() -> str:
    return uuid.uuid4().hex[:10]


async def _fresh_session() -> tuple[AsyncEngine, AsyncSession]:
    """Open an independent async session that commits for real."""
    engine = create_async_engine(get_test_database_url(), poolclass=NullPool)
    maker = async_sessionmaker(engine, expire_on_commit=False)
    return engine, maker()


async def _thread(db: AsyncSession, *, user_id: int, title: str, queue_position: int) -> Thread:
    thread = Thread(
        title=title,
        format="comic",
        issues_remaining=0,
        queue_position=queue_position,
        status="active",
        user_id=user_id,
        total_issues=0,
        reading_progress="not_started",
        created_at=datetime.now(UTC),
    )
    db.add(thread)
    await db.flush()
    return thread


async def _issue(db: AsyncSession, *, thread: Thread, issue_number: str, position: int) -> Issue:
    issue = Issue(
        thread_id=thread.id,
        issue_number=issue_number,
        position=position,
        status="unread",
    )
    db.add(issue)
    await db.flush()
    thread.total_issues = (thread.total_issues or 0) + 1
    thread.issues_remaining = (thread.issues_remaining or 0) + 1
    return issue


async def _identity(db: AsyncSession, *, entity_type: str, external_id: str) -> ExternalIdentity:
    identity = ExternalIdentity(
        provider="comicvine",
        entity_type=entity_type,
        external_id=external_id,
        metadata_json={},
    )
    db.add(identity)
    await db.flush()
    return identity


async def _seed_list(
    db: AsyncSession,
    *,
    user_id: int,
    tag: str,
    include_missing: bool = True,
) -> tuple[CBLSourceList, Issue]:
    """Seed one owned issue plus an optional missing importable CBL entry."""
    source = CBLSource(
        repository=f"JoshCLWren/CBL-ReadingLists-{tag}",
        revision_sha=f"rev-{tag}",
        synced_at=datetime.now(UTC),
    )
    db.add(source)
    await db.flush()
    source_list = CBLSourceList(
        source_id=source.id,
        source_path=f"Fixtures/Idempotency {tag}.cbl",
        name=f"Idempotency {tag}",
        declared_issue_count=2 if include_missing else 1,
        content_hash=f"hash-{tag}",
        revision_sha=f"rev-{tag}",
        active=True,
    )
    db.add(source_list)
    await db.flush()

    owned_thread = await _thread(
        db, user_id=user_id, title=f"Owned {tag}", queue_position=1
    )
    owned_issue = await _issue(db, thread=owned_thread, issue_number="1", position=1)
    owned_identity = await _identity(db, entity_type="issue", external_id=f"4000-owned-{tag}")
    db.add(
        IssueExternalIdentityMapping(
            issue_id=owned_issue.id,
            external_identity_id=owned_identity.id,
            status="confirmed",
            evidence_source="idempotency",
        )
    )
    db.add(
        CBLSourceEntry(
            list_id=source_list.id,
            position=1,
            series_name=f"Owned {tag}",
            issue_number="1",
            external_issue_identity_id=owned_identity.id,
        )
    )
    if include_missing:
        missing_identity = await _identity(
            db,
            entity_type="issue",
            external_id=f"4000-missing-{tag}",
        )
        missing_identity.metadata_json = {
            "volume": {"name": f"Missing {tag}", "start_year": 2001},
        }
        db.add(
            CBLSourceEntry(
                list_id=source_list.id,
                position=2,
                series_name=f"Missing {tag}",
                issue_number="1",
                volume_year=2001,
                external_issue_identity_id=missing_identity.id,
            )
        )
    await db.commit()
    return source_list, owned_issue


async def _cleanup(
    db: AsyncSession,
    *,
    user_id: int,
    list_id: int,
    source_id: int,
) -> None:
    """Remove rows this module committed so later tests stay isolated."""
    plan_ids = list(
        (
            await db.execute(
                select(CblAdoptionReceipt.plan_id).where(CblAdoptionReceipt.user_id == user_id)
            )
        ).scalars().all()
    )
    extra_plan_ids = list(
        (
            await db.execute(select(ContinuityPlan.id).where(ContinuityPlan.user_id == user_id))
        ).scalars().all()
    )
    await db.execute(delete(CblAdoptionReceipt).where(CblAdoptionReceipt.user_id == user_id))
    if plan_ids or extra_plan_ids:
        await db.execute(
            delete(ContinuityPlan).where(
                ContinuityPlan.id.in_([*plan_ids, *extra_plan_ids])
            )
        )
    await db.execute(delete(CBLSourceEntry).where(CBLSourceEntry.list_id == list_id))
    await db.execute(delete(CBLSourceList).where(CBLSourceList.id == list_id))
    await db.execute(delete(CBLSource).where(CBLSource.id == source_id))
    thread_ids = list(
        (await db.execute(select(Thread.id).where(Thread.user_id == user_id))).scalars().all()
    )
    if thread_ids:
        await db.execute(delete(Issue).where(Issue.thread_id.in_(thread_ids)))
        await db.execute(delete(Thread).where(Thread.id.in_(thread_ids)))
    await db.execute(delete(User).where(User.id == user_id))
    await db.commit()


@pytest.mark.asyncio
async def test_retry_after_lost_response_reuses_plan_and_issues(
    auth_client: AsyncClient,
    async_db: AsyncSession,
) -> None:
    """A second commit after a lost 201 returns the same plan and creates no comics."""
    user = await get_or_create_user_async(async_db)
    tag = f"lost-{_suffix()}"
    source_list, _owned = await _seed_list(async_db, user_id=user.id, tag=tag)
    issues_before = await async_db.scalar(select(func.count()).select_from(Issue))

    payload = {
        "entry_decisions": {},
        "series_decisions": [],
        "series_overrides": [],
        "content_hash": source_list.content_hash,
        "revision_sha": source_list.revision_sha,
    }
    first = await auth_client.post(
        f"/api/v1/cbl/{source_list.id}/adoption-commit",
        json=payload,
    )
    assert first.status_code == 201, first.text
    first_body = first.json()
    # The client never received this 201; it retries the same request.
    retry = await auth_client.post(
        f"/api/v1/cbl/{source_list.id}/adoption-commit",
        json=payload,
    )
    assert retry.status_code == 201, retry.text
    retry_body = retry.json()
    assert retry_body["id"] == first_body["id"]
    assert retry_body["created_positions"] == []
    assert len(retry_body["nodes"]) == len(first_body["nodes"])
    assert await async_db.scalar(
        select(func.count()).select_from(ContinuityPlan).where(ContinuityPlan.user_id == user.id)
    ) == 1
    assert await async_db.scalar(select(func.count()).select_from(Issue)) == (issues_before or 0) + 1
    receipt_count = await async_db.scalar(
        select(func.count())
        .select_from(CblAdoptionReceipt)
        .where(
            CblAdoptionReceipt.user_id == user.id,
            CblAdoptionReceipt.cbl_source_list_id == source_list.id,
        )
    )
    assert receipt_count == 1


@pytest.mark.asyncio
async def test_owned_entry_excluded_individually(
    auth_client: AsyncClient,
    async_db: AsyncSession,
) -> None:
    """Unchecking Include on one owned issue leaves it out of the plan, in the library."""
    user = await get_or_create_user_async(async_db)
    tag = f"exclude-{_suffix()}"
    source_list, owned_issue = await _seed_list(async_db, user_id=user.id, tag=tag)
    issues_before = await async_db.scalar(select(func.count()).select_from(Issue))

    commit = await auth_client.post(
        f"/api/v1/cbl/{source_list.id}/adoption-commit",
        json={
            "entry_decisions": {},
            "series_decisions": [],
            "series_overrides": [{"cbl_position": 1, "decision": "exclude"}],
            "content_hash": source_list.content_hash,
            "revision_sha": source_list.revision_sha,
        },
    )
    assert commit.status_code == 201, commit.text
    body = commit.json()
    assert body["excluded_positions"] == [1]
    issue_refs = [node["ref_id"] for node in body["nodes"] if node["node_type"] == "issue"]
    assert owned_issue.id not in issue_refs
    assert len(issue_refs) == 1
    assert await async_db.get(Issue, owned_issue.id) is not None
    assert await async_db.scalar(select(func.count()).select_from(Issue)) == (issues_before or 0) + 1


@pytest.mark.asyncio
async def test_concurrent_double_submit_creates_one_plan(db_engine: AsyncEngine) -> None:
    """Two overlapping adoption-commits for the same user and list create one plan.

    Independent connections are required: the function-scoped async_db fixture
    holds TRUNCATE locks that would serialize the racers.
    """
    del db_engine
    tag = f"race-{_suffix()}"
    setup_engine, setup = await _fresh_session()
    try:
        username = f"cbl_race_{tag}"
        user = User(username=username, email=f"{username}@example.com", password_hash="x")
        setup.add(user)
        await setup.flush()
        source_list, _owned = await _seed_list(setup, user_id=user.id, tag=tag)
        user_id = user.id
        list_id = source_list.id
        source_id = source_list.source_id
        content_hash = source_list.content_hash
        revision_sha = source_list.revision_sha
    finally:
        await setup.close()
        await setup_engine.dispose()

    async def attempt() -> int:
        engine, session = await _fresh_session()
        try:
            result = await adopt_cbl_material_into_reading_plan(
                session,
                user_id=user_id,
                list_id=list_id,
                entry_decisions={},
                series_decisions={},
                client_content_hash=content_hash,
                client_revision_sha=revision_sha,
            )
            return result.plan.id
        finally:
            await session.close()
            await engine.dispose()

    check_engine, check = await _fresh_session()
    try:
        plan_ids = await asyncio.gather(attempt(), attempt())
        assert plan_ids[0] == plan_ids[1]
        assert plan_ids[0] > 0
        plan_count = await check.scalar(
            select(func.count())
            .select_from(ContinuityPlan)
            .where(ContinuityPlan.user_id == user_id)
        )
        assert plan_count == 1
        receipt_count = await check.scalar(
            select(func.count())
            .select_from(CblAdoptionReceipt)
            .where(
                CblAdoptionReceipt.user_id == user_id,
                CblAdoptionReceipt.cbl_source_list_id == list_id,
            )
        )
        assert receipt_count == 1
        issue_count = await check.scalar(
            select(func.count())
            .select_from(Issue)
            .join(Thread, Thread.id == Issue.thread_id)
            .where(Thread.user_id == user_id)
        )
        assert issue_count == 2
    finally:
        await _cleanup(check, user_id=user_id, list_id=list_id, source_id=source_id)
        await check.close()
        await check_engine.dispose()
