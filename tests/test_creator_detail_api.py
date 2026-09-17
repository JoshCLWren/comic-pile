"""API coverage for the bounded personal creator detail contract (issue #2037).

One authenticated detail endpoint returns a single creator's headline summary
plus role breakdowns and bounded rated/read-but-unrated/upcoming issue
collections. It reuses the #2028 rating, role, and coverage semantics: latest
effective ``rate`` event wins, one issue contributes at most once to headline
totals, and pure cover/editorial/unknown roles are preserved in role stats
without distorting the headline average. This module covers bounded collections,
deterministic ordering (recent-first and queue order), pagination, explicit
partial coverage, ownership isolation, and non-leaking not-found behavior.
"""

from collections.abc import Iterator
from contextlib import contextmanager
from datetime import UTC, datetime

import pytest
from httpx import AsyncClient
from sqlalchemy import event
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession

from app.models import Event, Issue, Thread, User
from app.models.external_identity import ExternalIdentity, IssueExternalIdentityMapping

D1 = datetime(2026, 3, 1, tzinfo=UTC)
D2 = datetime(2026, 3, 2, tzinfo=UTC)
D3 = datetime(2026, 3, 3, tzinfo=UTC)

_identity_serial = 0


@contextmanager
def _captured_selects(db_engine: AsyncEngine) -> Iterator[list[str]]:
    """Yield a list that records SELECT statements executed on the engine."""
    select_statements: list[str] = []

    def _capture(
        conn: object,
        cursor: object,
        statement: str,
        parameters: object,
        context: object,
        executemany: bool,
    ) -> None:
        if statement.lstrip().upper().startswith("SELECT"):
            select_statements.append(statement)

    event.listen(db_engine.sync_engine, "before_cursor_execute", _capture)
    try:
        yield select_statements
    finally:
        event.remove(db_engine.sync_engine, "before_cursor_execute", _capture)


async def _make_thread(
    db: AsyncSession,
    user: User,
    *,
    title: str,
    issue_count: int,
    queue_position: int,
    read_through: int = 0,
) -> tuple[Thread, list[Issue]]:
    """Create an owned thread with contiguous issues."""
    thread = Thread(
        user_id=user.id,
        title=title,
        format="Comic",
        issues_remaining=issue_count - read_through,
        total_issues=issue_count,
        queue_position=queue_position,
        status="active",
    )
    db.add(thread)
    await db.flush()
    issues = []
    for position in range(1, issue_count + 1):
        issue = Issue(
            thread_id=thread.id,
            issue_number=str(position),
            position=position,
            status="read" if position <= read_through else "unread",
        )
        db.add(issue)
        issues.append(issue)
    await db.flush()
    return thread, issues


async def _confirm_identity(
    db: AsyncSession,
    issue: Issue,
    *,
    creators: list[dict[str, object]] | None = None,
    metadata: dict[str, object] | None = None,
    provider: str = "comicvine",
    status: str = "confirmed",
) -> None:
    """Create an external issue identity mapping."""
    global _identity_serial
    _identity_serial += 1
    if metadata is not None:
        payload = metadata
    else:
        payload = {"creator_credits": creators or []}
    identity = ExternalIdentity(
        provider=provider,
        entity_type="issue",
        external_id=f"sv-{_identity_serial}",
        metadata_json=payload,
    )
    db.add(identity)
    await db.flush()
    db.add(
        IssueExternalIdentityMapping(
            issue_id=issue.id,
            external_identity_id=identity.id,
            status=status,
            confidence=1.0,
        )
    )
    await db.flush()


async def _rate(
    db: AsyncSession,
    issue: Issue,
    *,
    rating: float,
    timestamp: datetime,
) -> Event:
    """Create one rate event for an issue."""
    event = Event(
        type="rate",
        thread_id=issue.thread_id,
        issue_id=issue.id,
        issue_number=issue.issue_number,
        rating=rating,
        timestamp=timestamp,
    )
    db.add(event)
    await db.flush()
    return event


@pytest.mark.asyncio
async def test_detail_returns_headline_roles_and_bounded_collections(
    auth_client: AsyncClient,
    async_db: AsyncSession,
    default_user: User,
) -> None:
    """One request returns the headline summary plus all three collections."""
    thread, issues = await _make_thread(
        async_db, default_user, title="Team Book", issue_count=4, queue_position=1, read_through=3
    )
    assert thread is not None
    for issue in issues:
        await _confirm_identity(
            async_db, issue, creators=[{"id": 1, "name": "Writer One", "role": "writer"}]
        )
    await _rate(async_db, issues[0], rating=4.0, timestamp=D1)
    await _rate(async_db, issues[2], rating=5.0, timestamp=D3)

    response = await auth_client.get("/api/v1/creators/creator:1")

    assert response.status_code == 200
    body = response.json()
    assert body["next_cursor"] is None

    summary = body["summary"]
    assert summary["canonical_creator_key"] == "creator:1"
    assert summary["display_name"] == "Writer One"
    assert summary["normalized_roles"] == ["writer"]
    assert summary["ratings_count"] == 2
    assert summary["average_rating"] == pytest.approx(4.5)
    assert summary["read_unrated_count"] == 1
    assert summary["upcoming_count"] == 1

    rated = body["rated_issues"]
    assert [row["issue_id"] for row in rated] == [issues[2].id, issues[0].id]
    assert [row["issue_number"] for row in rated] == ["3", "1"]
    assert rated[0]["effective_rating"] == pytest.approx(5.0)
    assert rated[1]["effective_rating"] == pytest.approx(4.0)
    for row in rated:
        assert row["status"] == "read"
        assert row["thread_id"] == thread.id
        assert row["thread_title"] == "Team Book"
        assert set(row["roles"]) == {"writer"}
        assert row["rating_timestamp"]

    read_unrated = body["read_unrated_issues"]
    assert [row["issue_id"] for row in read_unrated] == [issues[1].id]
    assert read_unrated[0]["effective_rating"] is None
    assert read_unrated[0]["status"] == "read"

    upcoming = body["upcoming_issues"]
    assert [row["issue_id"] for row in upcoming] == [issues[3].id]
    assert upcoming[0]["status"] == "unread"
    assert upcoming[0]["effective_rating"] is None


@pytest.mark.asyncio
async def test_latest_effective_rating_wins_with_timestamp(
    auth_client: AsyncClient,
    async_db: AsyncSession,
    default_user: User,
) -> None:
    """The latest effective rate event determines the row's rating and timestamp."""
    _thread, issues = await _make_thread(
        async_db, default_user, title="Rerated", issue_count=1, queue_position=1, read_through=1
    )
    await _confirm_identity(
        async_db, issues[0], creators=[{"id": 10, "name": "Retry Roe", "role": "writer"}]
    )
    await _rate(async_db, issues[0], rating=4.0, timestamp=D1)
    await _rate(async_db, issues[0], rating=2.0, timestamp=D2)

    response = await auth_client.get("/api/v1/creators/creator:10")

    assert response.status_code == 200
    body = response.json()
    assert body["summary"]["ratings_count"] == 1
    assert body["summary"]["average_rating"] == pytest.approx(2.0)
    rated = body["rated_issues"]
    assert len(rated) == 1
    assert rated[0]["effective_rating"] == pytest.approx(2.0)
    assert str(rated[0]["rating_timestamp"]).startswith("2026-03-02")


@pytest.mark.asyncio
async def test_one_issue_contributes_once_despite_multiple_roles(
    auth_client: AsyncClient,
    async_db: AsyncSession,
    default_user: User,
) -> None:
    """One issue is rated at most once per creator even with several roles."""
    _thread, issues = await _make_thread(
        async_db, default_user, title="Duo", issue_count=1, queue_position=1, read_through=1
    )
    await _confirm_identity(
        async_db,
        issues[0],
        creators=[
            {"id": 7, "name": "Dan Rippley", "role": "writer"},
            {"id": 7, "name": "Dan Rippley", "role": "artist"},
        ],
    )
    await _rate(async_db, issues[0], rating=4.5, timestamp=D1)

    response = await auth_client.get("/api/v1/creators/creator:7")

    assert response.status_code == 200
    body = response.json()
    summary = body["summary"]
    assert summary["ratings_count"] == 1
    assert summary["average_rating"] == pytest.approx(4.5)
    assert summary["normalized_roles"] == ["artist", "writer"]

    by_role = {stat["role"]: stat for stat in body["role_stats"]}
    assert set(by_role) == {"artist", "writer"}
    assert by_role["artist"]["issue_count"] == 1
    assert by_role["writer"]["issue_count"] == 1

    rated = body["rated_issues"]
    assert len(rated) == 1
    assert rated[0]["roles"] == ["artist", "writer"]
    assert rated[0]["effective_rating"] == pytest.approx(4.5)


@pytest.mark.asyncio
async def test_cover_only_credit_is_preserved_in_role_stats_but_not_headline(
    auth_client: AsyncClient,
    async_db: AsyncSession,
    default_user: User,
) -> None:
    """A pure cover credit stays visible but never feeds the headline average."""
    _thread, issues = await _make_thread(
        async_db, default_user, title="Covered", issue_count=1, queue_position=1, read_through=1
    )
    await _confirm_identity(
        async_db, issues[0], creators=[{"id": 8, "name": "Cover Gal", "role": "cover"}]
    )
    await _rate(async_db, issues[0], rating=4.0, timestamp=D1)

    response = await auth_client.get("/api/v1/creators/creator:8")

    assert response.status_code == 200
    body = response.json()
    summary = body["summary"]
    assert summary["display_name"] == "Cover Gal"
    assert summary["normalized_roles"] == ["cover"]
    assert summary["ratings_count"] == 0
    assert summary["average_rating"] is None

    assert body["role_stats"] == [
        {"role": "cover", "issue_count": 1, "average_rating": pytest.approx(4.0)}
    ]
    assert len(body["rated_issues"]) == 1
    assert body["rated_issues"][0]["effective_rating"] == pytest.approx(4.0)
    assert body["rated_issues"][0]["roles"] == ["cover"]


@pytest.mark.asyncio
async def test_unknown_role_stays_unclassified(
    auth_client: AsyncClient,
    async_db: AsyncSession,
    default_user: User,
) -> None:
    """An unknown provider role string is preserved but never guessed."""
    _thread, issues = await _make_thread(
        async_db, default_user, title="Layout", issue_count=1, queue_position=1, read_through=1
    )
    await _confirm_identity(
        async_db, issues[0], creators=[{"id": 9, "name": "Lay Out", "role": "layout"}]
    )
    await _rate(async_db, issues[0], rating=4.0, timestamp=D1)

    response = await auth_client.get("/api/v1/creators/creator:9")

    assert response.status_code == 200
    body = response.json()
    summary = body["summary"]
    assert summary["normalized_roles"] == ["layout"]
    assert summary["ratings_count"] == 0
    assert summary["average_rating"] is None
    assert body["role_stats"] == [
        {"role": "layout", "issue_count": 1, "average_rating": pytest.approx(4.0)}
    ]


@pytest.mark.asyncio
async def test_upcoming_orders_by_queue_then_issue_position(
    auth_client: AsyncClient,
    async_db: AsyncSession,
    default_user: User,
) -> None:
    """Upcoming follows local queue order, never issue-id or bibliography order."""
    later_thread, later_issues = await _make_thread(
        async_db, default_user, title="Later", issue_count=2, queue_position=2
    )
    sooner_thread, sooner_issues = await _make_thread(
        async_db, default_user, title="Sooner", issue_count=2, queue_position=1
    )
    assert later_thread is not None
    assert sooner_thread is not None
    for issue in [*later_issues, *sooner_issues]:
        await _confirm_identity(
            async_db, issue, creators=[{"id": 6, "name": "Queue Quinn", "role": "writer"}]
        )

    response = await auth_client.get("/api/v1/creators/creator:6")

    assert response.status_code == 200
    upcoming = response.json()["upcoming_issues"]
    assert [row["issue_id"] for row in upcoming] == [
        sooner_issues[0].id,
        sooner_issues[1].id,
        later_issues[0].id,
        later_issues[1].id,
    ]
    sort_keys = [row["sort_key"] for row in upcoming]
    assert sort_keys == sorted(sort_keys)


@pytest.mark.asyncio
async def test_read_unrated_collection_and_zero_upcoming(
    auth_client: AsyncClient,
    async_db: AsyncSession,
    default_user: User,
) -> None:
    """Read-but-unrated issues surface while upcoming stays empty when all read."""
    _thread, issues = await _make_thread(
        async_db, default_user, title="All Read", issue_count=3, queue_position=1, read_through=3
    )
    for issue in issues:
        await _confirm_identity(
            async_db, issue, creators=[{"id": 11, "name": "Read Rob", "role": "writer"}]
        )
    await _rate(async_db, issues[0], rating=4.0, timestamp=D1)

    response = await auth_client.get("/api/v1/creators/creator:11")

    assert response.status_code == 200
    body = response.json()
    assert len(body["rated_issues"]) == 1
    assert len(body["read_unrated_issues"]) == 2
    assert body["upcoming_issues"] == []
    assert body["summary"]["read_unrated_count"] == 2
    assert body["summary"]["upcoming_count"] == 0


@pytest.mark.asyncio
async def test_pagination_bounds_collections_with_next_cursor(
    auth_client: AsyncClient,
    async_db: AsyncSession,
    default_user: User,
) -> None:
    """Long collections are bounded with a deterministic offset cursor."""
    _thread, issues = await _make_thread(
        async_db, default_user, title="Long", issue_count=6, queue_position=1, read_through=6
    )
    for issue in issues:
        await _confirm_identity(
            async_db, issue, creators=[{"id": 30, "name": "Page Pam", "role": "writer"}]
        )
        await _rate(async_db, issue, rating=3.0, timestamp=D1)

    first = await auth_client.get("/api/v1/creators/creator:30?limit=2")
    assert first.status_code == 200
    assert len(first.json()["rated_issues"]) == 2
    assert first.json()["next_cursor"] == "2"

    second = await auth_client.get("/api/v1/creators/creator:30?limit=2&offset=2")
    assert second.status_code == 200
    assert len(second.json()["rated_issues"]) == 2
    assert second.json()["next_cursor"] == "4"

    third = await auth_client.get("/api/v1/creators/creator:30?limit=2&offset=4")
    assert third.status_code == 200
    assert len(third.json()["rated_issues"]) == 2
    assert third.json()["next_cursor"] is None


@pytest.mark.asyncio
async def test_partial_coverage_is_explicit(
    auth_client: AsyncClient,
    async_db: AsyncSession,
    default_user: User,
) -> None:
    """Missing or unconfirmed metadata marks coverage partial, never negative."""
    _thread, issues = await _make_thread(
        async_db, default_user, title="Patchy", issue_count=3, queue_position=1, read_through=3
    )
    await _confirm_identity(
        async_db, issues[0], creators=[{"id": 3, "name": "Ann A.", "role": "writer"}]
    )
    await _rate(async_db, issues[0], rating=5.0, timestamp=D1)
    await _rate(async_db, issues[1], rating=4.0, timestamp=D2)
    await _rate(async_db, issues[2], rating=3.0, timestamp=D3)

    response = await auth_client.get("/api/v1/creators/creator:3")

    assert response.status_code == 200
    coverage = response.json()["coverage"]
    assert coverage["rated_issues_total"] == 3
    assert coverage["rated_issues_with_creator_metadata"] == 1
    assert coverage["ratings_complete"] is False


@pytest.mark.asyncio
async def test_unconfirmed_metadata_is_not_guessed(
    auth_client: AsyncClient,
    async_db: AsyncSession,
    default_user: User,
) -> None:
    """A candidate-only mapping never fabricates a creator identity."""
    _thread, issues = await _make_thread(
        async_db, default_user, title="Pending", issue_count=1, queue_position=1, read_through=1
    )
    await _confirm_identity(
        async_db,
        issues[0],
        creators=[{"id": 55, "name": "Maybe Moe", "role": "writer"}],
        status="candidate",
    )
    await _rate(async_db, issues[0], rating=4.0, timestamp=D1)

    response = await auth_client.get("/api/v1/creators/creator:55")

    assert response.status_code == 404


@pytest.mark.asyncio
async def test_ownership_isolation_and_non_leaking_not_found(
    auth_client: AsyncClient,
    async_db: AsyncSession,
    default_user: User,
) -> None:
    """A creator in another user's library is indistinguishable from unknown."""
    other_user = User(username="creator_detail_other")
    async_db.add(other_user)
    await async_db.flush()

    _thread, issues = await _make_thread(
        async_db, default_user, title="Mine", issue_count=1, queue_position=1, read_through=1
    )
    await _confirm_identity(
        async_db, issues[0], creators=[{"id": 1, "name": "Mine Writer", "role": "writer"}]
    )
    await _rate(async_db, issues[0], rating=4.0, timestamp=D1)

    hidden_thread, hidden_issues = await _make_thread(
        async_db, other_user, title="Hidden", issue_count=1, queue_position=2, read_through=1
    )
    assert hidden_thread is not None
    await _confirm_identity(
        async_db,
        hidden_issues[0],
        creators=[{"id": 999, "name": "Hidden Writer", "role": "writer"}],
    )
    await _rate(async_db, hidden_issues[0], rating=5.0, timestamp=D1)

    visible = await auth_client.get("/api/v1/creators/creator:1")
    assert visible.status_code == 200
    assert visible.json()["summary"]["display_name"] == "Mine Writer"

    foreign = await auth_client.get("/api/v1/creators/creator:999")
    unknown = await auth_client.get("/api/v1/creators/creator:424242")
    assert foreign.status_code == 404
    assert unknown.status_code == 404
    assert list(foreign.json()) == list(unknown.json())
    assert "not found in your library" in foreign.json()["detail"]
    assert "not found in your library" in unknown.json()["detail"]


@pytest.mark.asyncio
async def test_invalid_and_missing_creator_keys(
    auth_client: AsyncClient,
) -> None:
    """Malformed keys are rejected and absent keys are uniformly 404."""
    for bad_key in ["writer:1", "creator:abc", "creator:", "creator:1:2"]:
        response = await auth_client.get(f"/api/v1/creators/{bad_key}")
        assert response.status_code == 400, bad_key

    missing = await auth_client.get("/api/v1/creators/creator:424242")
    assert missing.status_code == 404


@pytest.mark.asyncio
async def test_unauthenticated_request_is_rejected(
    client: AsyncClient,
) -> None:
    """The detail endpoint requires an authenticated user."""
    response = await client.get("/api/v1/creators/creator:1")
    assert response.status_code == 401


@pytest.mark.asyncio
async def test_detail_uses_bounded_constant_query_count(
    auth_client: AsyncClient,
    async_db: AsyncSession,
    db_engine: AsyncEngine,
    default_user: User,
) -> None:
    """One detail request uses a fixed query count regardless of issue count."""
    _small_thread, small_issues = await _make_thread(
        async_db, default_user, title="Small", issue_count=2, queue_position=1, read_through=2
    )
    for issue in small_issues:
        await _confirm_identity(
            async_db, issue, creators=[{"id": 101, "name": "Small Sam", "role": "writer"}]
        )
        await _rate(async_db, issue, rating=3.0, timestamp=D1)

    _wide_thread, wide_issues = await _make_thread(
        async_db, default_user, title="Wide", issue_count=6, queue_position=2, read_through=6
    )
    for issue in wide_issues:
        await _confirm_identity(
            async_db, issue, creators=[{"id": 201, "name": "Wide Wilma", "role": "writer"}]
        )
        await _rate(async_db, issue, rating=4.0, timestamp=D1)
    await async_db.flush()

    await auth_client.get("/api/v1/creators/creator:101")

    with _captured_selects(db_engine) as small_selects:
        small = await auth_client.get("/api/v1/creators/creator:101")
    with _captured_selects(db_engine) as wide_selects:
        wide = await auth_client.get("/api/v1/creators/creator:201")

    assert small.status_code == 200
    assert wide.status_code == 200
    assert len(small_selects) == len(wide_selects)
    assert len(small_selects) <= 12, small_selects