"""PostgreSQL transaction coverage for reader-owned CBL source links."""

import asyncio
from datetime import UTC, datetime
from uuid import uuid4

import pytest
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker

from app.models.cbl_reference import CBLSource, CBLSourceList
from app.models.continuity_plan import ContinuityPlan
from app.models.custom_cbl import CustomCBLList
from app.models.custom_cbl_source_link import CustomCBLSourceLink
from app.models.user import User
from app.services.custom_cbl_source_link_service import ensure_first_add_link, get_owned_destination


async def _seed(db: AsyncSession) -> tuple[int, int, int]:
    """Persist two readers and one uniquely identified shared source."""
    token = uuid4().hex
    readers = [User(username=f"link-{token}-{i}", password_hash="unused") for i in range(2)]
    source = CBLSource(
        repository=f"test/{token}", revision_sha="a" * 40, synced_at=datetime.now(UTC)
    )
    db.add_all([*readers, source])
    await db.flush()
    listing = CBLSourceList(
        source_id=source.id,
        source_path="one.cbl",
        name="Same title",
        revision_sha="a" * 40,
        content_hash="b" * 64,
    )
    db.add(listing)
    await db.flush()
    result = (readers[0].id, readers[1].id, listing.id)
    await db.commit()
    return result


async def _counts(db: AsyncSession, user_id: int) -> tuple[int, int]:
    """Count both destination lists and durable links for one reader."""
    lists = await db.scalar(
        select(func.count()).select_from(CustomCBLList).where(CustomCBLList.user_id == user_id)
    )
    links = await db.scalar(
        select(func.count())
        .select_from(CustomCBLSourceLink)
        .where(CustomCBLSourceLink.user_id == user_id)
    )
    return int(lists or 0), int(links or 0)


@pytest.mark.asyncio
async def test_repeat_reopen_and_separate_readers(async_db_committed: AsyncSession) -> None:
    """Retries retain IDs and provenance while different readers stay isolated."""
    db = async_db_committed
    first, second, source_id = await _seed(db)
    original = await ensure_first_add_link(db, user_id=first, cbl_source_list_id=source_id)
    original_id = original.owned_list.id
    await db.commit()
    db.expunge_all()
    repeated = await ensure_first_add_link(db, user_id=first, cbl_source_list_id=source_id)
    assert repeated.owned_list.id == original_id
    assert repeated.link.source_content_hash == "b" * 64
    other = await ensure_first_add_link(db, user_id=second, cbl_source_list_id=source_id)
    assert other.owned_list.id != original_id
    assert other.owned_list.user_id == second
    assert await _counts(db, first) == (1, 1)
    assert await _counts(db, second) == (1, 1)
    await db.commit()
    reopened = await get_owned_destination(db, user_id=first, cbl_source_list_id=source_id)
    assert reopened.owned_list.id == original_id


@pytest.mark.asyncio
async def test_caller_rollback_removes_list_and_link(async_db_committed: AsyncSession) -> None:
    """Releasing the helper savepoint never commits the caller transaction."""
    db = async_db_committed
    first, _, source_id = await _seed(db)
    await ensure_first_add_link(db, user_id=first, cbl_source_list_id=source_id)
    assert await _counts(db, first) == (1, 1)
    await db.rollback()
    assert await _counts(db, first) == (0, 0)
    retry = await ensure_first_add_link(db, user_id=first, cbl_source_list_id=source_id)
    assert retry.owned_list.user_id == first
    assert await _counts(db, first) == (1, 1)


@pytest.mark.asyncio
async def test_concurrent_first_add_converges(
    async_db_committed: AsyncSession,
    db_engine: AsyncEngine,
) -> None:
    """Independent overlapping transactions create exactly one owned destination."""
    first, _, source_id = await _seed(async_db_committed)
    sessions = async_sessionmaker(db_engine, expire_on_commit=False)
    locked = asyncio.Event()
    contender_started = asyncio.Event()

    async def winner() -> int:
        async with sessions() as db:
            result = await ensure_first_add_link(db, user_id=first, cbl_source_list_id=source_id)
            locked.set()
            await contender_started.wait()
            await db.commit()
            return result.owned_list.id

    async def contender() -> int:
        await locked.wait()
        async with sessions() as db:
            contender_started.set()
            result = await ensure_first_add_link(db, user_id=first, cbl_source_list_id=source_id)
            await db.commit()
            return result.owned_list.id

    ids = await asyncio.wait_for(asyncio.gather(winner(), contender()), timeout=15)
    assert ids[0] == ids[1]
    assert await _counts(async_db_committed, first) == (1, 1)


@pytest.mark.asyncio
async def test_same_names_never_alias(async_db_committed: AsyncSession) -> None:
    """Source identity, rather than title, selects an isolated destination."""
    db = async_db_committed
    first, _, source_id = await _seed(db)
    source = await db.get(CBLSourceList, source_id)
    assert source is not None
    plan = ContinuityPlan(
        user_id=first,
        name="Existing plan",
        nodes_json=[{"id": "retained", "status": "read", "rating": 5}],
    )
    db.add(plan)
    await db.flush()
    plan_id = plan.id
    manual = CustomCBLList(user_id=first, name="Same title", mode="loose")
    other_source = CBLSourceList(
        source_id=source.source_id,
        source_path="two.cbl",
        name=source.name,
        revision_sha=source.revision_sha,
        content_hash="c" * 64,
    )
    db.add_all([manual, other_source])
    await db.flush()
    manual_id = manual.id
    a = await ensure_first_add_link(db, user_id=first, cbl_source_list_id=source_id)
    b = await ensure_first_add_link(db, user_id=first, cbl_source_list_id=other_source.id)
    assert len({manual_id, a.owned_list.id, b.owned_list.id}) == 3
    assert manual.name == "Same title"
    assert await _counts(db, first) == (3, 2)

    await db.commit()
    db.expunge_all()
    preserved = await db.get(ContinuityPlan, plan_id)
    assert preserved is not None
    assert preserved.nodes_json == [{"id": "retained", "status": "read", "rating": 5}]
