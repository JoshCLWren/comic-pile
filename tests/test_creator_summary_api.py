"""API coverage for the bounded personal creator summary contract (issue #2028).

One authenticated batch endpoint summarizes the current user's library per
canonical creator key computed from confirmed local ComicVine issue metadata
(no ComicVine call). This module covers the acceptance contract: bounded batch
semantics, headline role classification, latest-effective rating semantics,
one-rating-per-issue-per-creator deduplication, explicit coverage completeness,
zero leakage of another user's library state, request validation, and constant
query count regardless of the number of requested keys.
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
            status="confirmed",
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
async def test_batch_summaries_return_multiple_creators(
    auth_client: AsyncClient,
    async_db: AsyncSession,
    default_user: User,
) -> None:
    """A batch request summarizes every requested key visible in the library."""
    thread, issues = await _make_thread(
        async_db, default_user, title="Team Book", issue_count=3, queue_position=1, read_through=3
    )
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
    await _rate(async_db, issues[1], rating=3.0, timestamp=D2)
    await _rate(async_db, issues[2], rating=5.0, timestamp=D3)

    response = await auth_client.get(
        "/api/v1/creators/summaries?keys=creator:1,creator:2,creator:9999"
    )

    assert response.status_code == 200
    body = response.json()
    assert set(body["summaries"]) == {"creator:1", "creator:2"}

    writer = body["summaries"]["creator:1"]
    assert writer["display_name"] == "Writer One"
    assert writer["normalized_roles"] == ["writer"]
    assert writer["ratings_count"] == 2
    assert writer["average_rating"] == pytest.approx(4.5)
    assert writer["read_unrated_count"] == 0
    assert writer["upcoming_count"] == 0

    artist = body["summaries"]["creator:2"]
    assert artist["display_name"] == "Artist Two"
    assert artist["normalized_roles"] == ["artist", "inker"]
    assert artist["ratings_count"] == 2
    assert artist["average_rating"] == pytest.approx(4.0)

    coverage = body["coverage"]
    assert coverage["rated_issues_total"] == 3
    assert coverage["rated_issues_with_creator_metadata"] == 3
    assert coverage["ratings_complete"] is True
    assert coverage["read_unrated_issues_total"] == 0
    assert coverage["unread_issues_total"] == 0


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

    response = await auth_client.get("/api/v1/creators/summaries?keys=creator:7")

    assert response.status_code == 200
    summary = response.json()["summaries"]["creator:7"]
    assert summary["ratings_count"] == 1
    assert summary["average_rating"] == pytest.approx(4.5)
    assert summary["normalized_roles"] == ["artist", "writer"]


@pytest.mark.asyncio
async def test_comma_joined_role_is_split_and_deduplicated(
    auth_client: AsyncClient,
    async_db: AsyncSession,
    default_user: User,
) -> None:
    """Provider role strings split on commas and stay headline-eligible."""
    _thread, issues = await _make_thread(
        async_db, default_user, title="Split", issue_count=1, queue_position=1, read_through=1
    )
    await _confirm_identity(
        async_db,
        issues[0],
        creators=[{"id": 21, "name": "Kelly Sue", "role": "writer, artist"}],
    )
    await _rate(async_db, issues[0], rating=5.0, timestamp=D1)

    response = await auth_client.get("/api/v1/creators/summaries?keys=creator:21")

    assert response.status_code == 200
    summary = response.json()["summaries"]["creator:21"]
    assert summary["normalized_roles"] == ["artist", "writer"]
    assert summary["ratings_count"] == 1
    assert summary["average_rating"] == pytest.approx(5.0)


@pytest.mark.asyncio
async def test_cover_only_credit_never_distorts_headline(
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

    response = await auth_client.get("/api/v1/creators/summaries?keys=creator:8")

    assert response.status_code == 200
    body = response.json()
    summary = body["summaries"]["creator:8"]
    assert summary["display_name"] == "Cover Gal"
    assert summary["normalized_roles"] == ["cover"]
    assert summary["ratings_count"] == 0
    assert summary["average_rating"] is None
    assert body["coverage"]["ratings_complete"] is True


@pytest.mark.asyncio
async def test_unknown_role_stays_unclassified(
    auth_client: AsyncClient,
    async_db: AsyncSession,
    default_user: User,
) -> None:
    """An unknown provider role string is never guessed into a headline role."""
    _thread, issues = await _make_thread(
        async_db, default_user, title="Layout", issue_count=1, queue_position=1, read_through=1
    )
    await _confirm_identity(
        async_db, issues[0], creators=[{"id": 9, "name": "Lay Out", "role": "layout"}]
    )
    await _rate(async_db, issues[0], rating=4.0, timestamp=D1)

    response = await auth_client.get("/api/v1/creators/summaries?keys=creator:9")

    assert response.status_code == 200
    summary = response.json()["summaries"]["creator:9"]
    assert summary["normalized_roles"] == ["layout"]
    assert summary["ratings_count"] == 0
    assert summary["average_rating"] is None


@pytest.mark.asyncio
async def test_latest_effective_rating_wins(
    auth_client: AsyncClient,
    async_db: AsyncSession,
    default_user: User,
) -> None:
    """The latest effective rate event determines an issue's single rating."""
    _thread, issues = await _make_thread(
        async_db, default_user, title="Rerated", issue_count=1, queue_position=1, read_through=1
    )
    await _confirm_identity(
        async_db, issues[0], creators=[{"id": 10, "name": "Retry Roe", "role": "writer"}]
    )
    await _rate(async_db, issues[0], rating=4.0, timestamp=D1)
    await _rate(async_db, issues[0], rating=2.0, timestamp=D2)

    response = await auth_client.get("/api/v1/creators/summaries?keys=creator:10")

    assert response.status_code == 200
    summary = response.json()["summaries"]["creator:10"]
    assert summary["ratings_count"] == 1
    assert summary["average_rating"] == pytest.approx(2.0)


@pytest.mark.asyncio
async def test_average_null_and_read_unrated_and_upcoming_counts(
    auth_client: AsyncClient,
    async_db: AsyncSession,
    default_user: User,
) -> None:
    """Unrated issues split into read-but-unrated and upcoming counts."""
    _thread, issues = await _make_thread(
        async_db, default_user, title="Mixed", issue_count=4, queue_position=1, read_through=2
    )
    for issue in issues[:3]:
        await _confirm_identity(
            async_db, issue, creators=[{"id": 5, "name": "Courtney C.", "role": "writer"}]
        )
    await _rate(async_db, issues[0], rating=4.0, timestamp=D1)
    await _confirm_identity(
        async_db,
        issues[3],
        metadata={"volume_id": "no-credits-here"},
    )

    response = await auth_client.get("/api/v1/creators/summaries?keys=creator:5")

    assert response.status_code == 200
    body = response.json()
    summary = body["summaries"]["creator:5"]
    assert summary["ratings_count"] == 1
    assert summary["average_rating"] == pytest.approx(4.0)
    assert summary["read_unrated_count"] == 1
    assert summary["upcoming_count"] == 1

    coverage = body["coverage"]
    assert coverage["ratings_complete"] is True
    assert coverage["read_unrated_complete"] is True
    assert coverage["unread_issues_total"] == 2
    assert coverage["unread_issues_with_creator_metadata"] == 1
    assert coverage["upcoming_complete"] is False


@pytest.mark.asyncio
async def test_partial_coverage_never_counts_absence_as_evidence(
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
    await _confirm_identity(
        async_db,
        issues[1],
        creators=[{"id": 4, "name": "Bo B.", "role": "artist"}],
        provider="marvel",
    )
    await _rate(async_db, issues[0], rating=5.0, timestamp=D1)
    await _rate(async_db, issues[1], rating=4.0, timestamp=D2)
    await _rate(async_db, issues[2], rating=3.0, timestamp=D3)

    response = await auth_client.get("/api/v1/creators/summaries?keys=creator:3")

    assert response.status_code == 200
    coverage = response.json()["coverage"]
    assert coverage["rated_issues_total"] == 3
    assert coverage["rated_issues_with_creator_metadata"] == 1
    assert coverage["ratings_complete"] is False


@pytest.mark.asyncio
async def test_foreign_and_unknown_keys_are_omitted(
    auth_client: AsyncClient,
    async_db: AsyncSession,
    default_user: User,
) -> None:
    """Another user's creator keys never leak into the authenticated response."""
    other_user = User(username="creator_summary_other")
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

    response = await auth_client.get(
        "/api/v1/creators/summaries?keys=creator:1,creator:999,creator:424242"
    )

    assert response.status_code == 200
    body = response.json()
    assert set(body["summaries"]) == {"creator:1"}
    assert body["summaries"]["creator:1"]["ratings_count"] == 1
    assert body["coverage"]["rated_issues_total"] == 1


@pytest.mark.asyncio
async def test_empty_library_returns_empty_summaries_and_vacuous_coverage(
    auth_client: AsyncClient,
    async_db: AsyncSession,
    default_user: User,
) -> None:
    """An empty library yields no summaries and zero totals with complete True."""
    response = await auth_client.get("/api/v1/creators/summaries?keys=creator:1")

    assert response.status_code == 200
    body = response.json()
    assert body["summaries"] == {}
    assert body["coverage"]["rated_issues_total"] == 0
    assert body["coverage"]["ratings_complete"] is True
    assert body["coverage"]["upcoming_complete"] is True


@pytest.mark.asyncio
async def test_duplicate_keys_are_deduplicated(
    auth_client: AsyncClient,
    async_db: AsyncSession,
    default_user: User,
) -> None:
    """Repeated and whitespace-padded keys collapse to one summary."""
    _thread, issues = await _make_thread(
        async_db, default_user, title="Dupes", issue_count=1, queue_position=1, read_through=1
    )
    await _confirm_identity(
        async_db, issues[0], creators=[{"id": 12, "name": "Twice T.", "role": "writer"}]
    )
    await _rate(async_db, issues[0], rating=4.0, timestamp=D1)

    response = await auth_client.get("/api/v1/creators/summaries?keys=creator:12,%20creator:12")

    assert response.status_code == 200
    assert list(response.json()["summaries"]) == ["creator:12"]


@pytest.mark.asyncio
async def test_creator_key_validation_errors(
    auth_client: AsyncClient,
) -> None:
    """Malformed, empty, or unbounded keys parameters are rejected."""
    missing = await auth_client.get("/api/v1/creators/summaries")
    assert missing.status_code == 400

    empty = await auth_client.get("/api/v1/creators/summaries?keys=")
    assert empty.status_code == 400

    at_limit = await auth_client.get(
        "/api/v1/creators/summaries?keys=" + ",".join(f"creator:{i}" for i in range(1, 51))
    )
    assert at_limit.status_code == 200

    too_many = await auth_client.get(
        "/api/v1/creators/summaries?keys=" + ",".join(f"creator:{i}" for i in range(1, 52))
    )
    assert too_many.status_code == 400
    assert "at most 50" in too_many.json()["detail"]

    for bad_key in ["writer:1", "creator:abc", "creator:", "creator:1:2"]:
        response = await auth_client.get(f"/api/v1/creators/summaries?keys={bad_key}")
        assert response.status_code == 400, bad_key
        assert "creator:<external-person-id>" in response.json()["detail"]


@pytest.mark.asyncio
async def test_unauthenticated_request_is_rejected(
    client: AsyncClient,
) -> None:
    """The batch endpoint requires an authenticated user."""
    response = await client.get("/api/v1/creators/summaries?keys=creator:1")
    assert response.status_code == 401


@pytest.mark.asyncio
async def test_bounded_constant_query_count(
    auth_client: AsyncClient,
    async_db: AsyncSession,
    db_engine: AsyncEngine,
    default_user: User,
) -> None:
    """One request serves any key count with a fixed, constant query count."""
    _thread, issues = await _make_thread(
        async_db, default_user, title="Wide", issue_count=6, queue_position=1, read_through=6
    )
    for index, issue in enumerate(issues, start=1):
        await _confirm_identity(
            async_db,
            issue,
            creators=[{"id": index + 100, "name": f"Writer {index}", "role": "writer"}],
        )
        await _rate(async_db, issue, rating=float(index), timestamp=D1)
    await async_db.flush()

    await auth_client.get("/api/v1/creators/summaries?keys=creator:101")

    with _captured_selects(db_engine) as one_key_selects:
        one_key = await auth_client.get("/api/v1/creators/summaries?keys=creator:101")
    with _captured_selects(db_engine) as six_key_selects:
        six_keys = await auth_client.get(
            "/api/v1/creators/summaries?keys="
            + ",".join(f"creator:{index + 100}" for index in range(1, 7))
        )

    assert one_key.status_code == 200
    assert six_keys.status_code == 200
    assert len(six_keys.json()["summaries"]) == 6
    assert len(one_key_selects) == len(six_key_selects)
    assert len(one_key_selects) <= 4, one_key_selects