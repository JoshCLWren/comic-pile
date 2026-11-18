"""Regression tests for #2191: thread totals reflect adopted issue rows only.

Selective CBL materialization previously copied the external series volume size
into ``total_issues``/``issues_remaining`` while a thread owned only a subset of
the adopted issue rows. These tests pin the row-derived contract: totals, the
remaining-unread count, and the next-unread pointer always come from the issue
rows a thread actually owns.
"""

from __future__ import annotations

from datetime import UTC, datetime

from sqlalchemy.ext.asyncio import AsyncSession

from app.models import Issue, Thread
from app.services.issue_tracking import derive_thread_issue_tracking_state


async def _declare_volume_thread(
    async_db: AsyncSession,
    *,
    user_id: int,
    title: str,
    external_total: int,
) -> Thread:
    """Create a thread carrying the external series size as its declared total.

    This mirrors the corrupted pre-fix materialization contract where the
    thread claimed to track the whole external volume while owning no rows yet.

    Args:
        async_db: Database session.
        user_id: Owning user id.
        title: Thread title.
        external_total: Declared external volume size.

    Returns:
        The persisted thread.
    """
    thread = Thread(
        title=title,
        format="Comic",
        issues_remaining=external_total,
        queue_position=1,
        status="active",
        user_id=user_id,
        total_issues=external_total,
        reading_progress="not_started",
        created_at=datetime.now(UTC),
    )
    async_db.add(thread)
    await async_db.commit()
    return thread










def test_derive_empty_issue_set_is_completed() -> None:
    """An issue set with no rows reports zero totals and completed progress."""
    state = derive_thread_issue_tracking_state([])
    assert state.total_issues == 0
    assert state.issues_remaining == 0
    assert state.next_unread_issue_id is None
    assert state.reading_progress == "completed"


def test_derive_partially_read_issue_set_is_in_progress() -> None:
    """A partially read set reports the earliest unread issue as next-unread."""
    issues = [
        Issue(id=1, thread_id=10, issue_number="1", position=1, status="read"),
        Issue(id=2, thread_id=10, issue_number="2", position=2, status="unread"),
        Issue(id=3, thread_id=10, issue_number="3", position=3, status="unread"),
    ]
    state = derive_thread_issue_tracking_state(issues)
    assert state.total_issues == 3
    assert state.issues_remaining == 2
    assert state.next_unread_issue_id == 2
    assert state.reading_progress == "in_progress"