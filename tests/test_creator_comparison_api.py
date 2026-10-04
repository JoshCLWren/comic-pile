"""API coverage for the bounded personal creator comparison contract (issue #3091).

One authenticated batch endpoint compares 2-4 canonical creators using the
same explainable personal analytics already available on creator pages (no
ComicVine call). This module covers the acceptance contract: bounded batch
semantics with a single request for all keys, headline rating/median/sample
semantics shared with creator detail, latest-effective rating in series
aggregates, explicit insufficient-data flags, unknown-key omission without
leakage, and request validation.
"""

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
async def test_compare_returns_bounded_side_by_side_metrics(
    auth_client: AsyncClient,
    async_db: AsyncSession,
    default_user: User,
) -> None:
    """One batch request compares every requested key visible in the library."""
    _thread_a, issues_a = await _make_thread(
        async_db, default_user, title="Team Book", issue_count=3, queue_position=1, read_through=3
    )
    for issue in issues_a:
        await _confirm_identity(
            async_db, issue, creators=[{"id": 1, "name": "Writer One", "role": "writer"}]
        )
    await _rate(async_db, issues_a[0], rating=4.0, timestamp=D1)
    await _rate(async_db, issues_a[1], rating=5.0, timestamp=D2)
    await _rate(async_db, issues_a[2], rating=3.0, timestamp=D3)

    _thread_b, issues_b = await _make_thread(
        async_db, default_user, title="Solo Book", issue_count=3, queue_position=2, read_through=2
    )
    for issue in issues_b:
        await _confirm_identity(
            async_db, issue, creators=[{"id": 2, "name": "Artist Two", "role": "artist"}]
        )
    await _rate(async_db, issues_b[0], rating=5.0, timestamp=D1)

    response = await auth_client.get(
        "/api/v1/creators/compare?keys=creator:1,creator:2,creator:9999"
    )

    assert response.status_code == 200
    body = response.json()
    assert set(body["comparisons"]) == {"creator:1", "creator:2"}

    writer = body["comparisons"]["creator:1"]
    assert writer["display_name"] == "Writer One"
    assert writer["normalized_roles"] == ["writer"]
    assert writer["ratings_count"] == 3
    assert writer["average_rating"] == pytest.approx(4.0)
    assert writer["median_rating"] == pytest.approx(4.0)
    assert writer["rating_distribution"] == {"4": 1, "5": 1, "3": 1}
    assert writer["top_rating_rate"] == pytest.approx(1 / 3, abs=1e-3)
    assert writer["role_stats"] == [
        {"role": "writer", "issue_count": 3, "average_rating": pytest.approx(4.0)}
    ]
    assert writer["insufficient_data"] is False
    assert writer["strongest_series"][0]["thread_title"] == "Team Book"
    assert writer["strongest_series"][0]["issue_count"] == 3
    assert writer["strongest_series"][0]["average_rating"] == pytest.approx(4.0)

    artist = body["comparisons"]["creator:2"]
    assert artist["ratings_count"] == 1
    assert artist["average_rating"] == pytest.approx(5.0)
    assert artist["insufficient_data"] is True
    assert artist["unread_upcoming_count"] == 1
    assert artist["read_unrated_count"] == 1

    assert body["insufficient_data_keys"] == ["creator:2"]

    coverage = body["coverage"]
    assert coverage["rated_issues_total"] == 4
    assert coverage["rated_issues_with_creator_metadata"] == 4
    assert coverage["ratings_complete"] is True
    assert coverage["read_unrated_issues_total"] == 1
    assert coverage["unread_issues_total"] == 1


@pytest.mark.asyncio
async def test_compare_validates_key_bounds(auth_client: AsyncClient) -> None:
    """Comparison requires 2-4 well-formed canonical keys."""
    assert (
        await auth_client.get("/api/v1/creators/compare?keys=creator:1")
    ).status_code == 400
    assert (
        await auth_client.get(
            "/api/v1/creators/compare?keys=creator:1,creator:2,creator:3,creator:4,creator:5"
        )
    ).status_code == 400
    assert (
        await auth_client.get("/api/v1/creators/compare?keys=creator:1,not-a-key")
    ).status_code == 400
    assert (await auth_client.get("/api/v1/creators/compare")).status_code == 400


@pytest.mark.asyncio
async def test_coverage_ignores_creators_outside_the_comparison(
    auth_client: AsyncClient,
    async_db: AsyncSession,
    default_user: User,
) -> None:
    """Confirmed metadata naming unselected creators is still complete coverage.

    Coverage describes the whole owned library, not the compared subset. A
    rated issue whose confirmed credits name only creators outside the current
    selection is fully attributed, so the comparison must not report it as
    missing metadata or present the totals as a lower bound.
    """
    _thread, issues = await _make_thread(
        async_db, default_user, title="Mixed", issue_count=2, queue_position=1, read_through=2
    )
    await _confirm_identity(
        async_db, issues[0], creators=[{"id": 1, "name": "Writer One", "role": "writer"}]
    )
    await _confirm_identity(
        async_db, issues[1], creators=[{"id": 77, "name": "Unrelated Letterer", "role": "letterer"}]
    )
    await _rate(async_db, issues[0], rating=4.0, timestamp=D1)
    await _rate(async_db, issues[1], rating=5.0, timestamp=D2)

    _thread_b, issues_b = await _make_thread(
        async_db, default_user, title="Other", issue_count=1, queue_position=2, read_through=1
    )
    await _confirm_identity(
        async_db, issues_b[0], creators=[{"id": 2, "name": "Artist Two", "role": "artist"}]
    )

    response = await auth_client.get("/api/v1/creators/compare?keys=creator:1,creator:2")

    assert response.status_code == 200
    body = response.json()
    assert set(body["comparisons"]) == {"creator:1", "creator:2"}

    coverage = body["coverage"]
    assert coverage["rated_issues_total"] == 2
    assert coverage["rated_issues_with_creator_metadata"] == 2
    assert coverage["ratings_complete"] is True


@pytest.mark.asyncio
async def test_coverage_reports_true_partial_metadata(
    auth_client: AsyncClient,
    async_db: AsyncSession,
    default_user: User,
) -> None:
    """An owned rated issue with no confirmed metadata is a real lower bound."""
    _thread, issues = await _make_thread(
        async_db, default_user, title="Unattributed", issue_count=2, queue_position=1, read_through=2
    )
    await _confirm_identity(
        async_db, issues[0], creators=[{"id": 1, "name": "Writer One", "role": "writer"}]
    )
    await _confirm_identity(async_db, issues[1], metadata={"creator_credits": []})
    await _rate(async_db, issues[0], rating=4.0, timestamp=D1)
    await _rate(async_db, issues[1], rating=5.0, timestamp=D2)

    _thread_b, issues_b = await _make_thread(
        async_db, default_user, title="Other", issue_count=1, queue_position=2, read_through=1
    )
    await _confirm_identity(
        async_db, issues_b[0], creators=[{"id": 2, "name": "Artist Two", "role": "artist"}]
    )

    response = await auth_client.get("/api/v1/creators/compare?keys=creator:1,creator:2")

    assert response.status_code == 200
    coverage = response.json()["coverage"]
    assert coverage["rated_issues_total"] == 2
    assert coverage["rated_issues_with_creator_metadata"] == 1
    assert coverage["ratings_complete"] is False


@pytest.mark.asyncio
async def test_compare_issues_a_creator_independent_query_count(
    auth_client: AsyncClient,
    async_db: AsyncSession,
    db_engine: AsyncEngine,
    default_user: User,
) -> None:
    """Comparing more creators must not add one query per creator.

    Issue #3091 requires a bounded batch contract rather than a detail request
    per selected creator. Every comparison must be served by the same small,
    fixed number of SELECTs whether two or four creators are selected.
    """
    for creator_index in range(1, 5):
        _thread, issues = await _make_thread(
            async_db,
            default_user,
            title=f"Book {creator_index}",
            issue_count=1,
            queue_position=creator_index,
            read_through=1,
        )
        await _confirm_identity(
            async_db,
            issues[0],
            creators=[{"id": creator_index, "name": f"Creator {creator_index}", "role": "writer"}],
        )
        await _rate(async_db, issues[0], rating=4.0, timestamp=D1)

    sync_engine = db_engine.sync_engine
    counted: list[str] = []

    def _record(
        _conn: object,
        _cursor: object,
        statement: str,
        _params: object,
        _context: object,
        _executemany: bool,
    ) -> None:
        counted.append(statement)

    event.listen(sync_engine, "before_cursor_execute", _record)
    try:
        two = await auth_client.get("/api/v1/creators/compare?keys=creator:1,creator:2")
        two_creator_selects = [s for s in counted if s.lstrip().upper().startswith("SELECT")]
        counted.clear()
        four = await auth_client.get(
            "/api/v1/creators/compare?keys=creator:1,creator:2,creator:3,creator:4"
        )
        four_creator_selects = [s for s in counted if s.lstrip().upper().startswith("SELECT")]
    finally:
        event.remove(sync_engine, "before_cursor_execute", _record)

    assert two.status_code == 200
    assert four.status_code == 200
    assert len(two.json()["comparisons"]) == 2
    assert len(four.json()["comparisons"]) == 4
    # Auth lookup plus the three fixed batch queries; never one per creator.
    assert len(four_creator_selects) == len(two_creator_selects)
    assert len(four_creator_selects) <= 4, four_creator_selects


@pytest.mark.asyncio
async def test_series_average_uses_latest_effective_rating(
    auth_client: AsyncClient,
    async_db: AsyncSession,
    default_user: User,
) -> None:
    """A re-rated issue contributes its current rating once to series averages."""
    _thread, issues = await _make_thread(
        async_db, default_user, title="Rerated", issue_count=1, queue_position=1, read_through=1
    )
    await _confirm_identity(
        async_db,
        issues[0],
        creators=[
            {"id": 1, "name": "Writer One", "role": "writer"},
            {"id": 2, "name": "Artist Two", "role": "artist"},
        ],
    )
    await _rate(async_db, issues[0], rating=1.0, timestamp=D1)
    await _rate(async_db, issues[0], rating=5.0, timestamp=D2)

    response = await auth_client.get("/api/v1/creators/compare?keys=creator:1,creator:2")

    assert response.status_code == 200
    comparisons = response.json()["comparisons"]
    for key in ("creator:1", "creator:2"):
        assert comparisons[key]["average_rating"] == pytest.approx(5.0)
        assert comparisons[key]["strongest_series"][0]["average_rating"] == pytest.approx(5.0)
