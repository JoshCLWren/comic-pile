"""API coverage for the bounded personal creator summary contract (issue #2028).

One authenticated batch endpoint summarizes the current user's library per
canonical creator key computed from confirmed local ComicVine issue metadata
(no ComicVine call). This module covers the acceptance contract: batch
semantics, latest-effective rating wins, one-rating-per-issue-per-creator
deduplication, headline role classification, explicit coverage completeness,
ownership isolation, issue-only identity filtering, request validation, and
constant query count regardless of the number of requested keys.
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
    """Create an owned thread with contiguous issues.

    Args:
        db: Async database session.
        user: Owner of the thread.
        title: Thread title.
        issue_count: Number of issues to create.
        queue_position: Thread queue position.
        read_through: How many leading issues are marked read.

    Returns:
        The created thread and its issues in position order.
    """
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
    issues: list[Issue] = []
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
    entity_type: str = "issue",
) -> ExternalIdentity:
    """Create a confirmed external identity mapping for one issue.

    Args:
        db: Async database session.
        issue: Issue to map.
        creators: Raw ``creator_credits`` metadata payload.
        entity_type: External identity entity type (``issue`` or ``series``).

    Returns:
        The created external identity.
    """
    global _identity_serial
    _identity_serial += 1
    identity = ExternalIdentity(
        provider="comicvine",
        entity_type=entity_type,
        external_id=f"sv-{_identity_serial}",
        metadata_json={"creator_credits": creators or []},
    )
    db.add(identity)
    await db.flush()
    db.add(
        IssueExternalIdentityMapping(
            issue_id=issue.id,
            external_identity_id=identity.id,
            status="confirmed",
            confidence=1.0,
        )
    )
    await db.flush()
    return identity


async def _rate(
    db: AsyncSession,
    issue: Issue,
    *,
    rating: float,
    timestamp: datetime,
) -> Event:
    """Create one rate event for an issue.

    Args:
        db: Async database session.
        issue: Rated issue.
        rating: Numeric rating.
        timestamp: Event timestamp, used to order effective ratings.

    Returns:
        The created rate event.
    """
    rate_event = Event(
        type="rate",
        thread_id=issue.thread_id,
        issue_id=issue.id,
        issue_number=issue.issue_number,
        rating=rating,
        timestamp=timestamp,
    )
    db.add(rate_event)
    await db.flush()
    return rate_event


async def _summaries(
    client: AsyncClient, keys: list[str]
) -> tuple[int, dict[str, object]]:
    """Call the creator summary endpoint for one comma-separated key batch.

    Args:
        client: Authenticated API client.
        keys: Canonical creator keys to request.

    Returns:
        The HTTP status and parsed JSON response.
    """
    response = await client.get(
        "/api/v1/creators/summaries", params={"keys": ",".join(keys)}
    )
    return response.status_code, response.json()


@pytest.mark.asyncio
async def test_batch_summaries_return_per_creator_rows(
    auth_client: AsyncClient,
    async_db: AsyncSession,
    default_user: User,
) -> None:
    """A batch request summarizes every requested key visible in the library."""
    thread, issues = await _make_thread(
        async_db,
        default_user,
        title="Team Book",
        issue_count=3,
        queue_position=1,
        read_through=3,
    )
    assert thread.user_id == default_user.id
    await _confirm_identity(
        async_db, issues[0], creators=[{"id": 1, "name": "Writer One", "role": "writer"}]
    )
    await _confirm_identity(
        async_db, issues[1], creators=[{"id": 2, "name": "Artist Two", "role": "artist"}]
    )
    await _confirm_identity(
        async_db,
        issues[2],
        creators=[
            {"id": 1, "name": "Writer One", "role": "writer"},
            {"id": 2, "name": "Artist Two", "role": "inker"},
        ],
    )
    await _rate(async_db, issues[0], rating=4.0, timestamp=D1)
    await _rate(async_db, issues[1], rating=5.0, timestamp=D1)
    await _rate(async_db, issues[2], rating=3.0, timestamp=D1)

    status, payload = await _summaries(auth_client, ["creator:1", "creator:2"])

    assert status == 200
    summaries = {row["canonical_creator_key"]: row for row in payload["summaries"]}
    assert set(summaries) == {"creator:1", "creator:2"}
    writer = summaries["creator:1"]
    assert writer["display_name"] == "Writer One"
    assert writer["ratings_count"] == 2
    assert writer["average_rating"] == 3.5
    assert writer["normalized_roles"] == ["writer"]
    artist = summaries["creator:2"]
    assert artist["display_name"] == "Artist Two"
    assert artist["ratings_count"] == 2
    assert artist["average_rating"] == 4.0
    assert sorted(artist["normalized_roles"]) == ["artist", "inker"]


@pytest.mark.asyncio
async def test_rating_edits_count_latest_event_once(
    auth_client: AsyncClient,
    async_db: AsyncSession,
    default_user: User,
) -> None:
    """Multiple rate events for one issue count once with the newest winning."""
    _, issues = await _make_thread(
        async_db, default_user, title="Rerated", issue_count=1, queue_position=1, read_through=1
    )
    await _confirm_identity(
        async_db, issues[0], creators=[{"id": 7, "name": "Ed", "role": "writer"}]
    )
    await _rate(async_db, issues[0], rating=2.0, timestamp=D1)
    await _rate(async_db, issues[0], rating=5.0, timestamp=D2)

    status, payload = await _summaries(auth_client, ["creator:7"])

    assert status == 200
    row = payload["summaries"][0]
    assert row["ratings_count"] == 1
    assert row["average_rating"] == 5.0


@pytest.mark.asyncio
async def test_multiple_roles_on_one_issue_count_once(
    auth_client: AsyncClient,
    async_db: AsyncSession,
    default_user: User,
) -> None:
    """A creator with several roles on one issue is counted once per issue."""
    _, issues = await _make_thread(
        async_db, default_user, title="All Roles", issue_count=2, queue_position=1, read_through=2
    )
    await _confirm_identity(
        async_db,
        issues[0],
        creators=[
            {"id": 9, "name": "Multi", "role": "writer"},
            {"id": 9, "name": "Multi", "role": "artist"},
            {"id": 9, "name": "Multi", "role": "penciller"},
        ],
    )
    await _confirm_identity(
        async_db, issues[1], creators=[{"id": 9, "name": "Multi", "role": "inker"}]
    )
    await _rate(async_db, issues[0], rating=4.0, timestamp=D1)
    await _rate(async_db, issues[1], rating=5.0, timestamp=D1)

    status, payload = await _summaries(auth_client, ["creator:9"])

    assert status == 200
    row = payload["summaries"][0]
    assert row["ratings_count"] == 2
    assert row["average_rating"] == 4.5
    assert sorted(row["normalized_roles"]) == ["artist", "inker", "penciller", "writer"]


@pytest.mark.asyncio
async def test_cover_only_credits_do_not_distort_headline_average(
    auth_client: AsyncClient,
    async_db: AsyncSession,
    default_user: User,
) -> None:
    """Cover/editorial-only credits never gate the headline reading average."""
    _, issues = await _make_thread(
        async_db, default_user, title="Cover Guy", issue_count=2, queue_position=1, read_through=2
    )
    await _confirm_identity(
        async_db, issues[0], creators=[{"id": 3, "name": "Cov", "role": "cover"}]
    )
    await _confirm_identity(
        async_db, issues[1], creators=[{"id": 3, "name": "Cov", "role": "cover"}]
    )
    await _rate(async_db, issues[0], rating=4.0, timestamp=D1)
    await _rate(async_db, issues[1], rating=5.0, timestamp=D1)

    status, payload = await _summaries(auth_client, ["creator:3"])

    assert status == 200
    row = payload["summaries"][0]
    assert row["ratings_count"] == 0
    assert row["average_rating"] is None
    assert row["normalized_roles"] == ["cover"]


@pytest.mark.asyncio
async def test_read_unrated_and_upcoming_counts(
    auth_client: AsyncClient,
    async_db: AsyncSession,
    default_user: User,
) -> None:
    """Read-but-unrated and unread attributed issues are counted separately."""
    _, issues = await _make_thread(
        async_db, default_user, title="Mixed", issue_count=3, queue_position=1, read_through=2
    )
    for issue in issues:
        await _confirm_identity(
            async_db, issue, creators=[{"id": 4, "name": "Mix", "role": "writer"}]
        )
    await _rate(async_db, issues[0], rating=4.0, timestamp=D1)

    status, payload = await _summaries(auth_client, ["creator:4"])

    assert status == 200
    row = payload["summaries"][0]
    assert row["ratings_count"] == 1
    assert row["average_rating"] == 4.0
    assert row["read_unrated_count"] == 1
    assert row["upcoming_count"] == 1


@pytest.mark.asyncio
async def test_coverage_chapters_expose_completeness(
    auth_client: AsyncClient,
    async_db: AsyncSession,
    default_user: User,
) -> None:
    """Coverage chapters report partial metadata as incomplete, not exact."""
    _, issues = await _make_thread(
        async_db, default_user, title="Partial", issue_count=4, queue_position=1, read_through=2
    )
    await _confirm_identity(
        async_db, issues[0], creators=[{"id": 5, "name": "Ada", "role": "writer"}]
    )
    # issues[1] has confirmed ComicVine metadata but no usable creator credits,
    # and issues[2]/issues[3] have no confirmed identity at all.
    await _confirm_identity(async_db, issues[1], creators=[])
    await _rate(async_db, issues[0], rating=4.0, timestamp=D1)
    await _rate(async_db, issues[1], rating=3.0, timestamp=D1)
    await _rate(async_db, issues[2], rating=2.0, timestamp=D1)
    await _rate(async_db, issues[3], rating=5.0, timestamp=D1)

    status, payload = await _summaries(auth_client, ["creator:5"])

    assert status == 200
    rated = payload["coverage"]["rated"]
    assert rated["total"] == 4
    assert rated["with_creator_metadata"] == 1
    assert rated["complete"] is False


@pytest.mark.asyncio
async def test_complete_coverage_chapter_is_exact(
    auth_client: AsyncClient,
    async_db: AsyncSession,
    default_user: User,
) -> None:
    """A fully attributed universe reports complete coverage."""
    _, issues = await _make_thread(
        async_db, default_user, title="Complete", issue_count=2, queue_position=1, read_through=2
    )
    for issue in issues:
        await _confirm_identity(
            async_db, issue, creators=[{"id": 6, "name": "Eve", "role": "writer"}]
        )
        await _rate(async_db, issue, rating=4.0, timestamp=D1)

    status, payload = await _summaries(auth_client, ["creator:6"])

    assert status == 200
    rated = payload["coverage"]["rated"]
    assert rated["total"] == 2
    assert rated["with_creator_metadata"] == 2
    assert rated["complete"] is True


@pytest.mark.asyncio
async def test_unknown_key_returns_empty_row(
    auth_client: AsyncClient,
    async_db: AsyncSession,
    default_user: User,
) -> None:
    """Requesting a key with no library evidence yields an empty row."""
    _, issues = await _make_thread(
        async_db, default_user, title="No Match", issue_count=1, queue_position=1, read_through=1
    )
    await _confirm_identity(
        async_db, issues[0], creators=[{"id": 11, "name": "Zed", "role": "writer"}]
    )
    await _rate(async_db, issues[0], rating=4.0, timestamp=D1)

    status, payload = await _summaries(auth_client, ["creator:999999"])

    assert status == 200
    row = payload["summaries"][0]
    assert row["canonical_creator_key"] == "creator:999999"
    assert row["display_name"] == ""
    assert row["average_rating"] is None
    assert row["ratings_count"] == 0
    assert row["read_unrated_count"] == 0
    assert row["upcoming_count"] == 0


@pytest.mark.asyncio
async def test_other_user_library_is_not_visible(
    auth_client: AsyncClient,
    async_db: AsyncSession,
    default_user: User,
) -> None:
    """Another reader's credited issues never surface through this user's rows."""
    other = User(username="creator-summary-other", created_at=datetime.now(UTC))
    async_db.add(other)
    await async_db.flush()
    _, other_issues = await _make_thread(
        async_db, other, title="Someone Else", issue_count=1, queue_position=1, read_through=1
    )
    await _confirm_identity(
        async_db, other_issues[0], creators=[{"id": 42, "name": "Ghost", "role": "writer"}]
    )
    await _rate(async_db, other_issues[0], rating=5.0, timestamp=D1)

    status, payload = await _summaries(auth_client, ["creator:42"])

    assert status == 200
    row = payload["summaries"][0]
    assert row["average_rating"] is None
    assert row["ratings_count"] == 0
    assert row["upcoming_count"] == 0
    assert row["display_name"] == ""


@pytest.mark.asyncio
async def test_series_entity_credits_do_not_contribute(
    auth_client: AsyncClient,
    async_db: AsyncSession,
    default_user: User,
) -> None:
    """Confirmed series-level credits never leak into per-issue creator stats."""
    _, issues = await _make_thread(
        async_db, default_user, title="Series Only", issue_count=1, queue_position=1, read_through=1
    )
    await _confirm_identity(
        async_db,
        issues[0],
        creators=[{"id": 77, "name": "Series", "role": "writer"}],
        entity_type="series",
    )
    await _rate(async_db, issues[0], rating=4.0, timestamp=D1)

    status, payload = await _summaries(auth_client, ["creator:77"])

    assert status == 200
    row = payload["summaries"][0]
    assert row["average_rating"] is None
    assert row["ratings_count"] == 0
    assert row["display_name"] == ""


@pytest.mark.asyncio
async def test_string_creator_ids_are_coerced(
    auth_client: AsyncClient,
    async_db: AsyncSession,
    default_user: User,
) -> None:
    """Numeric-string creator ids from provider metadata still aggregate."""
    _, issues = await _make_thread(
        async_db, default_user, title="String Id", issue_count=1, queue_position=1, read_through=1
    )
    await _confirm_identity(
        async_db, issues[0], creators=[{"id": "88", "name": "Str", "role": "writer"}]
    )
    await _rate(async_db, issues[0], rating=4.0, timestamp=D1)

    status, payload = await _summaries(auth_client, ["creator:88"])

    assert status == 200
    row = payload["summaries"][0]
    assert row["average_rating"] == 4.0
    assert row["ratings_count"] == 1


@pytest.mark.asyncio
async def test_validation_rejects_bad_requests(
    auth_client: AsyncClient,
) -> None:
    """Missing, malformed, and oversized key batches are rejected with 422."""
    missing = await auth_client.get("/api/v1/creators/summaries")
    assert missing.status_code == 422

    malformed = await auth_client.get(
        "/api/v1/creators/summaries", params={"keys": "creator:abc"}
    )
    assert malformed.status_code == 422

    oversized = await auth_client.get(
        "/api/v1/creators/summaries",
        params={"keys": ",".join(f"creator:{i}" for i in range(1, 250))},
    )
    assert oversized.status_code == 422


@pytest.mark.asyncio
async def test_query_count_is_constant_across_batch_sizes(
    auth_client: AsyncClient,
    async_db: AsyncSession,
    default_user: User,
    db_engine: AsyncEngine,
) -> None:
    """The batch is served by a fixed number of queries regardless of key count."""
    _, issues = await _make_thread(
        async_db, default_user, title="Bounded", issue_count=3, queue_position=1, read_through=3
    )
    await _confirm_identity(
        async_db, issues[0], creators=[{"id": 21, "name": "B1", "role": "writer"}]
    )
    await _confirm_identity(
        async_db, issues[1], creators=[{"id": 22, "name": "B2", "role": "writer"}]
    )
    await _confirm_identity(
        async_db, issues[2], creators=[{"id": 23, "name": "B3", "role": "writer"}]
    )
    await _rate(async_db, issues[0], rating=4.0, timestamp=D1)
    await _rate(async_db, issues[1], rating=4.0, timestamp=D1)
    await _rate(async_db, issues[2], rating=4.0, timestamp=D1)

    with _captured_selects(db_engine) as single_key_selects:
        await _summaries(auth_client, ["creator:21"])
    with _captured_selects(db_engine) as batch_selects:
        await _summaries(auth_client, ["creator:21", "creator:22", "creator:23"])

    assert len(batch_selects) == len(single_key_selects)
    assert 3 <= len(single_key_selects) <= 6