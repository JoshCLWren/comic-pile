"""Regression coverage for owner-scoped, durable Option E collection exclusions."""

import asyncio
from datetime import UTC, datetime

import pytest
from httpx import AsyncClient
from pydantic import ValidationError
from sqlalchemy import delete, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker

from app.models import CollectionExclusion, Issue, Thread, User
from app.schemas.collection_exclusion import CollectionExclusionCreate
from app.services.collection_exclusion_service import create_collection_exclusion

pytestmark = pytest.mark.asyncio

BASE = "/api/v1/collection-exclusions"


async def test_volume_idempotent_normalized_and_persists_without_thread(
    auth_client: AsyncClient, async_db: AsyncSession, sample_data: dict[str, object]
) -> None:
    """An excluded external volume survives removal of its original Thread."""
    payload = {"provider": " ComicVine ", "external_volume_id": "4050-1234"}
    first = await auth_client.post(BASE, json=payload)
    assert first.status_code == 200, first.text
    assert first.json()["provider"] == "comicvine"
    second = await auth_client.post(BASE, json={
        "provider": "comicvine", "external_volume_id": "4050-1234"
    })
    assert second.status_code == 200
    assert second.json()["id"] == first.json()["id"]

    listing = await auth_client.get(BASE)
    assert listing.status_code == 200
    assert [item["id"] for item in listing.json()] == [first.json()["id"]]

    await async_db.execute(delete(Thread))
    await async_db.commit()
    listing = await auth_client.get(BASE)
    assert listing.status_code == 200
    assert listing.json()[0]["external_volume_id"] == "4050-1234"


@pytest.mark.parametrize("target", [{"thread_id": 1}, {"issue_id": 6}])
async def test_owned_local_target_roundtrip(
    auth_client: AsyncClient,
    sample_data: dict[str, object],
    target: dict[str, int],
) -> None:
    """Owners can exclude and remove their local Thread or Issue."""
    created = await auth_client.post(BASE, json=target)
    assert created.status_code == 200, created.text
    assert all(created.json()[key] == value for key, value in target.items())
    exclusion_id = created.json()["id"]
    assert (await auth_client.post(BASE, json=target)).json()["id"] == exclusion_id
    deleted = await auth_client.delete(f"{BASE}/{exclusion_id}")
    assert deleted.status_code == 204
    assert (await auth_client.delete(f"{BASE}/{exclusion_id}")).status_code == 404
    assert (await auth_client.get(BASE)).json() == []


async def test_other_users_targets_not_available(
    auth_client: AsyncClient,
    async_db: AsyncSession,
    sample_data: dict[str, object],
) -> None:
    """Reject cross-user Thread/Issue writes and hide foreign exclusion IDs."""
    other = User(username="exclusions_foreign", created_at=datetime.now(UTC))
    async_db.add(other)
    await async_db.flush()
    thread = Thread(
        title="Foreign Series", format="Comic", issues_remaining=1,
        queue_position=50, user_id=other.id, status="active",
    )
    async_db.add(thread)
    await async_db.flush()
    issue = Issue(thread_id=thread.id, issue_number="1", position=1, status="unread")
    async_db.add(issue)
    await async_db.flush()
    for payload in ({"thread_id": thread.id}, {"issue_id": issue.id}):
        response = await auth_client.post(BASE, json=payload)
        assert response.status_code == 404
    foreign_row = CollectionExclusion(user_id=other.id, thread_id=thread.id)
    async_db.add(foreign_row)
    await async_db.commit()
    assert (await auth_client.get(BASE)).json() == []
    assert (await auth_client.delete(f"{BASE}/{foreign_row.id}")).status_code == 404
    assert (await async_db.scalar(select(CollectionExclusion).where(
        CollectionExclusion.id == foreign_row.id
    ))) is not None


@pytest.mark.parametrize(
    "payload",
    [
        {},
        {"thread_id": 1, "issue_id": 2},
        {"thread_id": 0},
        {"issue_id": -1},
        {"provider": "comicvine"},
        {"external_volume_id": "4050-1234"},
        {"provider": "", "external_volume_id": "4050-1234"},
        {"provider": "comicvine", "external_volume_id": "   "},
        {"provider": "comicvine", "external_volume_id": "4050-1234", "issue_id": 1},
    ],
)
async def test_invalid_targets_rejected(
    auth_client: AsyncClient, sample_data: dict[str, object], payload: dict[str, object]
) -> None:
    """Malformed or multiple target kinds never create a row."""
    assert (await auth_client.post(BASE, json=payload)).status_code == 422
    assert (await auth_client.get(BASE)).json() == []


async def test_missing_local_targets_are_not_permitted(
    auth_client: AsyncClient, sample_data: dict[str, object]
) -> None:
    """Only external identities may be excluded before materialization."""
    assert (await auth_client.post(BASE, json={"thread_id": 999999})).status_code == 404
    assert (await auth_client.post(BASE, json={"issue_id": 999999})).status_code == 404


async def test_database_exactly_one_target_constraint(
    async_db: AsyncSession, sample_data: dict[str, object]
) -> None:
    """Database enforcement remains effective for writers bypassing Pydantic."""
    with pytest.raises(IntegrityError):
        async with async_db.begin_nested():
            async_db.add(CollectionExclusion(user_id=1, thread_id=1, issue_id=6))
            await async_db.flush()
    with pytest.raises(IntegrityError):
        async with async_db.begin_nested():
            async_db.add(CollectionExclusion(user_id=1, external_volume_id="4050-1"))
            await async_db.flush()


async def test_payload_validation_without_database() -> None:
    """Validate the public exactly-one-target contract independently of FastAPI."""
    with pytest.raises(ValidationError):
        CollectionExclusionCreate(thread_id=1, issue_id=2)
    with pytest.raises(ValidationError):
        CollectionExclusionCreate(provider="comicvine", external_volume_id=" ")


async def test_concurrent_identical_volume_requests_share_one_record(
    db_engine: AsyncEngine,
) -> None:
    """Independent transactions contend on the unique index and both return one ID."""
    factory = async_sessionmaker(db_engine, expire_on_commit=False)
    async with factory() as seed:
        owner = User(username="exclusions_concurrent", created_at=datetime.now(UTC))
        seed.add(owner)
        await seed.commit()
        user_id = owner.id

    async def create_one() -> int:
        async with factory() as session:
            result = await create_collection_exclusion(
                session,
                user_id=user_id,
                payload=CollectionExclusionCreate(
                    provider="comicvine", external_volume_id="4050-90001"
                ),
            )
            return result.id

    try:
        first_id, second_id = await asyncio.gather(create_one(), create_one())
        assert first_id == second_id
        async with factory() as check:
            records = await check.scalars(
                select(CollectionExclusion).where(CollectionExclusion.user_id == user_id)
            )
            assert [record.id for record in records] == [first_id]
    finally:
        async with factory() as cleanup:
            owner = await cleanup.get(User, user_id)
            if owner is not None:
                await cleanup.delete(owner)
            await cleanup.commit()


async def test_all_target_kinds_survive_deleted_thread_and_issue(
    auth_client: AsyncClient, async_db: AsyncSession, sample_data: dict[str, object]
) -> None:
    """Durable exclusions outlive both the target issue and parent Thread."""
    targets = (
        {"provider": "comicvine", "external_volume_id": "4050-777"},
        {"thread_id": 2},
        {"issue_id": 6},
    )
    recorded = []
    for target in targets:
        response = await auth_client.post(BASE, json=target)
        assert response.status_code == 200, response.text
        recorded.append(response.json())

    await async_db.execute(delete(Issue).where(Issue.id == 6))
    await async_db.commit()
    before_thread_delete = (await auth_client.get(BASE)).json()
    assert before_thread_delete == recorded

    await async_db.execute(delete(Thread).where(Thread.id == 2))
    await async_db.commit()
    after_thread_delete = (await auth_client.get(BASE)).json()
    assert after_thread_delete == recorded
    assert len({row["id"] for row in after_thread_delete}) == 3
