"""API coverage for the bounded personal creator-team chemistry contract (#3094).

One authenticated endpoint ranks recurring creator teams — pairs of stable
canonical creator identities credited together on shared rated issues with
eligible interior-storytelling roles. This module covers the acceptance
contract: pairs derived only from actual shared issues, role eligibility, the
explicit minimum shared sample, explainable sample/average/baseline context,
same-name distinctness, partial-metadata truthfulness, bounded query cost, and
navigable drilldown references.
"""

from collections.abc import Iterator
from contextlib import contextmanager
from datetime import UTC, datetime, timedelta
from typing import Any

import pytest
from httpx import AsyncClient
from sqlalchemy import event as sqla_event
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession

from app.constants import MIN_SHARED_TEAM_SAMPLE
from app.models import Event, Issue, Thread, User
from app.models.external_identity import ExternalIdentity, IssueExternalIdentityMapping
from app.schemas.creator_team_chemistry import MAX_RANKED_TEAM_PAIRS, MAX_SHARED_ISSUE_REFS

D1 = datetime(2026, 3, 1, tzinfo=UTC)

TEAM_CHEMISTRY_URL = "/api/v1/creators/team-chemistry"

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
        external_id=f"sv-team-{_identity_serial}",
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
async def test_team_chemistry_requires_authentication(client: AsyncClient) -> None:
    """Unauthenticated requests never aggregate a library."""
    assert (await client.get(TEAM_CHEMISTRY_URL)).status_code == 401


@pytest.mark.asyncio
async def test_empty_library_returns_empty_bounded_response(
    auth_client: AsyncClient,
) -> None:
    """A library with no rated issues yields an empty, well-formed payload."""
    response = await auth_client.get(TEAM_CHEMISTRY_URL)

    assert response.status_code == 200
    body = response.json()
    assert body["pairs"] == []
    assert body["pairs_total"] == 0
    assert body["min_shared_team_sample"] == MIN_SHARED_TEAM_SAMPLE
    assert body["max_ranked_pairs"] == MAX_RANKED_TEAM_PAIRS
    assert body["coverage"]["rated_issues_total"] == 0
    assert body["coverage"]["rated_issues_with_creator_metadata"] == 0
    assert body["coverage"]["ratings_complete"] is True


@pytest.mark.asyncio
async def test_pairs_derived_only_from_shared_issues(
    auth_client: AsyncClient,
    async_db: AsyncSession,
    default_user: User,
) -> None:
    """A pair ranks only from actual shared rated issues, strongest first."""
    _thread_a, issues_a = await _make_thread(
        async_db, default_user, title="Team Book", issue_count=4, queue_position=1, read_through=4
    )
    # Issues 1-3 credit the writer/artist team; issue 4 is writer-only work.
    for issue in issues_a[:3]:
        await _confirm_identity(
            async_db,
            issue,
            creators=[
                {"id": 1, "name": "Writer One", "role": "writer"},
                {"id": 2, "name": "Artist Two", "role": "artist"},
            ],
        )
    await _confirm_identity(
        async_db,
        issues_a[3],
        creators=[{"id": 1, "name": "Writer One", "role": "writer"}],
    )
    for rating, issue in zip([4.0, 5.0, 3.0, 2.0], issues_a, strict=True):
        await _rate(async_db, issue, rating=rating, timestamp=D1)

    # Artist Two also shares three rated issues with Letterer Three; the
    # letterer role is not interior-storytelling so only the artist side counts.
    _thread_b, issues_b = await _make_thread(
        async_db, default_user, title="Second Book", issue_count=3, queue_position=2, read_through=3
    )
    for issue in issues_b:
        await _confirm_identity(
            async_db,
            issue,
            creators=[
                {"id": 2, "name": "Artist Two", "role": "artist"},
                {"id": 3, "name": "Letterer Three", "role": "letterer"},
            ],
        )
    for rating, issue in zip([5.0, 4.0, 4.0], issues_b, strict=True):
        await _rate(async_db, issue, rating=rating, timestamp=D1)

    response = await auth_client.get(TEAM_CHEMISTRY_URL)
    assert response.status_code == 200
    body = response.json()

    by_key = {pair["pair_key"]: pair for pair in body["pairs"]}
    assert set(by_key) == {"creator:1|creator:2"}

    writer_artist = by_key["creator:1|creator:2"]
    assert writer_artist["shared_rated_issue_count"] == 3
    assert writer_artist["shared_average_rating"] == pytest.approx(4.0)  # (4+5+3)/3
    assert writer_artist["shared_rating_distribution"].get("5") == 1
    roles = {
        member["canonical_creator_key"]: member["roles"]
        for member in writer_artist["creators"]
    }
    assert roles == {"creator:1": ["writer"], "creator:2": ["artist"]}


@pytest.mark.asyncio
async def test_min_shared_sample_enforced_and_documented(
    auth_client: AsyncClient,
    async_db: AsyncSession,
    default_user: User,
) -> None:
    """Pairs below the documented minimum shared sample are never ranked."""
    _thread_a, issues_a = await _make_thread(
        async_db, default_user, title="Thin Team", issue_count=2, queue_position=1, read_through=2
    )
    for issue in issues_a:
        await _confirm_identity(
            async_db,
            issue,
            creators=[
                {"id": 5, "name": "Writer Five", "role": "writer"},
                {"id": 6, "name": "Artist Six", "role": "artist"},
            ],
        )
        await _rate(async_db, issue, rating=5.0, timestamp=D1)

    response = await auth_client.get(TEAM_CHEMISTRY_URL)
    assert response.status_code == 200
    body = response.json()
    assert body["pairs"] == []
    assert body["pairs_total"] == 0
    assert body["min_shared_team_sample"] == MIN_SHARED_TEAM_SAMPLE


@pytest.mark.asyncio
async def test_role_eligibility_excludes_noisy_non_story_credits(
    auth_client: AsyncClient,
    async_db: AsyncSession,
    default_user: User,
) -> None:
    """Editorial, cover, and lettering credits never define a team pair."""
    _thread_a, issues_a = await _make_thread(
        async_db, default_user, title="Cover Noise", issue_count=3, queue_position=1, read_through=3
    )
    for issue in issues_a:
        await _confirm_identity(
            async_db,
            issue,
            creators=[
                {"id": 7, "name": "Editor Seven", "role": "editor"},
                {"id": 8, "name": "Letterer Nine", "role": "letterer"},
            ],
        )
        await _rate(async_db, issue, rating=5.0, timestamp=D1)

    # The interior colorist/inker pair qualifies; the letterer does not add the
    # letterer or page-noise members into any ranked pair.
    _thread_b, issues_b = await _make_thread(
        async_db, default_user, title="Interior Team", issue_count=3, queue_position=2, read_through=3
    )
    for issue in issues_b:
        await _confirm_identity(
            async_db,
            issue,
            creators=[
                {"id": 8, "name": "Letterer Nine", "role": "letterer"},
                {"id": 10, "name": "Colorist Ten", "role": "colorist"},
                {"id": 11, "name": "Inker Eleven", "role": "inker"},
            ],
        )
        await _rate(async_db, issue, rating=4.0, timestamp=D1)

    response = await auth_client.get(TEAM_CHEMISTRY_URL)
    assert response.status_code == 200
    body = response.json()
    assert [pair["pair_key"] for pair in body["pairs"]] == ["creator:10|creator:11"]
    roles = {
        member["canonical_creator_key"]: member["roles"]
        for member in body["pairs"][0]["creators"]
    }
    assert roles["creator:10"] == ["colorist"]
    assert roles["creator:11"] == ["inker"]


@pytest.mark.asyncio
async def test_same_name_creators_remain_distinct(
    auth_client: AsyncClient,
    async_db: AsyncSession,
    default_user: User,
) -> None:
    """Identical display names never collapse two canonical identities."""
    _thread_a, issues_a = await _make_thread(
        async_db, default_user, title="Same Name Team", issue_count=3, queue_position=1, read_through=3
    )
    for issue in issues_a:
        await _confirm_identity(
            async_db,
            issue,
            creators=[
                {"id": 21, "name": "John Smith", "role": "writer"},
                {"id": 22, "name": "John Smith", "role": "artist"},
            ],
        )
        await _rate(async_db, issue, rating=3.5, timestamp=D1)

    response = await auth_client.get(TEAM_CHEMISTRY_URL)
    assert response.status_code == 200
    body = response.json()
    assert len(body["pairs"]) == 1
    members = body["pairs"][0]["creators"]
    assert sorted(m["canonical_creator_key"] for m in members) == ["creator:21", "creator:22"]
    names = {m["display_name"] for m in members}
    assert names == {"John Smith"}
    assert body["pairs"][0]["shared_rated_issue_count"] == 3


@pytest.mark.asyncio
async def test_ranking_prefers_stronger_shared_average(
    auth_client: AsyncClient,
    async_db: AsyncSession,
    default_user: User,
) -> None:
    """Pairs rank strongest shared average first, ties break deterministically."""
    # Two fully disjoint teams: (10,20) averages 3.0, (30,40) averages 5.0.
    for creators, title, ratings in (
        (
            [
                {"id": 10, "name": "Writer Mild", "role": "writer"},
                {"id": 20, "name": "Artist Mild", "role": "artist"},
            ],
            "Mild Team",
            [3.0, 3.0, 3.0],
        ),
        (
            [
                {"id": 30, "name": "Writer Favorite", "role": "writer"},
                {"id": 40, "name": "Artist Favorite", "role": "artist"},
            ],
            "Favorite Team",
            [5.0, 5.0, 5.0],
        ),
    ):
        thread, issues = await _make_thread(
            async_db, default_user, title=title, issue_count=3, queue_position=len(title), read_through=3
        )
        del thread
        for issue in issues:
            await _confirm_identity(async_db, issue, creators=creators)
        for rating, issue in zip(ratings, issues, strict=True):
            await _rate(async_db, issue, rating=rating, timestamp=D1)

    response = await auth_client.get(TEAM_CHEMISTRY_URL)
    assert response.status_code == 200
    body = response.json()
    assert [pair["pair_key"] for pair in body["pairs"]] == [
        "creator:30|creator:40",
        "creator:10|creator:20",
    ]


@pytest.mark.asyncio
async def test_shared_average_is_true_average_with_baseline_context(
    auth_client: AsyncClient,
    async_db: AsyncSession,
    default_user: User,
) -> None:
    """The shared average is the real mean of shared issues, never a baseline proxy."""
    # creator:31's baseline: three solo-rated issues at 2.0 (average 2.0).
    _thread_solo, issues_solo = await _make_thread(
        async_db, default_user, title="Solo Baseline", issue_count=3, queue_position=1, read_through=3
    )
    for issue in issues_solo:
        await _confirm_identity(
            async_db, issue, creators=[{"id": 31, "name": "Writer Solo", "role": "writer"}]
        )
        await _rate(async_db, issue, rating=2.0, timestamp=D1)

    # The shared trio averages 5.0 — the pair must report 5.0, not 2.0.
    _thread_team, issues_team = await _make_thread(
        async_db, default_user, title="Strong Team", issue_count=3, queue_position=2, read_through=3
    )
    for issue in issues_team:
        await _confirm_identity(
            async_db,
            issue,
            creators=[
                {"id": 31, "name": "Writer Solo", "role": "writer"},
                {"id": 32, "name": "Artist Team", "role": "artist"},
            ],
        )
        await _rate(async_db, issue, rating=5.0, timestamp=D1)

    response = await auth_client.get(TEAM_CHEMISTRY_URL)
    assert response.status_code == 200
    body = response.json()

    team = body["pairs"][0]
    assert team["pair_key"] == "creator:31|creator:32"
    assert team["shared_rated_issue_count"] == 3
    assert team["shared_average_rating"] == pytest.approx(5.0)
    assert team["shared_median_rating"] == pytest.approx(5.0)
    assert team["shared_rating_distribution"].get("5") == 3

    members: dict[str, dict[str, Any]] = {
        str(m["canonical_creator_key"]): m for m in team["creators"]
    }
    writer = members["creator:31"]
    expected_baseline = pytest.approx((2.0 * 3 + 5.0 * 3) / 6)
    assert writer["baseline_rated_count"] == 6
    assert writer["baseline_average_rating"] == expected_baseline
    assert writer["difference_from_baseline"] == pytest.approx(5.0 - (2.0 * 3 + 5.0 * 3) / 6)
    artist = members["creator:32"]
    assert artist["baseline_rated_count"] == 3
    assert artist["difference_from_baseline"] == pytest.approx(0.0)
    assert writer["roles"] == ["writer"]
    assert artist["roles"] == ["artist"]


@pytest.mark.asyncio
async def test_shared_series_and_issue_refs_are_navigable(
    auth_client: AsyncClient,
    async_db: AsyncSession,
    default_user: User,
) -> None:
    """Drilldown references expose thread identity, issue numbers, and bounds."""
    thread_a, issues_a = await _make_thread(
        async_db, default_user, title="Alpha Team Run", issue_count=2, queue_position=1, read_through=2
    )
    thread_b, issues_b = await _make_thread(
        async_db, default_user, title="Beta Team Run", issue_count=1, queue_position=2, read_through=1
    )
    for index, issue in enumerate([*issues_a, *issues_b]):
        await _confirm_identity(
            async_db,
            issue,
            creators=[
                {"id": 41, "name": "Writer Quad", "role": "writer"},
                {"id": 42, "name": "Artist Quad", "role": "artist"},
            ],
        )
        await _rate(async_db, issue, rating=3.0, timestamp=D1 + timedelta(minutes=index))

    response = await auth_client.get(TEAM_CHEMISTRY_URL)
    assert response.status_code == 200
    body = response.json()
    team = body["pairs"][0]

    assert team["shared_rated_issue_count"] == 3
    assert team["max_shared_issue_refs"] == MAX_SHARED_ISSUE_REFS
    assert len(team["shared_issue_refs"]) == 3
    for ref in team["shared_issue_refs"]:
        assert ref["thread_id"] in {thread_a.id, thread_b.id}
        assert ref["thread_title"] in {"Alpha Team Run", "Beta Team Run"}
        assert ref["issue_number"] != ""
        assert ref["effective_rating"] == pytest.approx(3.0)
        assert ref["status"] == "read"

    series_by_thread = {series["thread_id"]: series for series in team["shared_series"]}
    assert series_by_thread[thread_a.id]["shared_issue_count"] == 2
    assert series_by_thread[thread_a.id]["thread_title"] == "Alpha Team Run"
    assert series_by_thread[thread_b.id]["shared_issue_count"] == 1


@pytest.mark.asyncio
async def test_partial_creator_metadata_is_reported_truthfully(
    auth_client: AsyncClient,
    async_db: AsyncSession,
    default_user: User,
) -> None:
    """Rated issues without confirmed metadata shrink results as lower bounds."""
    _thread_a, issues_a = await _make_thread(
        async_db, default_user, title="Credited", issue_count=3, queue_position=1, read_through=3
    )
    for issue in issues_a:
        await _confirm_identity(
            async_db,
            issue,
            creators=[
                {"id": 51, "name": "Writer Fifty", "role": "writer"},
                {"id": 52, "name": "Artist Fifty", "role": "artist"},
            ],
        )
        await _rate(async_db, issue, rating=4.0, timestamp=D1)

    # Rated but never credited: a metadata gap only, never negative evidence.
    _thread_b, issues_b = await _make_thread(
        async_db, default_user, title="Uncredited", issue_count=1, queue_position=2, read_through=1
    )
    await _rate(async_db, issues_b[0], rating=4.0, timestamp=D1)

    response = await auth_client.get(TEAM_CHEMISTRY_URL)
    assert response.status_code == 200
    body = response.json()
    coverage = body["coverage"]
    assert coverage["rated_issues_total"] == 4
    assert coverage["rated_issues_with_creator_metadata"] == 3
    assert coverage["ratings_complete"] is False
    # The pair still derives exactly its three actual shared issues.
    assert body["pairs"][0]["shared_rated_issue_count"] == 3


@pytest.mark.asyncio
async def test_issue_refs_respect_bounded_sample(
    auth_client: AsyncClient,
    async_db: AsyncSession,
    default_user: User,
) -> None:
    """A pair larger than the ref bound still reports its true shared count."""
    _thread_a, issues_a = await _make_thread(
        async_db, default_user, title="Long Team Run", issue_count=6, queue_position=1, read_through=6
    )
    for issue in issues_a:
        await _confirm_identity(
            async_db,
            issue,
            creators=[
                {"id": 61, "name": "Writer Six", "role": "writer"},
                {"id": 62, "name": "Artist Six", "role": "artist"},
            ],
        )
        await _rate(async_db, issue, rating=4.0, timestamp=D1)

    response = await auth_client.get(TEAM_CHEMISTRY_URL)
    assert response.status_code == 200
    body = response.json()
    team = body["pairs"][0]
    assert team["shared_rated_issue_count"] == 6
    assert len(team["shared_issue_refs"]) == MAX_SHARED_ISSUE_REFS
    assert body["pairs_total"] == 1


@pytest.mark.asyncio
async def test_query_cost_stays_bounded_for_growing_libraries(
    auth_client: AsyncClient,
    db_engine: AsyncEngine,
    async_db: AsyncSession,
    default_user: User,
) -> None:
    """The endpoint is served by a fixed bounded number of SELECT statements.

    Regression guard for the N+1 draft this issue's first implementation
    carried: every issue and thread had to be re-fetched one ``db.get`` at a
    time inside the aggregation loop, so wide libraries multiplied round trips.
    """
    _thread, issues = await _make_thread(
        async_db,
        default_user,
        title="Bound Test",
        issue_count=12,
        queue_position=1,
        read_through=12,
    )
    for issue in issues:
        await _confirm_identity(
            async_db,
            issue,
            creators=[
                {"id": 71, "name": "Writer Bound", "role": "writer"},
                {"id": 72, "name": "Artist Bound", "role": "artist"},
            ],
        )
        await _rate(async_db, issue, rating=4.0, timestamp=D1)

    with _captured_selects(db_engine) as statements:
        response = await auth_client.get(TEAM_CHEMISTRY_URL)
        assert response.status_code == 200

    assert len(statements) <= 6, (
        f"Team chemistry endpoint issued {len(statements)} SELECTs; the bounded "
        "pipeline must stay within its fixed query budget for any library size"
    )
