"""Native Roll rerolls must not create durable snooze backoff.

Rust rerolls record a `snooze` event for history and dice projection, but the
temporary exclusion lives only in the browser cookie. Legacy Python eligibility
must not turn those events into cross-session backoff or block Read now.
"""

from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import Event, Issue, ReadingSession, Thread, User
from app.services.snooze_service import derive_cross_session_excluded_thread_ids


@pytest.mark.asyncio
async def test_native_reroll_snoozes_do_not_create_durable_backoff(
    async_db: AsyncSession, default_user: User
) -> None:
    """A native context marker excludes a snooze from legacy backoff only."""
    now = datetime.now(UTC)
    legacy = Thread(
        title="Legacy snooze",
        format="Comic",
        issues_remaining=1,
        total_issues=1,
        queue_position=1,
        status="active",
        user_id=default_user.id,
        created_at=now,
    )
    native = Thread(
        title="Native reroll",
        format="Comic",
        issues_remaining=1,
        total_issues=1,
        queue_position=2,
        status="active",
        user_id=default_user.id,
        created_at=now,
    )
    async_db.add_all([legacy, native])
    await async_db.flush()
    async_db.add_all(
        [
            Issue(
                thread_id=legacy.id,
                position=1,
                status="unread",
                issue_number="1",
            ),
            Issue(
                thread_id=native.id,
                position=1,
                status="unread",
                issue_number="1",
            ),
        ]
    )
    async_db.add_all(
        [
            Event(
                type="snooze",
                thread_id=legacy.id,
                user_id=default_user.id,
                timestamp=now,
            ),
            Event(
                type="snooze",
                thread_id=native.id,
                user_id=default_user.id,
                timestamp=now,
                context={"dice_command_key": "roll-offer-abc-snooze"},
            ),
        ]
    )
    # A session exists, but none started after the snooze, so the legacy
    # thread's one-snooze backoff is still active. The native thread must not
    # appear at all because its snooze is browser-cookie state.
    async_db.add(
        ReadingSession(
            user_id=default_user.id,
            started_at=now - timedelta(hours=1),
            start_die=6,
        )
    )
    await async_db.commit()

    excluded = await derive_cross_session_excluded_thread_ids(
        async_db, default_user.id
    )

    assert legacy.id in excluded
    assert native.id not in excluded
