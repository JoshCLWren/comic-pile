"""Performance regression test for rate endpoint round-trip count.

Ensures the rate endpoint performs a bounded number of DB queries after
removing redundant post-commit re-reads and using get_current_die_for_session.
"""

from datetime import UTC, datetime

import pytest
from sqlalchemy import event as sa_event
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession

from httpx import AsyncClient

from app.models import Issue, Thread

# After the #2553 cutover, blocked-state refresh joins canonical Dependency
# rows rather than materializing ContinuityRule / DependencyGroup snapshots.
CANONICAL_BLOCKING_PROBE = "join dependencies"
LEGACY_CONTINUITY_GRAPH_PROBES = (
    "from dependency_groups",
    "from dependency_group_memberships",
    "from continuity_rules",
    "from continuity_rule_selected_members",
)


@pytest.mark.asyncio
async def test_rate_endpoint_query_count(
    auth_client: AsyncClient,
    async_db: AsyncSession,
) -> None:
    """Check that the rate endpoint uses a bounded number of DB queries.

    The optimized implementation reuses the already-loaded session and thread
    objects instead of issuing extra SELECTs after commit. Key savings:
    - get_current_die_for_session avoids re-querying the session object.
    - Pre-extracting response values avoids db.refresh(thread) after commit.
    - Building ThreadResponse directly avoids thread_to_response's extra queries.
    """
    from tests.conftest import get_or_create_user_async

    user = await get_or_create_user_async(async_db)
    thread = Thread(
        title="Perf Rate Thread",
        format="Comic",
        issues_remaining=5,
        queue_position=1,
        status="active",
        user_id=user.id,
    )
    async_db.add(thread)
    await async_db.commit()
    await async_db.refresh(thread)

    # Establish a session and pending thread via a roll.
    roll_resp = await auth_client.post("/api/v1/roll/")
    assert roll_resp.status_code == 200

    # Rate the thread.
    rate_resp = await auth_client.post(
        "/api/v1/rate/",
        json={"rating": 4.0},
    )
    assert rate_resp.status_code == 200

    queries = int(rate_resp.headers.get("X-App-DB-Queries", "0"))
    # Before optimization: ~15-25 queries. After: should be well under 15.
    assert queries <= 12, f"Too many DB queries: {queries}"


async def _seed_issue_tracking_queue(
    async_db: AsyncSession, user_id: int, thread_count: int
) -> None:
    """Create issue-tracking threads so blocked-state work has a graph to load.

    Args:
        async_db: Database session.
        user_id: Owner for the created threads.
        thread_count: Number of active issue-tracking threads to create.
    """
    now = datetime.now(UTC)
    threads = [
        Thread(
            title=f"Graph {index}",
            format="Comic",
            issues_remaining=4,
            queue_position=index + 1,
            status="active",
            user_id=user_id,
            total_issues=4,
            reading_progress="in_progress",
            last_activity_at=now,
        )
        for index in range(thread_count)
    ]
    async_db.add_all(threads)
    await async_db.flush()
    for thread in threads:
        issues = [
            Issue(
                thread_id=thread.id,
                issue_number=str(number),
                position=number,
                status="unread",
                read_at=None,
            )
            for number in range(1, 5)
        ]
        async_db.add_all(issues)
        await async_db.flush()
        thread.next_unread_issue_id = issues[0].id
    await async_db.commit()


@pytest.mark.asyncio
@pytest.mark.parametrize("rating", [2.0, 4.0])
async def test_rate_endpoint_loads_the_continuity_graph_once(
    auth_client: AsyncClient,
    async_db: AsyncSession,
    db_engine: AsyncEngine,
    rating: float,
) -> None:
    """Blocked-state refresh must join canonical Dependencies exactly once.

    Issue #3388 budgeted POST /api/v1/rate at 1000 ms after a "targeted"
    ContinuityRule snapshot refresh rebuilt the graph twice. The #2553 cutover
    replaced that snapshot with a single canonical Dependency join; this probe
    still fails if refresh runs twice, and it also fails if the rate path
    regresses onto the legacy ContinuityRule / DependencyGroup snapshot.
    Both rate branches are covered because the safe-position branch runs on
    low ratings and the move-to-front branch on high ratings.
    """
    from tests.conftest import get_or_create_user_async

    user = await get_or_create_user_async(async_db)
    await _seed_issue_tracking_queue(async_db, user.id, thread_count=20)

    roll_resp = await auth_client.post("/api/v1/roll/")
    assert roll_resp.status_code == 200

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
        rate_resp = await auth_client.post("/api/v1/rate/", json={"rating": rating})
    finally:
        sa_event.remove(db_engine.sync_engine, "before_cursor_execute", record_statement)

    assert rate_resp.status_code == 200, rate_resp.text

    canonical_matches = [
        statement for statement in statements if CANONICAL_BLOCKING_PROBE in statement
    ]
    assert len(canonical_matches) == 1, (
        "Expected exactly one canonical Dependency join per rate call, got "
        f"{len(canonical_matches)}. A refresh that evaluates blocked state twice "
        "regressed POST /api/v1/rate round trips."
    )
    for probe in LEGACY_CONTINUITY_GRAPH_PROBES:
        matches = [statement for statement in statements if probe in statement]
        assert not matches, (
            f"Rate path still loaded legacy continuity graph table {probe!r} "
            f"({len(matches)} times); blocked-state refresh must use canonical "
            "Dependencies after the #2553 cutover."
        )
