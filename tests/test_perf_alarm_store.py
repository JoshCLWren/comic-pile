"""Tests for durable performance-alarm counters and filing claims."""

from datetime import UTC, date, datetime, timedelta

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from app.repositories import perf_alarm_repository as repo
from app.services.perf_alarm_store import InMemoryPerfAlarmStore, PostgresPerfAlarmStore

pytestmark = pytest.mark.asyncio


async def test_in_memory_increment_is_shared() -> None:
    """Two evaluators incrementing the same store share one daily count."""
    store = InMemoryPerfAlarmStore()
    day = date(2026, 10, 12)

    assert await store.increment_daily_hit("fp-share", day) == 1
    assert await store.increment_daily_hit("fp-share", day) == 2
    assert await store.increment_daily_hit("fp-share", day) == 3


async def test_in_memory_mark_closed_resets_daily_hits() -> None:
    """Closing an incident clears the UTC-day counter so regressions need N."""
    store = InMemoryPerfAlarmStore()
    day = date(2026, 10, 12)
    await store.increment_daily_hit("fp-close", day)
    await store.increment_daily_hit("fp-close", day)
    await store.mark_open("fp-close", 10)
    await store.mark_closed("fp-close", 10)

    assert await store.get_open_issue("fp-close") is None
    assert await store.get_closed_issue("fp-close") == 10
    assert await store.increment_daily_hit("fp-close", day) == 1


async def test_in_memory_filing_claim_is_exclusive() -> None:
    """Only one caller wins the filing claim for a fingerprint."""
    store = InMemoryPerfAlarmStore()
    now = datetime(2026, 10, 12, 12, 0, tzinfo=UTC)

    assert await store.try_claim_filing("fp-claim", now=now) is True
    assert await store.try_claim_filing("fp-claim", now=now) is False
    later = now + timedelta(minutes=6)
    assert await store.try_claim_filing("fp-claim", now=later) is True


async def test_in_memory_comment_claim_throttles_for_an_hour() -> None:
    """A second comment claim within an hour is rejected."""
    store = InMemoryPerfAlarmStore()
    now = datetime(2026, 10, 12, 12, 0, tzinfo=UTC)

    assert await store.try_claim_comment("fp-comment", now=now) is True
    assert await store.try_claim_comment("fp-comment", now=now + timedelta(minutes=59)) is False
    assert await store.try_claim_comment("fp-comment", now=now + timedelta(hours=1)) is True


async def test_postgres_increment_is_atomic(async_db: AsyncSession) -> None:
    """Postgres upsert returns the incremented daily hit count."""
    store = PostgresPerfAlarmStore(async_db)
    day = date(2026, 10, 12)

    assert await store.increment_daily_hit("fp-pg", day) == 1
    await store.commit()
    assert await store.increment_daily_hit("fp-pg", day) == 2
    await store.commit()
    assert await repo.increment_daily_hit(
        async_db, fingerprint="fp-pg", utc_day=day
    ) == 3
    await async_db.commit()


async def test_postgres_filing_claim_rejects_concurrent_second(
    async_db: AsyncSession,
) -> None:
    """A second claim on the same fingerprint does not win while the first is live."""
    store = PostgresPerfAlarmStore(async_db)
    now = datetime(2026, 10, 12, 12, 0, tzinfo=UTC)

    assert await store.try_claim_filing("fp-pg-claim", now=now) is True
    await store.commit()
    assert await store.try_claim_filing("fp-pg-claim", now=now) is False
    await store.commit()


async def test_postgres_mark_closed_resets_hits(async_db: AsyncSession) -> None:
    """Closing an incident deletes that fingerprint's daily counter rows."""
    store = PostgresPerfAlarmStore(async_db)
    day = date(2026, 10, 12)
    await store.increment_daily_hit("fp-pg-close", day)
    await store.increment_daily_hit("fp-pg-close", day)
    await store.mark_open("fp-pg-close", 42)
    await store.commit()
    await store.mark_closed("fp-pg-close", 42)
    await store.commit()

    assert await store.get_open_issue("fp-pg-close") is None
    assert await store.get_closed_issue("fp-pg-close") == 42
    assert await store.increment_daily_hit("fp-pg-close", day) == 1
    await store.commit()
