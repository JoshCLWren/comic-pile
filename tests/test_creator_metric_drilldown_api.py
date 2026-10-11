"""API coverage for the creator metric drilldown contract (issue #3176).

Every comparison metric must drill into the exact math and supporting issues
behind its summary value. These tests prove that each drilldown reconciles
with the comparison summary built from the same #2028 aggregation inputs:
headline metrics (average, median, rated count, 5-star rate, distribution)
count only headline-eligible rated issues, while role and series drilldowns
distinguish total credited issues from the rated subset used by the average.
"""

from datetime import UTC, datetime

import pytest
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

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
) -> None:
    """Create a confirmed external issue identity mapping."""
    global _identity_serial
    _identity_serial += 1
    identity = ExternalIdentity(
        provider="comicvine",
        entity_type="issue",
        external_id=f"drill-{_identity_serial}",
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


async def _seed_drilldown_library(
    async_db: AsyncSession, default_user: User
) -> tuple[Thread, list[Issue], Thread, Issue, Thread, Issue]:
    """Seed writer/cover/artist work with headline and non-headline credits."""
    writer_thread, writer_issues = await _make_thread(
        async_db, default_user, title="Writer Book", issue_count=4, queue_position=1, read_through=3
    )
    for issue in writer_issues:
        await _confirm_identity(
            async_db, issue, creators=[{"id": 1, "name": "Writer One", "role": "writer"}]
        )
    await _rate(async_db, writer_issues[0], rating=4.0, timestamp=D1)
    await _rate(async_db, writer_issues[2], rating=5.0, timestamp=D3)

    cover_thread, cover_issues = await _make_thread(
        async_db, default_user, title="Cover Book", issue_count=1, queue_position=2, read_through=1
    )
    await _confirm_identity(
        async_db, cover_issues[0], creators=[{"id": 1, "name": "Writer One", "role": "cover"}]
    )
    await _rate(async_db, cover_issues[0], rating=3.0, timestamp=D2)

    artist_thread, artist_issues = await _make_thread(
        async_db, default_user, title="Artist Book", issue_count=1, queue_position=3, read_through=1
    )
    await _confirm_identity(
        async_db, artist_issues[0], creators=[{"id": 2, "name": "Artist Two", "role": "artist"}]
    )
    await _rate(async_db, artist_issues[0], rating=3.5, timestamp=D2)
    return writer_thread, writer_issues, cover_thread, cover_issues[0], artist_thread, artist_issues[0]


@pytest.mark.asyncio
async def test_average_drilldown_reconciles_with_comparison(
    auth_client: AsyncClient,
    async_db: AsyncSession,
    default_user: User,
) -> None:
    """Average drilldown matches the comparison headline average and rated set."""
    writer_thread, writer_issues, _, cover_issue, _, _ = await _seed_drilldown_library(
        async_db, default_user
    )

    compare = await auth_client.get("/api/v1/creators/compare?keys=creator:1,creator:2")
    assert compare.status_code == 200
    writer = compare.json()["comparisons"]["creator:1"]
    assert writer["ratings_count"] == 2
    assert writer["average_rating"] == pytest.approx(4.5)

    response = await auth_client.get("/api/v1/creators/creator:1/metrics/average-rating")
    assert response.status_code == 200
    body = response.json()
    assert body["metric_type"] == "average-rating"
    assert body["total_count"] == writer["ratings_count"] == 2
    assert body["calculation"]["formula"] == "9.0 total rating points ÷ 2 rated issues = 4.50★"
    assert body["calculation"]["percentage"] == "4.50★"
    assert {row["issue_id"] for row in body["included_issues"]} == {
        writer_issues[0].id,
        writer_issues[2].id,
    }
    excluded_by_id = {row["issue_id"]: row["exclusion_reason"] for row in body["excluded_issues"]}
    assert excluded_by_id[writer_issues[1].id] == "No stored effective rating"
    assert excluded_by_id[writer_issues[3].id] == "No stored effective rating"
    assert (
        excluded_by_id[cover_issue.id]
        == "Creator only credited in a non-headline role excluded from headline stats"
    )
    assert writer_thread.id == writer_issues[0].thread_id


@pytest.mark.asyncio
async def test_median_drilldown_identifies_median_observations(
    auth_client: AsyncClient,
    async_db: AsyncSession,
    default_user: User,
) -> None:
    """Median drilldown names the observations that determine the median."""
    _, writer_issues, _, _, _, _ = await _seed_drilldown_library(async_db, default_user)

    compare = await auth_client.get("/api/v1/creators/compare?keys=creator:1,creator:2")
    assert compare.json()["comparisons"]["creator:1"]["median_rating"] == pytest.approx(4.5)

    response = await auth_client.get("/api/v1/creators/creator:1/metrics/median-rating")
    assert response.status_code == 200
    body = response.json()
    assert body["total_count"] == 2
    assert "middle observations (#1 and #2)" in body["calculation"]["formula"]
    assert body["calculation"]["percentage"] == "4.50★"
    median_rows = [
        row for row in body["included_issues"] if row["exclusion_reason"] == "Median observation"
    ]
    assert {row["issue_id"] for row in median_rows} == {writer_issues[0].id, writer_issues[2].id}


@pytest.mark.asyncio
async def test_rated_count_and_five_star_rate_reconcile(
    auth_client: AsyncClient,
    async_db: AsyncSession,
    default_user: User,
) -> None:
    """Rated count and 5-star rate drilldowns match the comparison summary."""
    _, writer_issues, _, _, _, _ = await _seed_drilldown_library(async_db, default_user)

    compare = await auth_client.get("/api/v1/creators/compare?keys=creator:1,creator:2")
    writer = compare.json()["comparisons"]["creator:1"]
    assert writer["top_rating_rate"] == pytest.approx(0.5)

    count = await auth_client.get("/api/v1/creators/creator:1/metrics/rated-issue-count")
    assert count.status_code == 200
    assert count.json()["total_count"] == writer["ratings_count"] == 2

    rate = await auth_client.get("/api/v1/creators/creator:1/metrics/five-star-rate")
    assert rate.status_code == 200
    rate_body = rate.json()
    assert rate_body["total_count"] == 1
    assert rate_body["calculation"]["formula"] == "1 five-star ratings ÷ 2 rated issues = 50.0%"
    assert rate_body["calculation"]["percentage"] == "50.0%"
    assert [row["issue_id"] for row in rate_body["included_issues"]] == [writer_issues[2].id]
    non_five = [
        row for row in rate_body["excluded_issues"] if row["issue_id"] == writer_issues[0].id
    ]
    assert non_five[0]["exclusion_reason"] == "Rated 4.0★, not 5★"


@pytest.mark.asyncio
async def test_distribution_bucket_shows_exact_bucket_issues(
    auth_client: AsyncClient,
    async_db: AsyncSession,
    default_user: User,
) -> None:
    """Distribution drilldown contains exactly the issues in the rating bucket."""
    _, writer_issues, _, _, _, _ = await _seed_drilldown_library(async_db, default_user)

    compare = await auth_client.get("/api/v1/creators/compare?keys=creator:1,creator:2")
    assert compare.json()["comparisons"]["creator:1"]["rating_distribution"] == {"4": 1, "5": 1}

    bucket = await auth_client.get("/api/v1/creators/creator:1/metrics/rating-distribution/5.0")
    assert bucket.status_code == 200
    bucket_body = bucket.json()
    assert bucket_body["bucket_count"] == 1
    assert bucket_body["bucket_percentage"] == pytest.approx(50.0)
    assert [row["issue_id"] for row in bucket_body["included_issues"]] == [writer_issues[2].id]

    other = await auth_client.get("/api/v1/creators/creator:1/metrics/rating-distribution/4.0")
    assert other.status_code == 200
    assert [row["issue_id"] for row in other.json()["included_issues"]] == [writer_issues[0].id]

    invalid = await auth_client.get("/api/v1/creators/creator:1/metrics/rating-distribution/abc")
    assert invalid.status_code == 400


@pytest.mark.asyncio
async def test_unread_and_read_unrated_drilldowns_match_counts(
    auth_client: AsyncClient,
    async_db: AsyncSession,
    default_user: User,
) -> None:
    """Unread and read-without-rating drilldowns expose the exact issue sets."""
    _, writer_issues, _, _, _, _ = await _seed_drilldown_library(async_db, default_user)

    compare = await auth_client.get("/api/v1/creators/compare?keys=creator:1,creator:2")
    writer = compare.json()["comparisons"]["creator:1"]
    assert writer["unread_upcoming_count"] == 1
    assert writer["read_unrated_count"] == 1

    unread = await auth_client.get("/api/v1/creators/creator:1/metrics/unread-count")
    assert unread.status_code == 200
    assert unread.json()["total_count"] == 1
    assert [row["issue_id"] for row in unread.json()["included_issues"]] == [writer_issues[3].id]

    unrated = await auth_client.get("/api/v1/creators/creator:1/metrics/read-unrated-count")
    assert unrated.status_code == 200
    assert unrated.json()["total_count"] == 1
    assert [row["issue_id"] for row in unrated.json()["included_issues"]] == [writer_issues[1].id]


@pytest.mark.asyncio
async def test_role_drilldown_distinguishes_credited_from_rated(
    auth_client: AsyncClient,
    async_db: AsyncSession,
    default_user: User,
) -> None:
    """Role drilldown separates total credited issues from rated issues."""
    await _seed_drilldown_library(async_db, default_user)

    compare = await auth_client.get("/api/v1/creators/compare?keys=creator:1,creator:2")
    writer_roles = {
        stat["role"]: stat for stat in compare.json()["comparisons"]["creator:1"]["role_stats"]
    }
    assert writer_roles["writer"]["issue_count"] == 4
    assert writer_roles["writer"]["rated_issue_count"] == 2

    writer = await auth_client.get("/api/v1/creators/creator:1/metrics/role-stats/writer")
    assert writer.status_code == 200
    writer_body = writer.json()
    assert writer_body["role_issue_count"] == 4
    assert writer_body["role_rated_issue_count"] == 2
    assert writer_body["role_average_rating"] == pytest.approx(4.5)

    cover = await auth_client.get("/api/v1/creators/creator:1/metrics/role-stats/cover")
    assert cover.status_code == 200
    assert cover.json()["role_issue_count"] == 1
    assert cover.json()["role_average_rating"] == pytest.approx(3.0)

    unknown_role = await auth_client.get("/api/v1/creators/creator:1/metrics/role-stats/letterer")
    assert unknown_role.status_code == 404

    missing_role = await auth_client.get("/api/v1/creators/creator:1/metrics/role-stats")
    assert missing_role.status_code == 400


@pytest.mark.asyncio
async def test_series_drilldown_matches_strongest_series(
    auth_client: AsyncClient,
    async_db: AsyncSession,
    default_user: User,
) -> None:
    """Series drilldown matches the strongest-series aggregate for the thread."""
    writer_thread, _, _, _, _, _ = await _seed_drilldown_library(async_db, default_user)

    compare = await auth_client.get("/api/v1/creators/compare?keys=creator:1,creator:2")
    strongest = compare.json()["comparisons"]["creator:1"]["strongest_series"][0]
    assert strongest["thread_id"] == writer_thread.id
    assert strongest["rated_issue_count"] == 2
    assert strongest["average_rating"] == pytest.approx(4.5)

    response = await auth_client.get(
        f"/api/v1/creators/creator:1/metrics/series-stats/thread:{writer_thread.id}"
    )
    assert response.status_code == 200
    body = response.json()
    assert body["series_issue_count"] == strongest["issue_count"] == 4
    assert body["series_rated_issue_count"] == 2
    assert body["series_average_rating"] == pytest.approx(4.5)

    unknown = await auth_client.get("/api/v1/creators/creator:1/metrics/series-stats/thread:999999")
    assert unknown.status_code == 404

    malformed = await auth_client.get("/api/v1/creators/creator:1/metrics/series-stats/bogus")
    assert malformed.status_code == 400


@pytest.mark.asyncio
async def test_single_rating_median_average_and_five_star(
    auth_client: AsyncClient,
    async_db: AsyncSession,
    default_user: User,
) -> None:
    """A single rated issue exercises the odd-median and empty-bucket paths."""
    _, _, _, _, _, artist_issue = await _seed_drilldown_library(async_db, default_user)

    median = await auth_client.get("/api/v1/creators/creator:2/metrics/median-rating")
    assert median.status_code == 200
    median_body = median.json()
    assert median_body["total_count"] == 1
    assert "middle value (#1) = 3.5★" in median_body["calculation"]["formula"]
    assert median_body["calculation"]["percentage"] == "3.50★"

    average = await auth_client.get("/api/v1/creators/creator:2/metrics/average-rating")
    assert average.status_code == 200
    assert (
        average.json()["calculation"]["formula"]
        == "3.5 total rating points ÷ 1 rated issues = 3.50★"
    )

    rate = await auth_client.get("/api/v1/creators/creator:2/metrics/five-star-rate")
    assert rate.status_code == 200
    rate_body = rate.json()
    assert rate_body["total_count"] == 0
    assert rate_body["calculation"]["percentage"] == "0.0%"
    assert rate_body["included_issues"] == []

    bucket = await auth_client.get("/api/v1/creators/creator:2/metrics/rating-distribution/3.5")
    assert bucket.status_code == 200
    assert bucket.json()["bucket_count"] == 1
    assert bucket.json()["bucket_percentage"] == pytest.approx(100.0)
    assert [row["issue_id"] for row in bucket.json()["included_issues"]] == [artist_issue.id]

    empty_bucket = await auth_client.get(
        "/api/v1/creators/creator:2/metrics/rating-distribution/5.0"
    )
    assert empty_bucket.status_code == 200
    assert empty_bucket.json()["bucket_count"] == 0


@pytest.mark.asyncio
async def test_drilldown_rejects_unknown_creator_metric_and_key(
    auth_client: AsyncClient,
    async_db: AsyncSession,
    default_user: User,
) -> None:
    """Unknown creators 404, invalid metric types and keys 400 without leaking."""
    await _seed_drilldown_library(async_db, default_user)

    missing = await auth_client.get("/api/v1/creators/creator:9999/metrics/average-rating")
    assert missing.status_code == 404

    bad_metric = await auth_client.get("/api/v1/creators/creator:1/metrics/not-a-metric")
    assert bad_metric.status_code == 400

    bad_key = await auth_client.get("/api/v1/creators/bogus/metrics/average-rating")
    assert bad_key.status_code == 400

    missing_param = await auth_client.get("/api/v1/creators/creator:1/metrics/role-stats")
    assert missing_param.status_code == 400
