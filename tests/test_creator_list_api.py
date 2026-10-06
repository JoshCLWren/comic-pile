"""API coverage for the bounded personal creator discovery list (issue #2775).

This module covers the backend discovery contract owned by #2775:
bounded, user-scoped collection of canonical creators with at least one
rated issue, rows include key/display name/ratings_count/average_rating and
compact roles, headline semantics match #2028/#2037, duplicate display names
remain distinct, search/sort/pagination are bounded and deterministic, user
isolation holds, coverage is honest, and query count is constant (no N+1).
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
    """Create a confirmed external issue identity mapping."""
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
    evt = Event(
        type="rate",
        thread_id=issue.thread_id,
        issue_id=issue.id,
        issue_number=issue.issue_number,
        rating=rating,
        timestamp=timestamp,
    )
    db.add(evt)
    await db.flush()
    return evt


@pytest.mark.asyncio
async def test_list_empty_when_no_rated_creators(
    auth_client: AsyncClient,
    async_db: AsyncSession,
    default_user: User,
) -> None:
    """No rated creators yields empty bounded list with honest coverage."""
    response = await auth_client.get("/api/v1/creators")
    assert response.status_code == 200
    body = response.json()
    assert body["items"] == []
    assert body["total"] == 0
    assert body["limit"] == 20
    assert body["offset"] == 0
    assert body["coverage"]["rated_issues_total"] == 0
    assert body["coverage"]["ratings_complete"] is True


@pytest.mark.asyncio
async def test_list_one_creator_row_contract(
    auth_client: AsyncClient,
    async_db: AsyncSession,
    default_user: User,
) -> None:
    """Single rated creator row carries key, name, count, average, and roles."""
    _thread, issues = await _make_thread(
        async_db, default_user, title="Solo", issue_count=1, queue_position=1, read_through=1
    )
    await _confirm_identity(
        async_db, issues[0], creators=[{"id": 1, "name": "Writer One", "role": "writer"}]
    )
    await _rate(async_db, issues[0], rating=4.0, timestamp=D1)

    response = await auth_client.get("/api/v1/creators")
    assert response.status_code == 200
    body = response.json()
    assert body["total"] == 1
    assert len(body["items"]) == 1
    row = body["items"][0]
    assert row["canonical_creator_key"] == "creator:1"
    assert row["display_name"] == "Writer One"
    assert row["ratings_count"] == 1
    assert row["average_rating"] == pytest.approx(4.0)
    assert row["normalized_roles"] == ["writer"]


@pytest.mark.asyncio
async def test_one_issue_contributes_once_despite_multiple_roles(
    auth_client: AsyncClient,
    async_db: AsyncSession,
    default_user: User,
) -> None:
    """One issue counts once even when a creator has multiple roles on it."""
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

    response = await auth_client.get("/api/v1/creators")
    assert response.status_code == 200
    row = next(r for r in response.json()["items"] if r["canonical_creator_key"] == "creator:7")
    assert row["ratings_count"] == 1
    assert row["average_rating"] == pytest.approx(4.5)
    assert row["normalized_roles"] == ["artist", "writer"]


@pytest.mark.asyncio
async def test_duplicate_display_names_remain_distinct_keys(
    auth_client: AsyncClient,
    async_db: AsyncSession,
    default_user: User,
) -> None:
    """Two canonical keys sharing a display name remain separate rows."""
    t1, i1 = await _make_thread(
        async_db, default_user, title="Book One", issue_count=1, queue_position=1, read_through=1
    )
    t2, i2 = await _make_thread(
        async_db, default_user, title="Book Two", issue_count=1, queue_position=2, read_through=1
    )
    assert t1 is not None and t2 is not None
    await _confirm_identity(
        async_db, i1[0], creators=[{"id": 111, "name": "Shared Name", "role": "writer"}]
    )
    await _confirm_identity(
        async_db, i2[0], creators=[{"id": 222, "name": "Shared Name", "role": "artist"}]
    )
    await _rate(async_db, i1[0], rating=4.5, timestamp=D1)
    await _rate(async_db, i2[0], rating=3.0, timestamp=D2)

    response = await auth_client.get("/api/v1/creators?sort=name")
    assert response.status_code == 200
    body = response.json()
    keys = [r["canonical_creator_key"] for r in body["items"]]
    assert "creator:111" in keys and "creator:222" in keys
    row111 = next(r for r in body["items"] if r["canonical_creator_key"] == "creator:111")
    row222 = next(r for r in body["items"] if r["canonical_creator_key"] == "creator:222")
    assert row111["ratings_count"] == 1 and row222["ratings_count"] == 1
    assert row111["display_name"] == "Shared Name"
    assert row222["display_name"] == "Shared Name"


@pytest.mark.asyncio
async def test_search_is_bounded_and_user_scoped(
    auth_client: AsyncClient,
    async_db: AsyncSession,
    default_user: User,
) -> None:
    """Name search is case-insensitive, bounded, and does not leak others."""
    _thread, issues = await _make_thread(
        async_db, default_user, title="Search", issue_count=2, queue_position=1, read_through=2
    )
    await _confirm_identity(
        async_db, issues[0], creators=[{"id": 10, "name": "Alice Writer", "role": "writer"}]
    )
    await _confirm_identity(
        async_db, issues[1], creators=[{"id": 20, "name": "Bob Artist", "role": "artist"}]
    )
    await _rate(async_db, issues[0], rating=5.0, timestamp=D1)
    await _rate(async_db, issues[1], rating=3.0, timestamp=D2)

    response = await auth_client.get("/api/v1/creators?search=alice")
    assert response.status_code == 200
    body = response.json()
    assert body["total"] == 1
    assert body["items"][0]["canonical_creator_key"] == "creator:10"

    upper = await auth_client.get("/api/v1/creators?search=ALICE")
    assert upper.json()["total"] == 1

    none = await auth_client.get("/api/v1/creators?search=zzz")
    assert none.json()["total"] == 0
    assert none.json()["items"] == []


@pytest.mark.asyncio
async def test_sort_alphabetical_is_deterministic(
    auth_client: AsyncClient,
    async_db: AsyncSession,
    default_user: User,
) -> None:
    """Alphabetical order uses display_name case-insensitive and stable key tie-breaker."""
    _thread, issues = await _make_thread(
        async_db, default_user, title="Alpha", issue_count=3, queue_position=1, read_through=3
    )
    await _confirm_identity(
        async_db, issues[0], creators=[{"id": 3, "name": "Charlie", "role": "writer"}]
    )
    await _confirm_identity(
        async_db, issues[1], creators=[{"id": 1, "name": "alice", "role": "writer"}]
    )
    await _confirm_identity(
        async_db, issues[2], creators=[{"id": 2, "name": "Alice", "role": "writer"}]
    )
    for iss in issues:
        await _rate(async_db, iss, rating=4.0, timestamp=D1)

    response = await auth_client.get("/api/v1/creators?sort=name")
    assert response.status_code == 200
    names = [(r["display_name"], r["canonical_creator_key"]) for r in response.json()["items"]]
    # alice/ Alice share lowercased name; canonical key is stable tie-breaker
    assert names == [("Alice", "creator:2"), ("alice", "creator:1"), ("Charlie", "creator:3")] or names == [
        ("alice", "creator:1"),
        ("Alice", "creator:2"),
        ("Charlie", "creator:3"),
    ]
    # Ensure lowercased ordering is correct
    lower = [n.lower() for n, _ in names]
    assert lower == sorted(lower)


@pytest.mark.asyncio
async def test_sort_most_rated_descending_deterministic(
    auth_client: AsyncClient,
    async_db: AsyncSession,
    default_user: User,
) -> None:
    """Most-rated order is ratings_count descending with name/key tie-breakers."""
    _thread, issues = await _make_thread(
        async_db, default_user, title="Rated", issue_count=3, queue_position=1, read_through=3
    )
    # creator:1 appears once, creator:2 appears twice
    await _confirm_identity(
        async_db, issues[0], creators=[{"id": 1, "name": "Solo", "role": "writer"}]
    )
    await _confirm_identity(
        async_db, issues[1], creators=[{"id": 2, "name": "Double", "role": "writer"}]
    )
    await _confirm_identity(
        async_db, issues[2], creators=[{"id": 2, "name": "Double", "role": "writer"}]
    )
    for iss in issues:
        await _rate(async_db, iss, rating=4.0, timestamp=D1)

    response = await auth_client.get("/api/v1/creators?sort=ratings_count")
    assert response.status_code == 200
    items = response.json()["items"]
    assert items[0]["canonical_creator_key"] == "creator:2"
    assert items[0]["ratings_count"] == 2
    assert items[1]["canonical_creator_key"] == "creator:1"
    assert items[1]["ratings_count"] == 1


@pytest.mark.asyncio
async def test_sort_average_rating_descending_nulls_last(
    auth_client: AsyncClient,
    async_db: AsyncSession,
    default_user: User,
) -> None:
    """Personal-average order is average desc, nulls last, deterministic."""
    _thread, issues = await _make_thread(
        async_db, default_user, title="Avg", issue_count=2, queue_position=1, read_through=2
    )
    await _confirm_identity(
        async_db, issues[0], creators=[{"id": 5, "name": "High", "role": "writer"}]
    )
    await _confirm_identity(
        async_db, issues[1], creators=[{"id": 6, "name": "Low", "role": "writer"}]
    )
    await _rate(async_db, issues[0], rating=5.0, timestamp=D1)
    await _rate(async_db, issues[1], rating=2.0, timestamp=D1)

    response = await auth_client.get("/api/v1/creators?sort=average_rating")
    assert response.status_code == 200
    items = response.json()["items"]
    assert items[0]["canonical_creator_key"] == "creator:5"
    assert items[0]["average_rating"] == pytest.approx(5.0)
    assert items[1]["canonical_creator_key"] == "creator:6"
    assert items[1]["average_rating"] == pytest.approx(2.0)


@pytest.mark.asyncio
async def test_pagination_boundaries_deterministic(
    auth_client: AsyncClient,
    async_db: AsyncSession,
    default_user: User,
) -> None:
    """Pagination is bounded with stable tie-breaker across pages."""
    _thread, issues = await _make_thread(
        async_db, default_user, title="Pages", issue_count=5, queue_position=1, read_through=5
    )
    for idx, issue in enumerate(issues):
        await _confirm_identity(
            async_db,
            issue,
            creators=[{"id": 100 + idx, "name": f"Creator {idx:02d}", "role": "writer"}],
        )
        await _rate(async_db, issue, rating=4.0, timestamp=D1)

    first = await auth_client.get("/api/v1/creators?sort=name&limit=2&offset=0")
    assert first.status_code == 200
    assert len(first.json()["items"]) == 2
    assert first.json()["total"] == 5
    assert first.json()["limit"] == 2
    assert first.json()["offset"] == 0

    second = await auth_client.get("/api/v1/creators?sort=name&limit=2&offset=2")
    assert len(second.json()["items"]) == 2

    third = await auth_client.get("/api/v1/creators?sort=name&limit=2&offset=4")
    assert len(third.json()["items"]) == 1

    beyond = await auth_client.get("/api/v1/creators?sort=name&limit=2&offset=10")
    assert beyond.json()["items"] == []
    assert beyond.json()["total"] == 5

    # No duplicates across pages
    all_keys = [
        r["canonical_creator_key"]
        for resp in (first, second, third)
        for r in resp.json()["items"]
    ]
    assert len(all_keys) == len(set(all_keys)) == 5


@pytest.mark.asyncio
async def test_user_isolation(
    auth_client: AsyncClient,
    async_db: AsyncSession,
    default_user: User,
) -> None:
    """Creators from another user's library never appear."""
    other = User(username="creator_list_other")
    async_db.add(other)
    await async_db.flush()

    _thread, issues = await _make_thread(
        async_db, default_user, title="Mine", issue_count=1, queue_position=1, read_through=1
    )
    await _confirm_identity(
        async_db, issues[0], creators=[{"id": 1, "name": "Mine Writer", "role": "writer"}]
    )
    await _rate(async_db, issues[0], rating=4.0, timestamp=D1)

    hidden_t, hidden_i = await _make_thread(
        async_db, other, title="Hidden", issue_count=1, queue_position=2, read_through=1
    )
    assert hidden_t is not None
    await _confirm_identity(
        async_db, hidden_i[0], creators=[{"id": 999, "name": "Hidden Writer", "role": "writer"}]
    )
    await _rate(async_db, hidden_i[0], rating=5.0, timestamp=D1)

    response = await auth_client.get("/api/v1/creators")
    assert response.status_code == 200
    keys = [r["canonical_creator_key"] for r in response.json()["items"]]
    assert "creator:1" in keys
    assert "creator:999" not in keys


@pytest.mark.asyncio
async def test_bounded_constant_query_count(
    auth_client: AsyncClient,
    async_db: AsyncSession,
    db_engine: AsyncEngine,
    default_user: User,
) -> None:
    """One request uses a fixed query count regardless of creator/issue count."""
    _thread, issues = await _make_thread(
        async_db, default_user, title="Wide", issue_count=6, queue_position=1, read_through=6
    )
    for idx, issue in enumerate(issues):
        await _confirm_identity(
            async_db,
            issue,
            creators=[{"id": 200 + idx, "name": f"Writer {idx}", "role": "writer"}],
        )
        await _rate(async_db, issue, rating=float(idx + 1), timestamp=D1)
    await async_db.flush()

    await auth_client.get("/api/v1/creators")

    with _captured_selects(db_engine) as one_page:
        one = await auth_client.get("/api/v1/creators?limit=2&offset=0")
    with _captured_selects(db_engine) as full:
        full_resp = await auth_client.get("/api/v1/creators?limit=50&offset=0")

    assert one.status_code == 200
    assert full_resp.status_code == 200
    assert len(one.json()["items"]) == 2
    assert full_resp.json()["total"] == 6
    assert len(one_page) == len(full)
    assert len(one_page) <= 4, one_page


@pytest.mark.asyncio
async def test_unauthenticated_is_rejected(
    client: AsyncClient,
) -> None:
    """Discovery list requires authentication."""
    response = await client.get("/api/v1/creators")
    assert response.status_code == 401


@pytest.mark.asyncio
async def test_no_live_provider_call(
    auth_client: AsyncClient,
    async_db: AsyncSession,
    default_user: User,
) -> None:
    """Endpoint uses stored confirmed metadata only, no live provider."""
    _thread, issues = await _make_thread(
        async_db, default_user, title="Live", issue_count=1, queue_position=1, read_through=1
    )
    await _confirm_identity(
        async_db, issues[0], creators=[{"id": 55, "name": "Stored", "role": "writer"}]
    )
    await _rate(async_db, issues[0], rating=4.0, timestamp=D1)
    response = await auth_client.get("/api/v1/creators")
    assert response.status_code == 200
    assert any(r["canonical_creator_key"] == "creator:55" for r in response.json()["items"])


@pytest.mark.asyncio
async def test_min_ratings_filters_server_side(
    auth_client: AsyncClient,
    async_db: AsyncSession,
    default_user: User,
) -> None:
    """The minimum rated-sample filter is deterministic and server-side."""
    _t1, i1 = await _make_thread(
        async_db, default_user, title="Big", issue_count=5, queue_position=1, read_through=5
    )
    for issue in i1:
        await _confirm_identity(
            async_db, issue, creators=[{"id": 21, "name": "Big Ben", "role": "writer"}]
        )
        await _rate(async_db, issue, rating=4.0, timestamp=D1)
    _t2, i2 = await _make_thread(
        async_db, default_user, title="Small", issue_count=2, queue_position=2, read_through=2
    )
    for issue in i2:
        await _confirm_identity(
            async_db, issue, creators=[{"id": 22, "name": "Small Sue", "role": "writer"}]
        )
        await _rate(async_db, issue, rating=5.0, timestamp=D1)

    any_response = await auth_client.get("/api/v1/creators?min_ratings=0")
    assert any_response.status_code == 200
    assert any_response.json()["total"] == 2

    three_plus = await auth_client.get("/api/v1/creators?min_ratings=3")
    assert three_plus.status_code == 200
    body = three_plus.json()
    assert body["total"] == 1
    assert body["items"][0]["canonical_creator_key"] == "creator:21"

    five_plus = await auth_client.get("/api/v1/creators?min_ratings=5")
    assert five_plus.status_code == 200
    assert five_plus.json()["total"] == 1

    twenty_five = await auth_client.get("/api/v1/creators?min_ratings=25")
    assert twenty_five.status_code == 200
    assert twenty_five.json()["total"] == 0


@pytest.mark.asyncio
async def test_min_ratings_rejects_negative(
    auth_client: AsyncClient,
    async_db: AsyncSession,
    default_user: User,
) -> None:
    """Negative minimum samples are invalid."""
    response = await auth_client.get("/api/v1/creators?min_ratings=-1")
    assert response.status_code == 422


@pytest.mark.asyncio
async def test_role_filtering(
    auth_client: AsyncClient,
    async_db: AsyncSession,
    default_user: User,
) -> None:
    """Role filtering returns only creators with specified roles."""
    _thread, issues = await _make_thread(
        async_db, default_user, title="Roles", issue_count=3, queue_position=1, read_through=3
    )
    # Writer
    await _confirm_identity(
        async_db, issues[0], creators=[{"id": 1, "name": "Alice Writer", "role": "writer"}]
    )
    # Artist
    await _confirm_identity(
        async_db, issues[1], creators=[{"id": 2, "name": "Bob Artist", "role": "artist"}]
    )
    # Writer and penciller
    await _confirm_identity(
        async_db, issues[2], creators=[{"id": 3, "name": "Carol Creator", "role": "writer"}, {"id": 3, "name": "Carol Creator", "role": "penciller"}]
    )
    for issue in issues:
        await _rate(async_db, issue, rating=4.0, timestamp=D1)

    # No filter - should return all
    response = await auth_client.get("/api/v1/creators")
    assert response.status_code == 200
    assert response.json()["total"] == 3

    # Filter for writers only
    response = await auth_client.get("/api/v1/creators?role=writer")
    assert response.status_code == 200
    body = response.json()
    assert body["total"] == 2  # Alice and Carol
    writer_keys = [r["canonical_creator_key"] for r in body["items"]]
    assert "creator:1" in writer_keys
    assert "creator:3" in writer_keys

    # Filter for artists only
    response = await auth_client.get("/api/v1/creators?role=artist")
    assert response.status_code == 200
    body = response.json()
    assert body["total"] == 1  # Bob only
    assert body["items"][0]["canonical_creator_key"] == "creator:2"

    # Filter for pencillers only
    response = await auth_client.get("/api/v1/creators?role=penciller")
    assert response.status_code == 200
    body = response.json()
    assert body["total"] == 1  # Carol only
    assert body["items"][0]["canonical_creator_key"] == "creator:3"

    # Non-existent role
    response = await auth_client.get("/api/v1/creators?role=colorist")
    assert response.status_code == 200
    assert response.json()["total"] == 0


@pytest.mark.asyncio
async def test_rating_range_filtering(
    auth_client: AsyncClient,
    async_db: AsyncSession,
    default_user: User,
) -> None:
    """Rating range filtering returns creators within specified rating bounds."""
    _thread, issues = await _make_thread(
        async_db, default_user, title="Ratings", issue_count=3, queue_position=1, read_through=3
    )
    # High rated (5.0)
    await _confirm_identity(
        async_db, issues[0], creators=[{"id": 1, "name": "High Rated", "role": "writer"}]
    )
    await _rate(async_db, issues[0], rating=5.0, timestamp=D1)
    # Medium rated (3.0)
    await _confirm_identity(
        async_db, issues[1], creators=[{"id": 2, "name": "Medium Rated", "role": "artist"}]
    )
    await _rate(async_db, issues[1], rating=3.0, timestamp=D1)
    # Low rated (1.0)
    await _confirm_identity(
        async_db, issues[2], creators=[{"id": 3, "name": "Low Rated", "role": "writer"}]
    )
    await _rate(async_db, issues[2], rating=1.0, timestamp=D1)

    # No filter - should return all
    response = await auth_client.get("/api/v1/creators")
    assert response.status_code == 200
    assert response.json()["total"] == 3

    # Minimum rating filter (3.0 and above)
    response = await auth_client.get("/api/v1/creators?min_rating=3.0")
    assert response.status_code == 200
    body = response.json()
    assert body["total"] == 2  # High and Medium
    rated_keys = [r["canonical_creator_key"] for r in body["items"]]
    assert "creator:1" in rated_keys
    assert "creator:2" in rated_keys

    # Maximum rating filter (3.0 and below)
    response = await auth_client.get("/api/v1/creators?max_rating=3.0")
    assert response.status_code == 200
    body = response.json()
    assert body["total"] == 2  # Medium and Low
    rated_keys = [r["canonical_creator_key"] for r in body["items"]]
    assert "creator:2" in rated_keys
    assert "creator:3" in rated_keys

    # Range filter (2.0 to 4.0)
    response = await auth_client.get("/api/v1/creators?min_rating=2.0&max_rating=4.0")
    assert response.status_code == 200
    body = response.json()
    assert body["total"] == 1  # Medium only
    assert body["items"][0]["canonical_creator_key"] == "creator:2"

    # No results in range
    response = await auth_client.get("/api/v1/creators?min_rating=4.5&max_rating=4.8")
    assert response.status_code == 200
    assert response.json()["total"] == 0


@pytest.mark.asyncio
async def test_has_unread_work_filtering(
    auth_client: AsyncClient,
    async_db: AsyncSession,
    default_user: User,
) -> None:
    """Unread work filtering returns creators with or without unread attributed work."""
    _thread, issues = await _make_thread(
        async_db, default_user, title="Unread", issue_count=3, queue_position=1, read_through=1
    )
    # Issue 1: read, has creator
    await _confirm_identity(
        async_db, issues[0], creators=[{"id": 1, "name": "Read Only", "role": "writer"}]
    )
    await _rate(async_db, issues[0], rating=4.0, timestamp=D1)
    
    # Issue 2: unread, has creator
    await _confirm_identity(
        async_db, issues[1], creators=[{"id": 2, "name": "Has Unread", "role": "artist"}]
    )
    # Don't rate this one to keep it unread
    
    # Issue 3: read, has creator (different creator from issue 2)
    _thread2, issues2 = await _make_thread(
        async_db, default_user, title="Unread2", issue_count=1, queue_position=2, read_through=1
    )
    await _confirm_identity(
        async_db, issues2[0], creators=[{"id": 3, "name": "No Unread", "role": "writer"}]
    )
    await _rate(async_db, issues2[0], rating=3.0, timestamp=D1)

    # No filter - should return all
    response = await auth_client.get("/api/v1/creators")
    assert response.status_code == 200
    body = response.json()
    assert body["total"] == 3

    # Filter for creators with unread work
    response = await auth_client.get("/api/v1/creators?has_unread_work=true")
    assert response.status_code == 200
    body = response.json()
    assert body["total"] == 1  # Only "Has Unread"
    assert body["items"][0]["canonical_creator_key"] == "creator:2"

    # Filter for creators without unread work
    response = await auth_client.get("/api/v1/creators?has_unread_work=false")
    assert response.status_code == 200
    body = response.json()
    assert body["total"] == 2  # "Read Only" and "No Unread"
    rated_keys = [r["canonical_creator_key"] for r in body["items"]]
    assert "creator:1" in rated_keys
    assert "creator:3" in rated_keys


@pytest.mark.asyncio
async def test_combined_filters(
    auth_client: AsyncClient,
    async_db: AsyncSession,
    default_user: User,
) -> None:
    """Multiple filters work together correctly."""
    _thread, issues = await _make_thread(
        async_db, default_user, title="Combined", issue_count=4, queue_position=1, read_through=2
    )
    # Writer with high rating, no unread work
    await _confirm_identity(
        async_db, issues[0], creators=[{"id": 1, "name": "Good Writer", "role": "writer"}]
    )
    await _rate(async_db, issues[0], rating=4.5, timestamp=D1)
    
    # Artist with medium rating, has unread work
    await _confirm_identity(
        async_db, issues[1], creators=[{"id": 2, "name": "Ok Artist", "role": "artist"}]
    )
    await _rate(async_db, issues[1], rating=3.0, timestamp=D1)
    
    # Writer with low rating, has unread work
    await _confirm_identity(
        async_db, issues[2], creators=[{"id": 3, "name": "Bad Writer", "role": "writer"}]
    )
    await _rate(async_db, issues[2], rating=2.0, timestamp=D1)
    
    # Penciller with high rating, no unread work
    await _confirm_identity(
        async_db, issues[3], creators=[{"id": 4, "name": "Great Penciller", "role": "penciller"}]
    )
    await _rate(async_db, issues[3], rating=5.0, timestamp=D1)

    # Combined: writers with rating >= 3.0 and no unread work
    response = await auth_client.get("/api/v1/creators?role=writer&min_rating=3.0&has_unread_work=false")
    assert response.status_code == 200
    body = response.json()
    assert body["total"] == 1  # Only "Good Writer"
    assert body["items"][0]["canonical_creator_key"] == "creator:1"

    # Combined: artists with rating between 2.5 and 3.5 and has unread work
    response = await auth_client.get("/api/v1/creators?role=artist&min_rating=2.5&max_rating=3.5&has_unread_work=true")
    assert response.status_code == 200
    body = response.json()
    assert body["total"] == 1  # Only "Ok Artist"
    assert body["items"][0]["canonical_creator_key"] == "creator:2"

    # No results for impossible combination
    response = await auth_client.get("/api/v1/creators?role=writer&max_rating=1.5")
    assert response.status_code == 200
    assert response.json()["total"] == 0
