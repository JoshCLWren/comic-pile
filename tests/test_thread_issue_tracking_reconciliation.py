"""Tests for the #2191 thread issue-tracking reconciliation pass.

The pass re-derives ``total_issues``/``issues_remaining``/
``next_unread_issue_id``/``reading_progress`` from the issue rows a thread
actually owns. It must repair drifted counters without creating or deleting
issue rows and without mutating read history (status, ``read_at``, ratings).
"""

from __future__ import annotations

from datetime import UTC, datetime

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import Issue, Thread
from app.services.thread_issue_tracking_reconciliation import (
    reconcile_thread_issue_tracking,
)
from tests.conftest import get_or_create_user_async


@pytest.mark.asyncio
async def test_repairs_drifted_totals_without_mutating_read_history(
    async_db: AsyncSession,
) -> None:
    """Committed pass fixes counters, keeps rows, and preserves read history."""
    user = await get_or_create_user_async(async_db)

    inflated = Thread(
        title="Alpha Flight (1997)",
        format="Comic",
        issues_remaining=20,
        queue_position=1,
        status="active",
        user_id=user.id,
        total_issues=20,
        reading_progress="not_started",
        created_at=datetime.now(UTC),
    )
    async_db.add(inflated)
    await async_db.flush()
    adopted = Issue(thread_id=inflated.id, issue_number="9", position=1, status="unread")
    async_db.add(adopted)
    await async_db.flush()

    read_at = datetime.now(UTC)
    preserved = Thread(
        title="Wolverine (2005)",
        format="Comic",
        issues_remaining=28,
        queue_position=2,
        status="active",
        user_id=user.id,
        total_issues=28,
        reading_progress="in_progress",
        created_at=datetime.now(UTC),
    )
    async_db.add(preserved)
    await async_db.flush()
    read_rows = [
        Issue(
            thread_id=preserved.id,
            issue_number="850",
            position=1,
            status="read",
            read_at=read_at,
        ),
        Issue(thread_id=preserved.id, issue_number="900", position=2, status="unread"),
        Issue(
            thread_id=preserved.id,
            issue_number="901",
            position=3,
            status="read",
            read_at=read_at,
        ),
    ]
    for row in read_rows:
        async_db.add(row)
    await async_db.flush()
    preserved.next_unread_issue_id = read_rows[1].id
    await async_db.commit()

    report = await reconcile_thread_issue_tracking(async_db, user_id=user.id, commit=True)

    assert report.scanned == 2
    assert report.repaired == 2
    assert report.committed is True

    await async_db.refresh(inflated)
    assert inflated.total_issues == 1
    assert inflated.issues_remaining == 1
    assert inflated.next_unread_issue_id == adopted.id
    assert inflated.reading_progress == "not_started"
    assert inflated.status == "active"

    await async_db.refresh(preserved)
    assert preserved.total_issues == 3
    assert preserved.issues_remaining == 1
    assert preserved.next_unread_issue_id == read_rows[1].id
    assert preserved.reading_progress == "in_progress"

    result = await async_db.execute(
        select(Issue).where(Issue.thread_id == preserved.id).order_by(Issue.position)
    )
    rows = result.scalars().all()
    assert len(rows) == 3
    assert [row.issue_number for row in rows] == ["850", "900", "901"]
    assert rows[0].read_at == read_at
    assert rows[2].read_at == read_at


@pytest.mark.asyncio
async def test_dry_run_reports_repairs_without_persisting(async_db: AsyncSession) -> None:
    """A non-committed pass reports the planned repair but changes no rows."""
    user = await get_or_create_user_async(async_db)

    thread = Thread(
        title="Drifted",
        format="Comic",
        issues_remaining=20,
        queue_position=1,
        status="active",
        user_id=user.id,
        total_issues=20,
        reading_progress="not_started",
        created_at=datetime.now(UTC),
    )
    async_db.add(thread)
    await async_db.flush()
    issue = Issue(thread_id=thread.id, issue_number="9", position=1, status="unread")
    async_db.add(issue)
    await async_db.commit()

    report = await reconcile_thread_issue_tracking(async_db, user_id=user.id, commit=False)

    assert report.scanned == 1
    assert report.repaired == 1
    assert report.committed is False
    assert report.repairs[0].thread_id == thread.id
    assert report.repairs[0].total_issues_before == 20
    assert report.repairs[0].total_issues_after == 1
    assert report.repairs[0].issues_remaining_after == 1
    assert report.repairs[0].next_unread_issue_id_after == issue.id

    await async_db.refresh(thread)
    assert thread.total_issues == 20
    assert thread.issues_remaining == 20
    assert thread.next_unread_issue_id is None
    assert thread.reading_progress == "not_started"


@pytest.mark.asyncio
async def test_already_consistent_thread_is_not_repairable(async_db: AsyncSession) -> None:
    """A thread whose counters already match its rows is not reported."""
    user = await get_or_create_user_async(async_db)

    thread = Thread(
        title="Consistent",
        format="Comic",
        issues_remaining=1,
        queue_position=1,
        status="active",
        user_id=user.id,
        total_issues=1,
        reading_progress="not_started",
        created_at=datetime.now(UTC),
    )
    async_db.add(thread)
    await async_db.flush()
    issue = Issue(thread_id=thread.id, issue_number="9", position=1, status="unread")
    async_db.add(issue)
    await async_db.flush()
    thread.next_unread_issue_id = issue.id
    await async_db.commit()

    report = await reconcile_thread_issue_tracking(async_db, user_id=user.id, commit=True)

    assert report.scanned == 0
    assert report.repaired == 0
    assert report.committed is True
    assert report.repairs == ()


@pytest.mark.asyncio
async def test_unmigrated_counter_thread_is_not_migrated(async_db: AsyncSession) -> None:
    """The pass leaves old counter-based threads untouched."""
    user = await get_or_create_user_async(async_db)

    thread = Thread(
        title="Counter Based",
        format="Comic",
        queue_position=1,
        status="active",
        user_id=user.id,
        total_issues=None,
        reading_progress=None,
        created_at=datetime.now(UTC),
    )
    async_db.add(thread)
    await async_db.flush()
    issue = Issue(thread_id=thread.id, issue_number="9", position=1, status="unread")
    async_db.add(issue)
    await async_db.commit()

    report = await reconcile_thread_issue_tracking(async_db, user_id=user.id, commit=True)

    assert report.scanned == 0
    assert report.repaired == 0

    await async_db.refresh(thread)
    assert thread.total_issues is None
    assert thread.reading_progress is None