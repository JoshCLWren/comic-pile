"""Regression for #3763: a History card must show its own series' issue.

A History card names one series and one issue number. The number has to
belong to the series the card names, so a rating of one series can never lend
its issue number to another series rolled in the same session. The card and
the session timeline must agree on that identity.
"""

from datetime import UTC, datetime, timedelta

import pytest
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import Event, Issue, Thread
from app.models import ReadingSession
from app.models import User

_SESSION_START = datetime(2026, 10, 15, 19, 31, tzinfo=UTC)


async def _tracked_thread(
    async_db: AsyncSession,
    user: User,
    *,
    title: str,
    issue_numbers: list[str],
    queue_position: int,
) -> tuple[Thread, dict[str, Issue]]:
    """Create a thread with tracked issues and return its issues by number.

    Args:
        async_db: Active database session.
        user: Owner of the thread.
        title: Series title.
        issue_numbers: Issue numbers to create, in reading order.
        queue_position: Queue ordinal for the thread.

    Returns:
        The created thread and its issues keyed by issue number.
    """
    thread = Thread(
        title=title,
        format="Comic",
        issues_remaining=0,
        queue_position=queue_position,
        user_id=user.id,
        total_issues=len(issue_numbers),
        reading_progress="in_progress",
    )
    async_db.add(thread)
    await async_db.flush()

    issues = [
        Issue(
            thread_id=thread.id,
            issue_number=number,
            position=position,
            status="unread",
        )
        for position, number in enumerate(issue_numbers, start=1)
    ]
    async_db.add_all(issues)
    await async_db.flush()
    for issue in issues:
        await async_db.refresh(issue)

    thread.next_unread_issue_id = issues[0].id
    await async_db.flush()

    return thread, {issue.issue_number: issue for issue in issues}


@pytest.mark.asyncio
async def test_history_card_shows_the_rolled_series_issue(
    auth_client: AsyncClient, async_db: AsyncSession, default_user: User
) -> None:
    """A rating of another series never lends its issue number to the card."""
    alpha, alpha_issues = await _tracked_thread(
        async_db,
        default_user,
        title="Alpha Flight",
        issue_numbers=["40", "41"],
        queue_position=1,
    )
    iron_man, iron_man_issues = await _tracked_thread(
        async_db,
        default_user,
        title="Iron Man",
        issue_numbers=["2"],
        queue_position=2,
    )

    session = ReadingSession(
        start_die=6,
        user_id=default_user.id,
        started_at=_SESSION_START,
    )
    async_db.add(session)
    await async_db.flush()

    async_db.add_all(
        [
            Event(
                type="roll",
                session_id=session.id,
                selected_thread_id=iron_man.id,
                die=6,
                result=2,
                selection_method="random",
                issue_id=iron_man_issues["2"].id,
                issue_number="2",
                timestamp=_SESSION_START,
            ),
            Event(
                type="rate",
                session_id=session.id,
                thread_id=iron_man.id,
                rating=3.5,
                issues_read=2,
                die=6,
                die_after=4,
                issue_id=iron_man_issues["2"].id,
                issue_number="2",
                timestamp=_SESSION_START + timedelta(seconds=30),
            ),
            Event(
                type="roll",
                session_id=session.id,
                selected_thread_id=alpha.id,
                die=4,
                result=5,
                selection_method="random",
                issue_id=alpha_issues["41"].id,
                issue_number="41",
                timestamp=_SESSION_START + timedelta(minutes=5),
            ),
        ]
    )
    await async_db.commit()

    response = await auth_client.get("/api/v1/sessions/")
    assert response.status_code == 200
    item = next(s for s in response.json()["sessions"] if s["id"] == session.id)

    active_thread = item["active_thread"]
    assert active_thread is not None
    assert active_thread["title"] == "Alpha Flight"
    assert active_thread["issue_number"] == "41"
    assert active_thread["next_issue_number"] == "41"
    assert active_thread["next_issue_id"] == alpha_issues["41"].id

    details = await auth_client.get(f"/api/v1/sessions/{session.id}/details")
    assert details.status_code == 200
    timeline_roll = next(
        event
        for event in details.json()["events"]
        if event["type"] == "roll" and event["thread_title"] == "Alpha Flight"
    )
    assert timeline_roll["issue_number"] == "41"


@pytest.mark.asyncio
async def test_history_card_keeps_the_rated_issue_of_its_own_series(
    auth_client: AsyncClient, async_db: AsyncSession, default_user: User
) -> None:
    """A rated issue stays pinned to its own series after the series advances."""
    thread, issues = await _tracked_thread(
        async_db,
        default_user,
        title="Justice League Europe",
        issue_numbers=["5", "6", "7"],
        queue_position=1,
    )

    session = ReadingSession(
        start_die=6,
        user_id=default_user.id,
        started_at=_SESSION_START,
    )
    async_db.add(session)
    await async_db.flush()

    async_db.add_all(
        [
            Event(
                type="roll",
                session_id=session.id,
                selected_thread_id=thread.id,
                die=6,
                result=1,
                selection_method="random",
                timestamp=_SESSION_START,
            ),
            Event(
                type="rate",
                session_id=session.id,
                thread_id=thread.id,
                rating=4.0,
                issues_read=1,
                die=6,
                die_after=8,
                issue_id=issues["5"].id,
                issue_number="5",
                timestamp=_SESSION_START + timedelta(minutes=1),
            ),
        ]
    )
    await async_db.commit()

    response = await auth_client.get("/api/v1/sessions/")
    assert response.status_code == 200
    item = next(s for s in response.json()["sessions"] if s["id"] == session.id)

    active_thread = item["active_thread"]
    assert active_thread is not None
    assert active_thread["title"] == "Justice League Europe"
    assert active_thread["next_issue_number"] == "5"
    assert active_thread["next_issue_id"] == issues["5"].id
