"""Tests for the production E2E data janitor."""

from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker

import scripts.cleanup_production_e2e_data as cleanup_module
from app.models.thread import Thread
from app.models.user import User
from scripts.cleanup_production_e2e_data import (
    cleanup_stale_threads,
    is_managed_e2e_title,
)


@pytest.mark.parametrize(
    ("title", "expected"),
    [
        ("[E2E] 12345-1 queue smoke", True),
        ("[E2E] run_20260806 thread edit", True),
        ("[E2E] run.with-dots dependency test", True),
        ("[E2E] missing-description", False),
        ("[E2E]  queue smoke", False),
        ("[e2e] 123 queue smoke", False),
        ("Josh's real thread", False),
        ("prefix [E2E] 123 queue smoke", False),
        ("[E2E] 123", False),
    ],
)
def test_is_managed_e2e_title_requires_strict_prefix_and_run_id(
    title: str,
    expected: bool,
) -> None:
    """Only unmistakably automation-owned titles are cleanup candidates."""
    assert is_managed_e2e_title(title) is expected


@pytest.mark.asyncio
async def test_cleanup_rejects_empty_account_before_database_access() -> None:
    """Cleanup cannot run without an exact dedicated-account boundary."""
    with pytest.raises(ValueError, match="account_email must not be empty"):
        await cleanup_stale_threads(account_email="   ")


@pytest.mark.asyncio
@pytest.mark.parametrize("max_age_hours", [0, -1])
async def test_cleanup_rejects_nonpositive_age_before_database_access(
    max_age_hours: int,
) -> None:
    """Cleanup cannot erase active or newly-created test records."""
    with pytest.raises(ValueError, match="max_age_hours must be at least 1"):
        await cleanup_stale_threads(
            account_email="automation@example.com",
            max_age_hours=max_age_hours,
        )


def _thread(
    *,
    title: str,
    user_id: int,
    created_at: datetime,
    queue_position: int,
    is_test: bool = True,
) -> Thread:
    """Build a minimal persisted thread for janitor boundary tests."""
    return Thread(
        title=title,
        format="series",
        issues_remaining=0,
        queue_position=queue_position,
        is_test=is_test,
        created_at=created_at,
        user_id=user_id,
    )


@pytest.mark.asyncio
async def test_cleanup_deletes_only_owned_stale_managed_test_threads(
    db_engine: AsyncEngine,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Ownership, age, test flag, and title format all gate destructive cleanup."""
    session_factory = async_sessionmaker(db_engine, expire_on_commit=False)
    monkeypatch.setattr(cleanup_module, "AsyncSessionLocal", session_factory)
    now = datetime(2026, 8, 6, 14, 0, tzinfo=UTC)

    async with session_factory() as session:
        owner = User(username="janitor-owner", email="automation@example.com")
        other = User(username="janitor-other", email="other@example.com")
        session.add_all([owner, other])
        await session.flush()
        candidates = [
            _thread(
                title="[E2E] run-1 delete me",
                user_id=owner.id,
                created_at=now - timedelta(hours=25),
                queue_position=1,
            ),
            _thread(
                title="[E2E] run-2 other account",
                user_id=other.id,
                created_at=now - timedelta(hours=25),
                queue_position=2,
            ),
            _thread(
                title="[E2E] run-3 ordinary flag",
                user_id=owner.id,
                created_at=now - timedelta(hours=25),
                queue_position=3,
                is_test=False,
            ),
            _thread(
                title="ordinary title",
                user_id=owner.id,
                created_at=now - timedelta(hours=25),
                queue_position=4,
            ),
            _thread(
                title="[E2E] run-5 exact boundary",
                user_id=owner.id,
                created_at=now - timedelta(hours=24),
                queue_position=5,
            ),
            _thread(
                title="[E2E] run-6 recent",
                user_id=owner.id,
                created_at=now - timedelta(hours=23),
                queue_position=6,
            ),
        ]
        session.add_all(candidates)
        await session.commit()

    result = await cleanup_stale_threads(
        account_email="AUTOMATION@example.com",
        max_age_hours=24,
        now=now,
    )

    assert result.account_found is True
    assert result.deleted_count == 1
    assert result.dry_run is False
    async with session_factory() as session:
        remaining_titles = set((await session.scalars(select(Thread.title))).all())
    assert remaining_titles == {
        "[E2E] run-2 other account",
        "[E2E] run-3 ordinary flag",
        "ordinary title",
        "[E2E] run-5 exact boundary",
        "[E2E] run-6 recent",
    }


@pytest.mark.asyncio
async def test_cleanup_dry_run_reports_without_deleting(
    db_engine: AsyncEngine,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Dry-run mode counts eligible records but leaves them persisted."""
    session_factory = async_sessionmaker(db_engine, expire_on_commit=False)
    monkeypatch.setattr(cleanup_module, "AsyncSessionLocal", session_factory)
    now = datetime(2026, 8, 6, 14, 0, tzinfo=UTC)

    async with session_factory() as session:
        owner = User(username="janitor-dry-run", email="dry-run@example.com")
        session.add(owner)
        await session.flush()
        thread = _thread(
            title="[E2E] dry-run-1 retain me",
            user_id=owner.id,
            created_at=now - timedelta(hours=25),
            queue_position=1,
        )
        session.add(thread)
        await session.commit()
        thread_id = thread.id

    result = await cleanup_stale_threads(
        account_email="dry-run@example.com",
        max_age_hours=24,
        dry_run=True,
        now=now,
    )

    assert result.deleted_count == 1
    assert result.dry_run is True
    async with session_factory() as session:
        assert await session.get(Thread, thread_id) is not None
