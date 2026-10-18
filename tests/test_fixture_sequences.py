"""Fixture sequence synchronization must survive PostgreSQL transaction rollback."""

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from tests.conftest import _sync_id_sequence


async def test_sequence_sync_does_not_rewind_after_transactional_truncate(
    async_db: AsyncSession,
) -> None:
    """Rollback restores table rows but cannot undo a PostgreSQL setval call."""
    await async_db.execute(
        text("CREATE TEMP TABLE fixture_sequence_regression (id SERIAL PRIMARY KEY)")
    )
    await async_db.execute(
        text("INSERT INTO fixture_sequence_regression SELECT generate_series(1, 3)")
    )
    await _sync_id_sequence(async_db, "fixture_sequence_regression")
    savepoint = await async_db.begin_nested()
    await async_db.execute(text("TRUNCATE fixture_sequence_regression"))
    await _sync_id_sequence(async_db, "fixture_sequence_regression")
    await savepoint.rollback()
    inserted = await async_db.scalar(
        text("INSERT INTO fixture_sequence_regression DEFAULT VALUES RETURNING id")
    )
    assert inserted == 4
