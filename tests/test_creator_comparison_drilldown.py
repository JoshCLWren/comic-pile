"""API coverage for creator-comparison metric drilldowns (issue #3176).

Every summary metric on the comparison cards must open into a bounded
evidence surface whose numerators, denominators, and percentages reconcile
exactly with the visible summary value. This module proves that summary and
drilldown share one aggregation implementation for the average, median, 5-star
rate, rating-distribution buckets, read-without-rating count, role averages,
and series averages, and that evidence lists stay paginated through an
opaque cursor.
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
D4 = datetime(2026, 3, 4, tzinfo=UTC)
D5 = datetime(2026, 3, 5, tzinfo=UTC)

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


async def _seed_comparison_library(
    db: AsyncSession,
    user: User,
) -> tuple[Thread, list[Issue], Thread, list[Issue]]:
    """Seed two creators with rated, unrated-read, and unread issues.

    Creator 1 ("Writer One", writer) owns a 3-issue read thread rated
    4/5/3, one read-but-unrated issue, and one unread issue. Creator 2
    ("Artist Two", artist) owns a 2-issue thread with a single rating so the
    summary and drilldown have distinct populations to reconcile.
    """
    thread_a, issues_a = await _make_thread(
        db, user, title="Team Book", issue_count=5, queue_position=1, read_through=4
    )
    for issue in issues_a:
        await _confirm_identity(
            db, issue, creators=[{"id": 1, "name": "Writer One", "role": "writer"}]
        )
    await _rate(db, issues_a[0], rating=4.0, timestamp=D1)
    await _rate(db, issues_a[1], rating=5.0, timestamp=D2)
    await _rate(db, issues_a[2], rating=3.0, timestamp=D3)
    # issues_a[3] stays read-but-unrated; issues_a[4] stays unread.

    thread_b, issues_b = await _make_thread(
        db, user, title="Solo Book", issue_count=2, queue_position=2, read_through=1
    )
    for issue in issues_b:
        await _confirm_identity(
            db, issue, creators=[{"id": 2, "name": "Artist Two", "role": "artist"}]
        )
    await _rate(db, issues_b[0], rating=5.0, timestamp=D1)

    return thread_a, issues_a, thread_b, issues_b


async def _summary(
    auth_client: AsyncClient,
    *,
    keys: str = "creator:1,creator:2",
) -> dict[str, object]:
    """Fetch the batch comparison summary for reconciliation assertions."""
    response = await auth_client.get(f"/api/v1/creators/compare?keys={keys}")
    assert response.status_code == 200
    return response.json()


@pytest.mark.asyncio
async def test_average_drilldown_reconciles_with_summary(
    auth_client: AsyncClient,
    async_db: AsyncSession,
    default_user: User,
) -> None:
    """The average evidence page reproduces the summary average and count."""
    await _seed_comparison_library(async_db, default_user)
    summary = await _summary(auth_client)

    response = await auth_client.get("/api/v1/creators/compare/average?creator=creator:1")

    assert response.status_code == 200
    body = response.json()
    assert body["metric"] == "average"
    assert body["creator_key"] == "creator:1"
    assert body["total_rated"] == summary["comparisons"]["creator:1"]["ratings_count"] == 3
    assert body["total_points"] == pytest.approx(12.0)
    assert body["total_count"] == 3
    assert body["next_cursor"] is None
    assert len(body["issues"]) == 3
    assert body["calculation"] == "12 total rating points ÷ 3 rated issues = 4.00★"

    issue_numbers = {row["issue_number"] for row in body["issues"]}
    assert issue_numbers == {"1", "2", "3"}
    ratings = {row["issue_number"]: row["rating"] for row in body["issues"]}
    assert ratings == {"1": 4.0, "2": 5.0, "3": 3.0}
    assert all(row["role"] == "writer" for row in body["issues"])
    assert all(row["thread_title"] == "Team Book" for row in body["issues"])


@pytest.mark.asyncio
async def test_median_drilldown_reconciles_with_summary_and_flags_middle_observations(
    auth_client: AsyncClient,
    async_db: AsyncSession,
    default_user: User,
) -> None:
    """The median evidence page reproduces the summary median and marks the deciding ranks."""
    await _seed_comparison_library(async_db, default_user)
    summary = await _summary(auth_client)

    response = await auth_client.get("/api/v1/creators/compare/median?creator=creator:1")

    assert response.status_code == 200
    body = response.json()
    assert body["metric"] == "median"
    assert body["ratings_count"] == 3
    assert body["median_rating"] == summary["comparisons"]["creator:1"]["median_rating"] == 4.0
    assert body["total_count"] == 3
    assert body["next_cursor"] is None

    observations = body["sorted_ratings"]
    assert [row["rank"] for row in observations] == [1, 2, 3]
    # Strongest rating first: 5, 4, 3. The middle observation (#2) decides the median.
    assert [row["rating"] for row in observations] == [5.0, 4.0, 3.0]
    assert [row["determines_median"] for row in observations] == [False, True, False]
    assert "middle value (#2) = 4★" in body["calculation"]


@pytest.mark.asyncio
async def test_median_drilldown_even_sample_names_both_middle_observations(
    auth_client: AsyncClient,
    async_db: AsyncSession,
    default_user: User,
) -> None:
    """An even sample flags both middle observations and shows the averaged median."""
    thread, issues = await _make_thread(
        async_db, default_user, title="Even Book", issue_count=4, queue_position=1, read_through=4
    )
    for issue in issues:
        await _confirm_identity(
            async_db, issue, creators=[{"id": 1, "name": "Writer One", "role": "writer"}]
        )
    await _rate(async_db, issues[0], rating=1.0, timestamp=D1)
    await _rate(async_db, issues[1], rating=2.0, timestamp=D2)
    await _rate(async_db, issues[2], rating=4.0, timestamp=D3)
    await _rate(async_db, issues[3], rating=5.0, timestamp=D4)

    response = await auth_client.get("/api/v1/creators/compare/median?creator=creator:1")

    assert response.status_code == 200
    body = response.json()
    assert body["ratings_count"] == 4
    assert body["median_rating"] == pytest.approx(3.0)
    assert [row["rating"] for row in body["sorted_ratings"]] == [5.0, 4.0, 2.0, 1.0]
    assert [row["determines_median"] for row in body["sorted_ratings"]] == [False, True, True, False]
    assert "middle observations (#2) = 4★ and (#3) = 2★" in body["calculation"]
    assert "median = 3.00★" in body["calculation"]


@pytest.mark.asyncio
async def test_five_star_rate_drilldown_reconciles_with_summary(
    auth_client: AsyncClient,
    async_db: AsyncSession,
    default_user: User,
) -> None:
    """The 5-star evidence page reproduces the summary rate and lists exactly the top issues."""
    await _seed_comparison_library(async_db, default_user)
    summary = await _summary(auth_client)

    response = await auth_client.get("/api/v1/creators/compare/5-star-rate?creator=creator:1")

    assert response.status_code == 200
    body = response.json()
    assert body["metric"] == "5-star-rate"
    assert body["top_count"] == 1
    assert body["rated_count"] == 3
    assert body["total_count"] == 1
    assert body["next_cursor"] is None
    # 1 of 3 = 33.3%, matching the summary top_rating_rate of 1/3.
    assert body["calculation"] == "1 five-star rating ÷ 3 rated issues = 33.3%"
    assert summary["comparisons"]["creator:1"]["top_rating_rate"] == pytest.approx(
        1 / 3, abs=1e-3
    )
    assert len(body["issues"]) == 1
    assert body["issues"][0]["issue_number"] == "2"
    assert body["issues"][0]["rating"] == 5.0


@pytest.mark.asyncio
async def test_distribution_bucket_drilldown_reconciles_with_summary(
    auth_client: AsyncClient,
    async_db: AsyncSession,
    default_user: User,
) -> None:
    """A bucket evidence page reproduces the summary distribution count and denominator."""
    await _seed_comparison_library(async_db, default_user)
    summary = await _summary(auth_client)

    response = await auth_client.get(
        "/api/v1/creators/compare/distribution?creator=creator:1&bucket=4"
    )

    assert response.status_code == 200
    body = response.json()
    assert body["metric"] == "distribution"
    assert body["bucket"] == "4"
    summary_distribution = summary["comparisons"]["creator:1"]["rating_distribution"]
    assert body["bucket_count"] == summary_distribution["4"] == 1
    assert body["total_rated"] == summary["comparisons"]["creator:1"]["ratings_count"] == 3
    assert body["total_count"] == 1
    assert body["next_cursor"] is None
    assert body["calculation"] == "1 of 3 rated issues are exactly 4★ = 33.3%"
    assert len(body["issues"]) == 1
    assert body["issues"][0]["issue_number"] == "1"
    assert body["issues"][0]["rating"] == 4.0


@pytest.mark.asyncio
async def test_read_without_rating_drilldown_reconciles_with_summary(
    auth_client: AsyncClient,
    async_db: AsyncSession,
    default_user: User,
) -> None:
    """The read-without-rating evidence page reproduces the summary count and says causes are unclassified."""
    await _seed_comparison_library(async_db, default_user)
    summary = await _summary(auth_client)

    response = await auth_client.get(
        "/api/v1/creators/compare/read-without-rating?creator=creator:1"
    )

    assert response.status_code == 200
    body = response.json()
    assert body["metric"] == "read-without-rating"
    assert body["count"] == summary["comparisons"]["creator:1"]["read_unrated_count"] == 1
    assert body["total_count"] == 1
    assert body["next_cursor"] is None
    # Per-issue cause classification does not exist yet (issue #3175); the
    # response must say so instead of implying a known cause.
    assert body["classification_available"] is False
    assert "has not been classified yet" in body["calculation"]
    assert len(body["issues"]) == 1
    assert body["issues"][0]["issue_number"] == "4"
    assert body["issues"][0]["rating"] is None
    assert body["issues"][0]["role"] == "writer"


@pytest.mark.asyncio
async def test_unread_drilldown_reconciles_with_summary(
    auth_client: AsyncClient,
    async_db: AsyncSession,
    default_user: User,
) -> None:
    """The unread evidence page reproduces the summary unread count."""
    await _seed_comparison_library(async_db, default_user)
    summary = await _summary(auth_client)

    response = await auth_client.get("/api/v1/creators/compare/unread?creator=creator:1")

    assert response.status_code == 200
    body = response.json()
    assert body["metric"] == "unread"
    assert (
        body["count"]
        == summary["comparisons"]["creator:1"]["unread_upcoming_count"]
        == 1
    )
    assert body["total_count"] == 1
    assert len(body["issues"]) == 1
    assert body["issues"][0]["issue_number"] == "5"


@pytest.mark.asyncio
async def test_role_average_drilldown_reconciles_with_summary(
    auth_client: AsyncClient,
    async_db: AsyncSession,
    default_user: User,
) -> None:
    """A role evidence page distinguishes credited issues from the rated subset behind the average."""
    await _seed_comparison_library(async_db, default_user)
    # Add a second credited role with a partial rating so the role drilldown
    # has a rated subset smaller than its credited population.
    thread, issues = await _make_thread(
        async_db, default_user, title="Dual Role Book", issue_count=3, queue_position=3, read_through=3
    )
    dual_credits = [
        {"id": 1, "name": "Writer One", "role": "writer"},
        {"id": 1, "name": "Writer One", "role": "colorist"},
    ]
    for issue in issues:
        await _confirm_identity(async_db, issue, creators=dual_credits)
    await _rate(async_db, issues[0], rating=2.0, timestamp=D1)
    await _rate(async_db, issues[1], rating=4.0, timestamp=D2)
    # issues[2] stays read-but-unrated.

    summary = await _summary(auth_client)
    response = await auth_client.get(
        "/api/v1/creators/compare/role-average?creator=creator:1&role=colorist"
    )

    assert response.status_code == 200
    body = response.json()
    assert body["metric"] == "role-average"
    assert body["role"] == "colorist"
    summary_role = next(
        row
        for row in summary["comparisons"]["creator:1"]["role_stats"]
        if row["role"] == "colorist"
    )
    assert body["issue_count"] == summary_role["issue_count"] == 3
    assert body["rated_issue_count"] == summary_role["rated_issue_count"] == 2
    assert body["average_rating"] == summary_role["average_rating"] == pytest.approx(3.0)
    assert body["total_count"] == 3
    assert len(body["issues"]) == 3
    # Every credited issue appears; the unrated row carries a null rating.
    unrated_rows = [row for row in body["issues"] if row["rating"] is None]
    assert len(unrated_rows) == 1
    assert unrated_rows[0]["issue_number"] == "3"
    assert body["calculation"].startswith("colorist: 3 credited issues, 2 with effective ratings;")


@pytest.mark.asyncio
async def test_series_average_drilldown_reconciles_with_summary(
    auth_client: AsyncClient,
    async_db: AsyncSession,
    default_user: User,
) -> None:
    """A series evidence page distinguishes attributed issues from the rated subset behind the average."""
    thread_a, issues_a, _thread_b, _issues_b = await _seed_comparison_library(
        async_db, default_user
    )
    summary = await _summary(auth_client)
    response = await auth_client.get(
        f"/api/v1/creators/compare/series-average?creator=creator:1&series=thread:{thread_a.id}"
    )

    assert response.status_code == 200
    body = response.json()
    assert body["metric"] == "series-average"
    assert body["thread_id"] == thread_a.id
    assert body["thread_title"] == "Team Book"
    summary_series = next(
        row
        for row in summary["comparisons"]["creator:1"]["strongest_series"]
        if row["thread_id"] == thread_a.id
    )
    assert body["issue_count"] == summary_series["issue_count"] == 5
    assert body["rated_issue_count"] == summary_series["rated_issue_count"] == 3
    assert body["average_rating"] == summary_series["average_rating"] == pytest.approx(4.0)
    assert body["min_rated_issues_per_series"] == 3
    assert body["total_count"] == 5
    assert len(body["issues"]) == 5
    # The two non-rated attributed issues (one read-unrated, one unread) still
    # appear with null ratings so the attributed population is fully inspectable.
    rated_rows = [row for row in body["issues"] if row["rating"] is not None]
    assert len(rated_rows) == 3
    assert {row["issue_number"] for row in rated_rows} == {"1", "2", "3"}
    assert body["calculation"].startswith(
        "Team Book: 5 attributed issues, 3 with effective ratings;"
    )


@pytest.mark.asyncio
async def test_drilldown_evidence_pages_through_opaque_cursor(
    auth_client: AsyncClient,
    async_db: AsyncSession,
    default_user: User,
) -> None:
    """Evidence lists are bounded per page and the cursor walks the full set exactly once."""
    thread, issues = await _make_thread(
        async_db, default_user, title="Long Book", issue_count=5, queue_position=1, read_through=5
    )
    for issue in issues:
        await _confirm_identity(
            async_db, issue, creators=[{"id": 1, "name": "Writer One", "role": "writer"}]
        )
    for index, issue in enumerate(issues):
        await _rate(async_db, issue, rating=1.0 + index, timestamp=D1)

    first = await auth_client.get(
        "/api/v1/creators/compare/average?creator=creator:1&limit=2"
    )
    assert first.status_code == 200
    first_body = first.json()
    assert len(first_body["issues"]) == 2
    assert first_body["total_count"] == 5
    assert first_body["total_rated"] == 5
    assert first_body["next_cursor"] is not None

    second = await auth_client.get(
        "/api/v1/creators/compare/average?creator=creator:1&limit=2&cursor="
        + first_body["next_cursor"]
    )
    assert second.status_code == 200
    second_body = second.json()
    assert len(second_body["issues"]) == 2
    assert second_body["total_count"] == 5
    assert second_body["next_cursor"] is not None

    third = await auth_client.get(
        "/api/v1/creators/compare/average?creator=creator:1&limit=2&cursor="
        + second_body["next_cursor"]
    )
    assert third.status_code == 200
    third_body = third.json()
    assert len(third_body["issues"]) == 1
    assert third_body["next_cursor"] is None

    seen = [
        row["issue_id"]
        for page in (first_body, second_body, third_body)
        for row in page["issues"]
    ]
    assert len(seen) == len(set(seen)) == 5


@pytest.mark.asyncio
async def test_drilldown_unknown_creator_returns_404(
    auth_client: AsyncClient,
    async_db: AsyncSession,
    default_user: User,
) -> None:
    """A creator outside the library 404s instead of leaking other readers' data."""
    await _seed_comparison_library(async_db, default_user)

    for metric in ("average", "median", "5-star-rate", "read-without-rating", "unread"):
        response = await auth_client.get(
            f"/api/v1/creators/compare/{metric}?creator=creator:9999"
        )
        assert response.status_code == 404, metric
        assert "creator:9999" in response.json()["detail"]


@pytest.mark.asyncio
async def test_drilldown_invalid_inputs_return_400(
    auth_client: AsyncClient,
    async_db: AsyncSession,
    default_user: User,
) -> None:
    """Malformed buckets and cursors fail closed with a 400."""
    await _seed_comparison_library(async_db, default_user)

    bucket = await auth_client.get(
        "/api/v1/creators/compare/distribution?creator=creator:1&bucket=7"
    )
    assert bucket.status_code == 400
    assert "Unknown rating bucket" in bucket.json()["detail"]

    cursor = await auth_client.get(
        "/api/v1/creators/compare/average?creator=creator:1&cursor=not-a-cursor"
    )
    assert cursor.status_code == 400
    assert "cursor" in cursor.json()["detail"]

    missing_role = await auth_client.get(
        "/api/v1/creators/compare/role-average?creator=creator:1"
    )
    assert missing_role.status_code == 422

    unknown_series = await auth_client.get(
        "/api/v1/creators/compare/series-average?creator=creator:1&series=thread:99999"
    )
    assert unknown_series.status_code == 404
