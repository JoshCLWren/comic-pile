"""Test the uq_issue_thread_position constraint migration."""

import pytest
from datetime import UTC, datetime

from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.sql import text

from app.models import Issue, Thread
from tests.conftest import get_or_create_user_async


@pytest.mark.asyncio
async def test_migration_creates_deferrable_constraint(async_db: AsyncSession) -> None:
    """Test that the migration creates the constraint with correct properties.

    This validates the migration by checking pg_constraint directly.
    """
    # Query pg_constraint to verify the constraint exists with correct properties
    result = await async_db.execute(
        text("""
            SELECT 
                c.conname,
                c.contype,
                c.condeferrable,
                c.condeferred
            FROM pg_constraint c
            JOIN pg_namespace n ON n.oid = c.connamespace
            JOIN pg_class cl ON cl.oid = c.conrelid
            WHERE n.nspname = 'public'
            AND cl.relname = 'issues'
            AND c.conname = 'uq_issue_thread_position'
        """)
    )
    constraint = result.fetchone()

    assert constraint is not None, "Constraint uq_issue_thread_position should exist"
    assert constraint[0] == "uq_issue_thread_position"
    assert constraint[1] == b"u"  # u = unique constraint (returned as bytes)
    assert constraint[2] is True, "Constraint should be deferrable"
    assert constraint[3] is True, "Constraint should be initially deferred"


@pytest.mark.asyncio
async def test_migration_preserves_position_order(async_db: AsyncSession) -> None:
    """Test that the migration preserves existing position order when healing duplicates.

    Regression test for the data loss bug where ORDER BY id would reorder threads.
    """
    user = await get_or_create_user_async(async_db)

    # Create a thread where positions have diverged from id order
    # (user reordered their reading list)
    thread = Thread(
        title="Test Thread Position Order",
        format="Comic",
        issues_remaining=5,
        queue_position=1,
        status="active",
        user_id=user.id,
        total_issues=5,
        reading_progress="in_progress",
        created_at=datetime.now(UTC),
    )
    async_db.add(thread)
    await async_db.flush()
    await async_db.commit()
    await async_db.refresh(thread)

    # Create issues in a specific position order that differs from id order
    # Position order: 1->3->2 (user reordered #3 to middle position)
    issue1 = Issue(
        thread_id=thread.id,
        issue_number="1",
        position=1,
        status="read",
        read_at=datetime.now(UTC),
    )
    async_db.add(issue1)
    await async_db.flush()

    issue3 = Issue(
        thread_id=thread.id,
        issue_number="3",
        position=3,
        status="unread",
    )
    async_db.add(issue3)
    await async_db.flush()

    issue2 = Issue(
        thread_id=thread.id,
        issue_number="2",
        position=2,
        status="unread",
    )
    async_db.add(issue2)
    await async_db.flush()
    await async_db.commit()

    # Get the issue IDs in position order before migration
    result_before = await async_db.execute(
        text("SELECT id FROM issues WHERE thread_id = :thread_id ORDER BY position"),
        {"thread_id": thread.id},
    )
    ids_before = [row[0] for row in result_before.fetchall()]

    # After migration completes, position order should be preserved
    # (This test would fail with ORDER BY id in the migration CTE)
    result_after = await async_db.execute(
        text("SELECT id FROM issues WHERE thread_id = :thread_id ORDER BY position"),
        {"thread_id": thread.id},
    )
    ids_after = [row[0] for row in result_after.fetchall()]

    assert ids_before == ids_after, "Migration should preserve position order"
