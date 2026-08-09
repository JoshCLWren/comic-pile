"""Tests for disposable production E2E account cleanup."""

from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncEngine, async_sessionmaker

import scripts.cleanup_production_e2e_accounts as cleanup_module
from app.models.session import Session
from app.models.thread import Thread
from app.models.user import User
from scripts.cleanup_production_e2e_accounts import (
    cleanup_e2e_accounts,
    is_managed_e2e_account,
)


@pytest.mark.parametrize(
    ("username", "email", "expected"),
    [
        ("e2e_123_1", "comicpile-e2e+123.1@example.com", True),
        ("e2e_123_2", "comicpile-e2e+123.1@example.com", False),
        ("e2e_name_1", "comicpile-e2e+123.1@example.com", False),
        ("e2e_123_1", "reader@example.com", False),
        ("reader", "comicpile-e2e+123.1@example.com", False),
        ("e2e_123_1", None, False),
    ],
)
def test_is_managed_e2e_account_requires_matching_run_identifiers(
    username: str,
    email: str | None,
    expected: bool,
) -> None:
    """Both identifiers must encode the same run and attempt."""
    assert is_managed_e2e_account(username, email) is expected


@pytest.mark.asyncio
async def test_cleanup_rejects_unmanaged_exact_username() -> None:
    """Exact cleanup cannot target an ordinary account namespace."""
    with pytest.raises(ValueError, match="outside the managed E2E namespace"):
        await cleanup_e2e_accounts(account_username="reader")


@pytest.mark.asyncio
async def test_exact_cleanup_deletes_only_matching_empty_account(
    db_engine: AsyncEngine,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Current-run cleanup deletes one exact, empty disposable account."""
    session_factory = async_sessionmaker(db_engine, expire_on_commit=False)
    monkeypatch.setattr(cleanup_module, "AsyncSessionLocal", session_factory)
    async with session_factory() as session:
        managed = User(
            username="e2e_123_1",
            email="comicpile-e2e+123.1@example.com",
        )
        ordinary = User(username="reader", email="reader@example.com")
        session.add_all([managed, ordinary])
        await session.flush()
        session.add(Session(user_id=managed.id, start_die=6))
        await session.commit()

    result = await cleanup_e2e_accounts(account_username="e2e_123_1")

    assert result.candidate_count == 1
    assert result.deleted_count == 1
    assert result.refused_count == 0
    async with session_factory() as session:
        usernames = set((await session.scalars(select(User.username))).all())
        managed_sessions = list(
            (await session.scalars(select(Session).where(Session.user_id == managed.id))).all()
        )
    assert usernames == {"reader"}
    assert managed_sessions == []


@pytest.mark.asyncio
async def test_cleanup_refuses_account_with_application_data(
    db_engine: AsyncEngine,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A matching name is insufficient when the account owns a thread."""
    session_factory = async_sessionmaker(db_engine, expire_on_commit=False)
    monkeypatch.setattr(cleanup_module, "AsyncSessionLocal", session_factory)
    async with session_factory() as session:
        user = User(
            username="e2e_456_1",
            email="comicpile-e2e+456.1@example.com",
        )
        session.add(user)
        await session.flush()
        session.add(
            Thread(
                title="Never delete this account",
                format="series",
                issues_remaining=1,
                queue_position=1,
                user_id=user.id,
            )
        )
        await session.commit()

    result = await cleanup_e2e_accounts(account_username="e2e_456_1")

    assert result.deleted_count == 0
    assert result.refused_count == 1


@pytest.mark.asyncio
async def test_stale_cleanup_respects_age_and_dry_run(
    db_engine: AsyncEngine,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Interrupted accounts are eligible only after the stale cutoff."""
    session_factory = async_sessionmaker(db_engine, expire_on_commit=False)
    monkeypatch.setattr(cleanup_module, "AsyncSessionLocal", session_factory)
    now = datetime(2026, 8, 8, 18, 0, tzinfo=UTC)
    async with session_factory() as session:
        session.add_all(
            [
                User(
                    username="e2e_100_1",
                    email="comicpile-e2e+100.1@example.com",
                    created_at=now - timedelta(hours=25),
                ),
                User(
                    username="e2e_101_1",
                    email="comicpile-e2e+101.1@example.com",
                    created_at=now - timedelta(hours=23),
                ),
            ]
        )
        await session.commit()

    result = await cleanup_e2e_accounts(dry_run=True, now=now)

    assert result.candidate_count == 1
    assert result.deleted_count == 1
    assert result.dry_run is True
    async with session_factory() as session:
        remaining = set(
            (
                await session.scalars(
                    select(User.username).where(User.username.in_(["e2e_100_1", "e2e_101_1"]))
                )
            ).all()
        )
    assert remaining == {"e2e_100_1", "e2e_101_1"}
