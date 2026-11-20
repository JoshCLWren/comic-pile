"""API coverage for the explainable personal taste-discovery contract (#3093).

One authenticated endpoint returns the complete fixed set of personal
taste-discovery views (consistently loved, polarizing, most read, highest
top-rating rate, great average / small sample, loved with unread work, and
warmed to / cooled on). This module covers the acceptance contract: every view
is present and deterministic, thresholds and minimum samples are enforced,
small samples are excluded from reliability-implying views, equal scores break
ties by canonical key, partial creator metadata is reported truthfully as a
lower bound, results are bounded, reasons match the reported metrics, data never
crosses users, and no provider or LLM request participates.
"""

from collections.abc import Iterator
from contextlib import contextmanager
from datetime import UTC, datetime, timedelta
from typing import Any

import pytest
from httpx import AsyncClient
from sqlalchemy import event as sqla_event
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession

from app.constants import (
    DISCOVERY_MIN_RELIABLE_SAMPLE,
    MAX_DISCOVERY_ENTRIES,
)
from app.models import Event, Issue, Thread, User
from app.models.external_identity import ExternalIdentity, IssueExternalIdentityMapping
from app.schemas.creator_discovery import CreatorDiscoveryMode

DISCOVERIES_URL = "/api/v1/creators/discoveries"

D1 = datetime(2026, 3, 1, tzinfo=UTC)

#: Canonical display order of the views, asserted on every response.
EXPECTED_MODE_ORDER = [mode.value for mode in CreatorDiscoveryMode]

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
    creators: list[dict[str, object]],
) -> None:
    """Create one confirmed ComicVine issue identity mapping."""
    global _identity_serial
    _identity_serial += 1
    identity = ExternalIdentity(
        provider="comicvine",
        entity_type="issue",
        external_id=f"sv-discovery-{_identity_serial}",
        metadata_json={"creator_credits": creators},
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
) -> None:
    """Create one rate event for an issue."""
    db.add(
        Event(
            type="rate",
            thread_id=issue.thread_id,
            issue_id=issue.id,
            issue_number=issue.issue_number,
            rating=rating,
            timestamp=timestamp,
        )
    )
    await db.flush()


async def _build_creator(
    db: AsyncSession,
    user: User,
    *,
    queue_position: int,
    creator_id: int,
    name: str,
    ratings: list[float],
    role: str = "writer",
    unread_issues: int = 0,
    start: datetime = D1,
) -> Thread:
    """Create a thread whose rated issues credit one creator.

    Args:
        db: Async database session.
        user: Owner of the created library.
        queue_position: Thread ordering position.
        creator_id: Stable external person id to credit.
        name: Creator display name.
        ratings: Effective ratings, one per read issue, in reading order.
        role: Provider role string for the credit.
        unread_issues: Extra unread credited issues appended after the rated ones.
        start: Timestamp of the first rate event; later events step one day.

    Returns:
        The created thread.
    """
    issue_count = len(ratings) + unread_issues
    thread, issues = await _make_thread(
        db,
        user,
        title=f"Run {creator_id}",
        issue_count=issue_count,
        queue_position=queue_position,
        read_through=len(ratings),
    )
    for issue in issues:
        await _confirm_identity(
            db, issue, creators=[{"id": creator_id, "name": name, "role": role}]
        )
    for index, (issue, rating) in enumerate(zip(issues, ratings, strict=False)):
        await _rate(db, issue, rating=rating, timestamp=start + timedelta(days=index))
    return thread


def _views_by_mode(body: dict[str, Any]) -> dict[str, dict[str, Any]]:
    """Index a discovery response's views by their stable mode."""
    return {view["mode"]: view for view in body["views"]}


def _keys(view: dict[str, Any]) -> list[str]:
    """Return the ordered canonical creator keys of one view."""
    return [entry["canonical_creator_key"] for entry in view["entries"]]


@contextmanager
def _captured_selects(db_engine: AsyncEngine) -> Iterator[list[str]]:
    """Record every SELECT statement executed on the engine during the block."""
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

    sqla_event.listen(db_engine.sync_engine, "before_cursor_execute", _capture)
    try:
        yield select_statements
    finally:
        sqla_event.remove(db_engine.sync_engine, "before_cursor_execute", _capture)


@pytest.mark.asyncio
async def test_discoveries_requires_authentication(client: AsyncClient) -> None:
    """Unauthenticated requests never aggregate a library."""
    assert (await client.get(DISCOVERIES_URL)).status_code == 401


@pytest.mark.asyncio
async def test_empty_library_returns_every_view_empty(auth_client: AsyncClient) -> None:
    """A library with no data still returns every view, empty and well-formed."""
    response = await auth_client.get(DISCOVERIES_URL)

    assert response.status_code == 200
    body = response.json()

    assert [view["mode"] for view in body["views"]] == EXPECTED_MODE_ORDER
    for view in body["views"]:
        assert view["entries"] == []
        assert view["total"] == 0
        assert view["truncated"] is False
        assert view["title"] != ""
        assert view["description"] != ""
        assert view["min_sample"] >= 0
        assert view["max_entries"] == MAX_DISCOVERY_ENTRIES

    assert body["minimum_reliable_sample"] == DISCOVERY_MIN_RELIABLE_SAMPLE
    assert body["max_entries_per_view"] == MAX_DISCOVERY_ENTRIES
    assert body["coverage"] == {
        "rated_issues_total": 0,
        "rated_issues_with_creator_metadata": 0,
        "ratings_complete": True,
    }


@pytest.mark.asyncio
async def test_consistently_loved_requires_sample_average_and_low_dispersion(
    auth_client: AsyncClient,
    async_db: AsyncSession,
    default_user: User,
) -> None:
    """Only a reliable sample with a high, tightly clustered average qualifies."""
    # Reliable, high, tight: qualifies.
    await _build_creator(
        async_db,
        default_user,
        queue_position=1,
        creator_id=100,
        name="Steady Star",
        ratings=[5.0, 5.0, 5.0, 5.0, 5.0],
    )
    # Small sample: excluded from a reliability-implying view.
    await _build_creator(
        async_db,
        default_user,
        queue_position=2,
        creator_id=101,
        name="Thin Sample",
        ratings=[5.0, 5.0],
    )
    # Reliable but dispersed: excluded.
    await _build_creator(
        async_db,
        default_user,
        queue_position=3,
        creator_id=102,
        name="Erratic",
        ratings=[5.0, 3.0, 5.0, 3.0, 5.0],
    )
    # Reliable but mediocre: excluded.
    await _build_creator(
        async_db,
        default_user,
        queue_position=4,
        creator_id=103,
        name="Average",
        ratings=[3.0, 3.0, 3.0, 3.0, 3.0],
    )

    body = (await auth_client.get(DISCOVERIES_URL)).json()
    view = _views_by_mode(body)[CreatorDiscoveryMode.CONSISTENTLY_LOVED.value]

    assert _keys(view) == ["creator:100"]
    assert view["min_sample"] == DISCOVERY_MIN_RELIABLE_SAMPLE
    entry = view["entries"][0]
    assert entry["rated_issue_count"] == 5
    assert entry["average_rating"] == pytest.approx(5.0)
    assert entry["rating_stddev"] == pytest.approx(0.0)


@pytest.mark.asyncio
async def test_polarizing_requires_wide_spread_on_reliable_sample(
    auth_client: AsyncClient,
    async_db: AsyncSession,
    default_user: User,
) -> None:
    """A wide rating spread on a reliable sample qualifies; a narrow one does not."""
    await _build_creator(
        async_db,
        default_user,
        queue_position=1,
        creator_id=110,
        name="Split Opinion",
        ratings=[5.0, 2.0, 3.0, 5.0, 2.0],
    )
    await _build_creator(
        async_db,
        default_user,
        queue_position=2,
        creator_id=111,
        name="Consensus",
        ratings=[4.0, 4.0, 5.0, 4.0, 4.0],
    )

    body = (await auth_client.get(DISCOVERIES_URL)).json()
    view = _views_by_mode(body)[CreatorDiscoveryMode.POLARIZING.value]

    assert _keys(view) == ["creator:110"]
    entry = view["entries"][0]
    assert entry["rating_spread"] == pytest.approx(3.0)
    assert entry["min_rating"] == pytest.approx(2.0)
    assert entry["max_rating"] == pytest.approx(5.0)


@pytest.mark.asyncio
async def test_most_read_orders_by_rated_sample_size(
    auth_client: AsyncClient,
    async_db: AsyncSession,
    default_user: User,
) -> None:
    """Most-read ranks by the largest rated sample, largest first."""
    await _build_creator(
        async_db, default_user, queue_position=1, creator_id=120, name="Prolific", ratings=[3.0] * 5
    )
    await _build_creator(
        async_db, default_user, queue_position=2, creator_id=121, name="Regular", ratings=[3.0] * 3
    )
    await _build_creator(
        async_db, default_user, queue_position=3, creator_id=122, name="Newcomer", ratings=[3.0]
    )

    body = (await auth_client.get(DISCOVERIES_URL)).json()
    view = _views_by_mode(body)[CreatorDiscoveryMode.MOST_READ.value]

    assert _keys(view) == ["creator:120", "creator:121", "creator:122"]
    assert view["min_sample"] == 1
    assert [entry["rated_issue_count"] for entry in view["entries"]] == [5, 3, 1]


@pytest.mark.asyncio
async def test_highest_top_rating_rate_requires_minimum_share(
    auth_client: AsyncClient,
    async_db: AsyncSession,
    default_user: User,
) -> None:
    """The top-rating view requires a reliable sample and most ratings at the top."""
    await _build_creator(
        async_db,
        default_user,
        queue_position=1,
        creator_id=130,
        name="Crowd Pleaser",
        ratings=[5.0, 5.0, 5.0, 4.0, 4.0],
    )
    await _build_creator(
        async_db,
        default_user,
        queue_position=2,
        creator_id=131,
        name="Mixed",
        ratings=[5.0, 4.0, 4.0, 4.0, 4.0],
    )
    # Perfect rate but below the reliable floor: excluded from this view.
    await _build_creator(
        async_db,
        default_user,
        queue_position=3,
        creator_id=132,
        name="Flash In The Pan",
        ratings=[5.0, 5.0],
    )

    body = (await auth_client.get(DISCOVERIES_URL)).json()
    views = _views_by_mode(body)
    view = views[CreatorDiscoveryMode.HIGHEST_TOP_RATING_RATE.value]

    assert _keys(view) == ["creator:130"]
    assert view["entries"][0]["top_rating_count"] == 3
    assert view["entries"][0]["top_rating_rate"] == pytest.approx(3 / 5, abs=1e-3)
    # The excluded creator still surfaces in the explicitly small-sample view.
    small = views[CreatorDiscoveryMode.GREAT_AVERAGE_SMALL_SAMPLE.value]
    assert "creator:132" in _keys(small)


@pytest.mark.asyncio
async def test_great_average_small_sample_is_below_reliability_floor(
    auth_client: AsyncClient,
    async_db: AsyncSession,
    default_user: User,
) -> None:
    """The small-sample view holds promising thin evidence only, below the floor."""
    await _build_creator(
        async_db, default_user, queue_position=1, creator_id=140, name="One Great", ratings=[5.0]
    )
    await _build_creator(
        async_db, default_user, queue_position=2, creator_id=141, name="Two Great", ratings=[4.0, 4.0]
    )
    await _build_creator(
        async_db, default_user, queue_position=3, creator_id=142, name="Two Weak", ratings=[2.0, 2.0]
    )
    await _build_creator(
        async_db,
        default_user,
        queue_position=4,
        creator_id=143,
        name="Fully Proven",
        ratings=[5.0, 5.0, 5.0, 5.0, 5.0],
    )

    body = (await auth_client.get(DISCOVERIES_URL)).json()
    view = _views_by_mode(body)[CreatorDiscoveryMode.GREAT_AVERAGE_SMALL_SAMPLE.value]

    assert _keys(view) == ["creator:140", "creator:141"]
    assert view["min_sample"] == 1
    for entry in view["entries"]:
        assert entry["rated_issue_count"] < DISCOVERY_MIN_RELIABLE_SAMPLE


@pytest.mark.asyncio
async def test_loved_with_unread_requires_high_average_and_unread_work(
    auth_client: AsyncClient,
    async_db: AsyncSession,
    default_user: User,
) -> None:
    """Loved-with-unread pairs a high average with at least one unread issue."""
    await _build_creator(
        async_db,
        default_user,
        queue_position=1,
        creator_id=150,
        name="Backlog Favorite",
        ratings=[5.0, 5.0],
        unread_issues=1,
    )
    await _build_creator(
        async_db,
        default_user,
        queue_position=2,
        creator_id=151,
        name="Caught Up",
        ratings=[5.0, 5.0, 5.0],
    )

    body = (await auth_client.get(DISCOVERIES_URL)).json()
    view = _views_by_mode(body)[CreatorDiscoveryMode.LOVED_WITH_UNREAD.value]

    assert _keys(view) == ["creator:150"]
    assert view["entries"][0]["unread_issue_count"] == 1


@pytest.mark.asyncio
async def test_moved_over_time_detects_warming_and_cooling(
    auth_client: AsyncClient,
    async_db: AsyncSession,
    default_user: User,
) -> None:
    """Dated histories far enough apart expose warming and cooling."""
    await _build_creator(
        async_db,
        default_user,
        queue_position=1,
        creator_id=160,
        name="Warmed Up",
        ratings=[2.0, 2.0, 2.0, 5.0, 5.0, 5.0],
    )
    await _build_creator(
        async_db,
        default_user,
        queue_position=2,
        creator_id=161,
        name="Cooled Down",
        ratings=[5.0, 5.0, 5.0, 2.0, 2.0, 2.0],
    )
    # Big enough sample but no meaningful change: excluded.
    await _build_creator(
        async_db,
        default_user,
        queue_position=3,
        creator_id=162,
        name="Flat",
        ratings=[4.0, 4.0, 4.0, 4.0, 4.0, 4.0],
    )
    # Meaningful change but below the dated-sample floor: excluded.
    await _build_creator(
        async_db,
        default_user,
        queue_position=4,
        creator_id=163,
        name="Too Few Dates",
        ratings=[2.0, 2.0, 5.0, 5.0, 5.0],
    )

    body = (await auth_client.get(DISCOVERIES_URL)).json()
    view = _views_by_mode(body)[CreatorDiscoveryMode.MOVED_OVER_TIME.value]

    assert _keys(view) == ["creator:160", "creator:161"]
    assert view["min_sample"] == 6
    directions = {
        entry["canonical_creator_key"]: entry["trend_direction"] for entry in view["entries"]
    }
    assert directions == {"creator:160": "warmed", "creator:161": "cooled"}
    warmed = view["entries"][0]
    assert warmed["earlier_average_rating"] == pytest.approx(2.0)
    assert warmed["recent_average_rating"] == pytest.approx(5.0)
    assert warmed["trend_delta"] == pytest.approx(3.0)
    assert warmed["trend_sample_count"] == 6


@pytest.mark.asyncio
async def test_insufficient_data_yields_empty_reliability_views(
    auth_client: AsyncClient,
    async_db: AsyncSession,
    default_user: User,
) -> None:
    """A single rated issue cannot satisfy any reliability-implying view."""
    await _build_creator(
        async_db, default_user, queue_position=1, creator_id=170, name="Solo", ratings=[5.0]
    )

    body = (await auth_client.get(DISCOVERIES_URL)).json()
    views = _views_by_mode(body)

    assert views[CreatorDiscoveryMode.CONSISTENTLY_LOVED.value]["entries"] == []
    assert views[CreatorDiscoveryMode.POLARIZING.value]["entries"] == []
    assert views[CreatorDiscoveryMode.HIGHEST_TOP_RATING_RATE.value]["entries"] == []
    assert views[CreatorDiscoveryMode.MOVED_OVER_TIME.value]["entries"] == []
    # The single rated creator still appears where no reliability is implied.
    assert _keys(views[CreatorDiscoveryMode.MOST_READ.value]) == ["creator:170"]
    assert _keys(views[CreatorDiscoveryMode.GREAT_AVERAGE_SMALL_SAMPLE.value]) == ["creator:170"]


@pytest.mark.asyncio
async def test_equal_scores_break_ties_by_canonical_key_and_are_deterministic(
    auth_client: AsyncClient,
    async_db: AsyncSession,
    default_user: User,
) -> None:
    """Identical metric rows order by canonical key and repeat identically."""
    await _build_creator(
        async_db, default_user, queue_position=1, creator_id=205, name="Tie E", ratings=[5.0, 5.0]
    )
    await _build_creator(
        async_db, default_user, queue_position=2, creator_id=201, name="Tie A", ratings=[5.0, 5.0]
    )
    await _build_creator(
        async_db, default_user, queue_position=3, creator_id=203, name="Tie C", ratings=[5.0, 5.0]
    )

    first = (await auth_client.get(DISCOVERIES_URL)).json()
    second = (await auth_client.get(DISCOVERIES_URL)).json()

    assert first == second
    small = _views_by_mode(first)[CreatorDiscoveryMode.GREAT_AVERAGE_SMALL_SAMPLE.value]
    assert _keys(small) == ["creator:201", "creator:203", "creator:205"]


@pytest.mark.asyncio
async def test_partial_creator_metadata_is_reported_as_lower_bound(
    auth_client: AsyncClient,
    async_db: AsyncSession,
    default_user: User,
) -> None:
    """Rated issues without confirmed metadata are a coverage gap, not evidence."""
    await _build_creator(
        async_db,
        default_user,
        queue_position=1,
        creator_id=180,
        name="Credited",
        ratings=[5.0, 5.0, 5.0, 5.0, 5.0],
    )
    # Rated but never credited: a metadata gap only.
    _thread, issues = await _make_thread(
        async_db, default_user, title="Uncredited", issue_count=1, queue_position=2, read_through=1
    )
    await _rate(async_db, issues[0], rating=5.0, timestamp=D1)

    body = (await auth_client.get(DISCOVERIES_URL)).json()
    coverage = body["coverage"]

    assert coverage["rated_issues_total"] == 6
    assert coverage["rated_issues_with_creator_metadata"] == 5
    assert coverage["ratings_complete"] is False
    # The credited creator's metrics derive from exactly its five real issues.
    loved = _views_by_mode(body)[CreatorDiscoveryMode.CONSISTENTLY_LOVED.value]
    assert _keys(loved) == ["creator:180"]
    assert loved["entries"][0]["rated_issue_count"] == 5


@pytest.mark.asyncio
async def test_entries_are_bounded_and_truncation_is_reported(
    auth_client: AsyncClient,
    async_db: AsyncSession,
    default_user: User,
) -> None:
    """More qualifying creators than the bound still report their true total."""
    for offset in range(MAX_DISCOVERY_ENTRIES + 2):
        await _build_creator(
            async_db,
            default_user,
            queue_position=offset + 1,
            creator_id=300 + offset,
            name=f"Creator {offset}",
            ratings=[5.0],
        )

    body = (await auth_client.get(DISCOVERIES_URL)).json()
    view = _views_by_mode(body)[CreatorDiscoveryMode.MOST_READ.value]

    assert view["total"] == MAX_DISCOVERY_ENTRIES + 2
    assert len(view["entries"]) == MAX_DISCOVERY_ENTRIES
    assert view["truncated"] is True
    assert view["max_entries"] == MAX_DISCOVERY_ENTRIES


@pytest.mark.asyncio
async def test_entry_reasons_match_reported_metrics(
    auth_client: AsyncClient,
    async_db: AsyncSession,
    default_user: User,
) -> None:
    """Every entry explains itself with reasons whose values match its metrics."""
    await _build_creator(
        async_db,
        default_user,
        queue_position=1,
        creator_id=190,
        name="Explainable",
        ratings=[5.0, 5.0, 5.0, 4.0, 4.0],
    )
    # A trend creator so the trend view's reasons are exercised too.
    await _build_creator(
        async_db,
        default_user,
        queue_position=2,
        creator_id=191,
        name="Warming",
        ratings=[2.0, 2.0, 2.0, 5.0, 5.0, 5.0],
    )

    body = (await auth_client.get(DISCOVERIES_URL)).json()
    view = _views_by_mode(body)[CreatorDiscoveryMode.CONSISTENTLY_LOVED.value]
    assert view["entries"], "the seeded loved creator must appear"

    # Every reason across every non-empty view must point at a metric the entry
    # actually exposes, so the UI can render any entry generically.
    for candidate in body["views"]:
        for candidate_entry in candidate["entries"]:
            assert candidate_entry["reasons"], "an entry must always explain itself"
            for reason in candidate_entry["reasons"]:
                assert reason["comparison"] in {"gte", "lte", "gt", "lt"}
                assert reason["metric"] in candidate_entry, (
                    f"{candidate['mode']} reason metric {reason['metric']!r} "
                    "is not exposed on the entry"
                )
                assert reason["value"] == pytest.approx(candidate_entry[reason["metric"]], abs=1e-3)


@pytest.mark.asyncio
async def test_discovery_never_crosses_users(
    auth_client: AsyncClient,
    async_db: AsyncSession,
    default_user: User,
    sample_user2: User,
) -> None:
    """Another user's library never leaks into this user's discovery views."""
    await _build_creator(
        async_db,
        default_user,
        queue_position=1,
        creator_id=400,
        name="Mine",
        ratings=[5.0, 5.0, 5.0, 5.0, 5.0],
    )
    await _build_creator(
        async_db,
        sample_user2,
        queue_position=1,
        creator_id=401,
        name="Theirs",
        ratings=[5.0, 5.0, 5.0, 5.0, 5.0],
    )

    body = (await auth_client.get(DISCOVERIES_URL)).json()
    loved = _views_by_mode(body)[CreatorDiscoveryMode.CONSISTENTLY_LOVED.value]

    assert _keys(loved) == ["creator:400"]
    assert body["coverage"]["rated_issues_total"] == 5


@pytest.mark.asyncio
async def test_query_cost_stays_bounded_for_growing_libraries(
    auth_client: AsyncClient,
    db_engine: AsyncEngine,
    async_db: AsyncSession,
    default_user: User,
) -> None:
    """The endpoint is served by a fixed bounded number of SELECT statements."""
    for offset in range(6):
        await _build_creator(
            async_db,
            default_user,
            queue_position=offset + 1,
            creator_id=500 + offset,
            name=f"Wide {offset}",
            ratings=[4.0, 4.0, 4.0, 4.0],
        )

    with _captured_selects(db_engine) as statements:
        response = await auth_client.get(DISCOVERIES_URL)
        assert response.status_code == 200

    assert len(statements) <= 6, (
        f"Discovery endpoint issued {len(statements)} SELECTs; the bounded "
        "pipeline must stay within its fixed query budget for any library size"
    )
