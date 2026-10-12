"""Regression coverage for CBL adoption natural order (#3483).

Modeled on prod threads after the #3489 retest:

* Ultimate X-Men 17982: ``#7–#24``, then appended ``#2–#6``, then ``#1``.
  Next-unread showed ``#13`` even though ``#1–#6`` were unread.
* Ultimate Spider-Man 17977: missing ``#1`` and ``#2`` appended after later
  issues, so next-unread stayed on ``#6``.
"""

from datetime import UTC, datetime

import pytest
from sqlalchemy import event as sa_event
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession

from app.models import Issue, Thread
from app.services.cbl_plan_adoption import _ensure_missing_issue_created
from app.services.issue_insertion import create_issue_in_natural_order
from tests.conftest import get_or_create_user_async


def _fact(series: str, number: str) -> dict[str, object]:
    return {
        "series_name": series,
        "issue_number": number,
        "comicvine_issue_id": None,
        "external_series_identity_id": None,
    }


async def _series_thread(
    db: AsyncSession,
    *,
    user_id: int,
    title: str,
    numbers: list[str],
    read_through: str | None,
) -> Thread:
    """Create one owned series with the given position order and read prefix."""
    thread = Thread(
        user_id=user_id,
        title=title,
        format="comic",
        queue_position=1,
        status="active",
        total_issues=len(numbers),
        issues_remaining=len(numbers),
        reading_progress="not_started",
        created_at=datetime.now(UTC),
    )
    db.add(thread)
    await db.flush()

    issues: list[Issue] = []
    reached_unread = read_through is None
    for position, number in enumerate(numbers, start=1):
        if read_through is not None and number == read_through:
            status = "read"
            reached_unread = True
            after_read = False
        elif not reached_unread:
            status = "read"
            after_read = False
        else:
            status = "unread"
            after_read = True
        issue = Issue(
            thread_id=thread.id,
            issue_number=number,
            position=position,
            status=status,
            read_at=datetime.now(UTC) if status == "read" else None,
        )
        db.add(issue)
        issues.append(issue)
        if after_read and thread.next_unread_issue_id is None:
            await db.flush()
            thread.next_unread_issue_id = issue.id
    await db.flush()
    unread_count = sum(1 for issue in issues if issue.status == "unread")
    thread.issues_remaining = unread_count
    thread.reading_progress = "in_progress" if unread_count < len(issues) else "not_started"
    if unread_count == 0:
        thread.next_unread_issue_id = None
        thread.reading_progress = "completed"
    await db.flush()
    return thread


async def _ordered_numbers(db: AsyncSession, thread_id: int) -> list[str]:
    result = await db.execute(
        select(Issue).where(Issue.thread_id == thread_id).order_by(Issue.position)
    )
    return [issue.issue_number for issue in result.scalars().all()]


@pytest.mark.asyncio
async def test_ultimate_xmen_17982_adopts_missing_early_issues_in_natural_order(
    async_db: AsyncSession,
) -> None:
    """Missing #1–#6 join an owned #7–#24 Ultimate X-Men thread in natural order."""
    user = await get_or_create_user_async(async_db, "cbl-uxm-17982")
    thread = await _series_thread(
        async_db,
        user_id=user.id,
        title="CBL: Ultimate X-Men (2024)",
        numbers=[str(number) for number in range(7, 25)],
        read_through="12",
    )
    await async_db.refresh(thread)
    assert thread.next_unread_issue_id is not None
    next_before = await async_db.get(Issue, thread.next_unread_issue_id)
    assert next_before is not None
    assert next_before.issue_number == "13"

    for number in ("1", "2", "3", "4", "5", "6"):
        created = await _ensure_missing_issue_created(
            async_db,
            user.id,
            fact=_fact("Ultimate X-Men", number),
            volume_year=2024,
        )
        assert created.created is True

    assert await _ordered_numbers(async_db, thread.id) == [
        str(number) for number in range(1, 25)
    ]
    await async_db.refresh(thread)
    next_after = await async_db.get(Issue, thread.next_unread_issue_id)
    assert next_after is not None
    assert next_after.issue_number == "1"
    assert thread.issues_remaining == 18
    assert thread.reading_progress == "in_progress"


@pytest.mark.asyncio
async def test_ultimate_xmen_17982_readoption_onto_already_appended_issues(
    async_db: AsyncSession,
) -> None:
    """Re-adoption after a broken append still reseats #1 first (#3483 prod)."""
    user = await get_or_create_user_async(async_db, "cbl-uxm-17982-messy")
    existing = [str(number) for number in range(7, 25)] + [
        str(number) for number in range(2, 7)
    ]
    thread = await _series_thread(
        async_db,
        user_id=user.id,
        title="CBL: Ultimate X-Men (2024)",
        numbers=existing,
        read_through="12",
    )

    created = await _ensure_missing_issue_created(
        async_db,
        user.id,
        fact=_fact("Ultimate X-Men", "1"),
        volume_year=2024,
    )
    assert created.created is True

    assert await _ordered_numbers(async_db, thread.id) == [
        str(number) for number in range(1, 25)
    ]
    await async_db.refresh(thread)
    next_after = await async_db.get(Issue, thread.next_unread_issue_id)
    assert next_after is not None
    assert next_after.issue_number == "1"


@pytest.mark.asyncio
async def test_ultimate_spiderman_17977_adopts_1_and_2_before_later_issues(
    async_db: AsyncSession,
) -> None:
    """Missing USM #1–#2 land before later issues so next-unread is #1."""
    user = await get_or_create_user_async(async_db, "cbl-usm-17977")
    thread = await _series_thread(
        async_db,
        user_id=user.id,
        title="CBL: Ultimate Spider-Man (2024)",
        numbers=[str(number) for number in range(3, 25)],
        read_through="5",
    )
    await async_db.refresh(thread)
    next_before = await async_db.get(Issue, thread.next_unread_issue_id)
    assert next_before is not None
    assert next_before.issue_number == "6"

    first = await _ensure_missing_issue_created(
        async_db,
        user.id,
        fact=_fact("Ultimate Spider-Man", "1"),
        volume_year=2024,
    )
    second = await _ensure_missing_issue_created(
        async_db,
        user.id,
        fact=_fact("Ultimate Spider-Man", "2"),
        volume_year=2024,
    )
    assert first.created is True
    assert second.created is True

    assert await _ordered_numbers(async_db, thread.id) == [
        str(number) for number in range(1, 25)
    ]
    await async_db.refresh(thread)
    next_after = await async_db.get(Issue, thread.next_unread_issue_id)
    assert next_after is not None
    assert next_after.issue_number == "1"
    assert next_after.id == first.issue.id


@pytest.mark.asyncio
async def test_create_issue_in_natural_order_reseats_messy_ordinary_series(
    async_db: AsyncSession,
) -> None:
    """The shared insertion primitive reseats an already-appended series."""
    user = await get_or_create_user_async(async_db, "insert-messy-ordinary")
    thread = await _series_thread(
        async_db,
        user_id=user.id,
        title="CBL: Ultimate X-Men (2024)",
        numbers=[str(number) for number in range(7, 25)]
        + [str(number) for number in range(2, 7)],
        read_through=None,
    )

    created = await create_issue_in_natural_order(async_db, thread.id, "1")
    assert created.issue_number == "1"
    assert created.position == 1
    assert await _ordered_numbers(async_db, thread.id) == [
        str(number) for number in range(1, 25)
    ]


@pytest.mark.asyncio
async def test_sequential_natural_order_inserts_use_set_based_reseats(
    async_db: AsyncSession,
    db_engine: AsyncEngine,
) -> None:
    """Six early inserts on a large thread must not emit O(k·n) position UPDATEs."""
    user = await get_or_create_user_async(async_db, "insert-set-based-large")
    large_count = 500
    thread = await _series_thread(
        async_db,
        user_id=user.id,
        title="CBL: Large Series",
        numbers=[str(number) for number in range(7, 7 + large_count)],
        read_through=None,
    )

    statements: list[str] = []

    def record_statement(
        _connection: object,
        _cursor: object,
        statement: str,
        _parameters: object,
        _context: object,
        _executemany: bool,
    ) -> None:
        statements.append(" ".join(statement.split()).lower())

    sa_event.listen(db_engine.sync_engine, "before_cursor_execute", record_statement)
    try:
        for number in ("1", "2", "3", "4", "5", "6"):
            created = await create_issue_in_natural_order(async_db, thread.id, number)
            assert created.issue_number == number
    finally:
        sa_event.remove(db_engine.sync_engine, "before_cursor_execute", record_statement)

    position_updates = [
        statement
        for statement in statements
        if statement.startswith("update issues") and "position" in statement
    ]
    # One set-based UPDATE per insert (plus no per-row UPDATE flood).
    assert len(position_updates) == 6, (
        f"expected 6 set-based position updates, got {len(position_updates)}: "
        f"{position_updates[:8]}"
    )
    for statement in position_updates:
        assert "position=case" in statement or "position = case" in statement, statement

    assert await _ordered_numbers(async_db, thread.id) == [
        str(number) for number in range(1, 7 + large_count)
    ]
