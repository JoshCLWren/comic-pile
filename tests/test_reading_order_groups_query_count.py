"""Regression for #3465: GET /api/v1/reading-order-groups query count.

The endpoint previously issued one membership requery plus batched thread/issue
lookups per group (N+1). Production telemetry recorded 67 queries and a 21s
request for this route. The batched path must keep the SELECT count flat as
group and membership counts grow, and must preserve the membership response
contract that ``list_memberships`` established before the batch.
"""

from types import SimpleNamespace

import pytest
from sqlalchemy import event as sa_event
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession

from app.api.dependency_group import list_groups
from app.models import DependencyGroup, DependencyGroupMembership, Issue, Thread
from app.schemas.dependency_group import DependencyGroupResponse
from tests.conftest import get_or_create_user_async

# Groups + memberships (one ``selectinload`` query) + one thread-titles query +
# one joined issue-metadata query. The cap leaves headroom for a future
# non-N+1 query without hiding a regression back to per-group lookups.
MAX_SELECTS = 5

_THREAD_MEMBERS_PER_GROUP = 2
_ISSUES_PER_THREAD = 2

# One ``(membership id, series title, issue number)`` expectation per member.
_ExpectedMember = tuple[int, str | None, str | None]


def _title_for(threads: list[Thread], thread_id: int | None) -> str:
    """Return the seeded title for one thread target.

    Args:
        threads: The seeded threads for one group.
        thread_id: The membership's thread target.

    Returns:
        The thread title the API must report for that membership.
    """
    return next(thread.title for thread in threads if thread.id == thread_id)


async def _seed_groups(
    db: AsyncSession,
    user_id: int,
    *,
    group_count: int,
    label: str,
) -> list[tuple[DependencyGroup, list[_ExpectedMember]]]:
    """Create groups whose memberships mix thread targets and issue targets.

    Args:
        db: The async test session.
        user_id: The owning user identifier.
        group_count: How many dependency groups to create.
        label: Unique prefix for group names, thread titles, and queue positions.

    Returns:
        One ``(group, expected members)`` tuple per group, where expected
        members are ordered by membership id.
    """
    threads: list[Thread] = []
    for index in range(group_count * _THREAD_MEMBERS_PER_GROUP):
        thread = Thread(
            user_id=user_id,
            title=f"{label} Thread {index}",
            format="Comic",
            issues_remaining=_ISSUES_PER_THREAD,
            total_issues=_ISSUES_PER_THREAD,
            queue_position=index + 1,
            status="active",
        )
        db.add(thread)
        await db.flush()
        threads.append(thread)
        db.add_all(
            [
                Issue(
                    thread_id=thread.id,
                    issue_number=str(position),
                    position=position,
                    status="unread",
                )
                for position in range(1, _ISSUES_PER_THREAD + 1)
            ]
        )
    await db.flush()

    seeded: list[tuple[DependencyGroup, list[_ExpectedMember]]] = []
    for group_index in range(group_count):
        group = DependencyGroup(user_id=user_id, name=f"{label} Crossover {group_index:02d}")
        db.add(group)
        await db.flush()

        group_threads = threads[
            group_index * _THREAD_MEMBERS_PER_GROUP : (group_index + 1) * _THREAD_MEMBERS_PER_GROUP
        ]
        issue_rows = list(
            (
                await db.execute(
                    select(Issue.id, Issue.issue_number).where(
                        Issue.thread_id == group_threads[0].id
                    )
                )
            )
            .all()
        )
        # Issue memberships are inserted first so the ascending-id response
        # order is asserted across both membership kinds in one group.
        memberships = [
            DependencyGroupMembership(group_id=group.id, issue_id=issue_id)
            for issue_id, _ in issue_rows
        ] + [
            DependencyGroupMembership(group_id=group.id, thread_id=thread.id)
            for thread in group_threads
        ]
        db.add_all(memberships)
        await db.flush()

        issue_numbers = dict(issue_rows)
        expected: list[_ExpectedMember] = [
            (membership.id, group_threads[0].title, issue_numbers[membership.issue_id])
            if membership.issue_id is not None
            else (membership.id, _title_for(group_threads, membership.thread_id), None)
            for membership in memberships
        ]
        seeded.append((group, sorted(expected, key=lambda member: member[0])))

    await db.commit()
    return seeded


async def _count_route_selects(
    db: AsyncSession,
    db_engine: AsyncEngine,
    user_id: int,
) -> tuple[int, list[DependencyGroupResponse]]:
    """Run the list route while counting its SELECT statements.

    Args:
        db: The async test session.
        db_engine: The engine whose sync facade carries the SQL event.
        user_id: The authenticated owner identifier.

    Returns:
        The observed SELECT count and the parsed route responses.
    """
    statements: list[str] = []

    def _capture(
        _conn: object,
        _cursor: object,
        statement: str,
        _parameters: object,
        _context: object,
        _executemany: bool,
    ) -> None:
        statements.append(statement)

    sa_event.listen(db_engine.sync_engine, "before_cursor_execute", _capture)
    try:
        responses = await list_groups(current_user=SimpleNamespace(id=user_id), db=db)
    finally:
        sa_event.remove(db_engine.sync_engine, "before_cursor_execute", _capture)

    selects = [
        statement for statement in statements if statement.lstrip().upper().startswith("SELECT")
    ]
    return len(selects), list(responses)


def _assert_response_contract(
    seeded: list[tuple[DependencyGroup, list[_ExpectedMember]]],
    responses: list[DependencyGroupResponse],
) -> None:
    """Assert the batched path returns the pre-batch response contract.

    Args:
        seeded: The seeded ``(group, expected members)`` tuples.
        responses: The parsed route responses.
    """
    assert [response.name for response in responses] == sorted(
        group.name for group, _ in seeded
    )

    by_id = {response.id: response for response in responses}
    for group, expected in seeded:
        members = by_id[group.id].memberships
        assert [
            (member.id, member.series_title, member.issue_number) for member in members
        ] == expected


@pytest.mark.asyncio
async def test_reading_order_groups_constant_query_count(
    async_db: AsyncSession,
    db_engine: AsyncEngine,
) -> None:
    """Many groups with mixed members must not multiply SELECT statements."""
    user = await get_or_create_user_async(async_db)
    seeded = await _seed_groups(async_db, user.id, group_count=8, label="Wide")

    select_count, responses = await _count_route_selects(async_db, db_engine, user.id)

    assert select_count <= MAX_SELECTS, (
        f"Too many SELECTs ({select_count}) for {len(seeded)} seeded groups"
    )
    _assert_response_contract(seeded, responses)


@pytest.mark.asyncio
async def test_reading_order_groups_query_count_does_not_grow_with_groups(
    async_db: AsyncSession,
    db_engine: AsyncEngine,
) -> None:
    """The query count is flat, not merely small, as the group count grows."""
    user = await get_or_create_user_async(async_db)

    small = await _seed_groups(async_db, user.id, group_count=2, label="Small")
    small_count, small_responses = await _count_route_selects(async_db, db_engine, user.id)

    large = await _seed_groups(async_db, user.id, group_count=6, label="Large")
    large_count, large_responses = await _count_route_selects(async_db, db_engine, user.id)

    assert large_count == small_count, (
        "Query count grew with the group count: "
        f"{small_count} SELECTs for {len(small)} groups vs "
        f"{large_count} SELECTs for {len(small) + len(large)} groups"
    )
    _assert_response_contract(small, small_responses)
    _assert_response_contract(small + large, large_responses)