"""Focused API coverage for the bounded issue reader-context contract.

Issue #1401: one authenticated ``reader-context`` response for the active Roll
issue covering canonical-series analytics, exact crossover membership, and the
bounded local reading neighborhood.
"""

from datetime import UTC, datetime

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import Event, Issue, Thread, User
from app.models.continuity_rule import ContinuityRule
from app.models.dependency import Dependency
from app.models.dependency_group import DependencyGroup, DependencyGroupMembership
from app.models.external_identity import ExternalIdentity, IssueExternalIdentityMapping

D1 = datetime(2026, 1, 1, tzinfo=UTC)
D2 = datetime(2026, 1, 2, tzinfo=UTC)
D3 = datetime(2026, 1, 3, tzinfo=UTC)
D4 = datetime(2026, 1, 4, tzinfo=UTC)


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
    external_id: str,
    series_id: int,
    series_name: str,
) -> None:
    """Create a confirmed ComicVine issue identity mapping."""
    identity = ExternalIdentity(
        provider="comicvine",
        entity_type="issue",
        external_id=external_id,
        metadata_json={
            "issue_number": issue.issue_number,
            "volume_id": series_id,
            "volume_name": series_name,
        },
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


async def _make_group(
    db: AsyncSession,
    user: User,
    name: str,
    *,
    thread_id: int | None = None,
    issue_ids: tuple[int, ...] = (),
) -> DependencyGroup:
    """Create an owned dependency group with optional memberships."""
    group = DependencyGroup(user_id=user.id, name=name)
    db.add(group)
    await db.flush()
    if thread_id is not None:
        db.add(DependencyGroupMembership(group_id=group.id, thread_id=thread_id))
    for issue_id in issue_ids:
        db.add(DependencyGroupMembership(group_id=group.id, issue_id=issue_id))
    await db.flush()
    return group


async def _thanos_scenario(
    db: AsyncSession,
    user: User,
) -> tuple[Thread, list[Issue]]:
    """Build a four-issue series with confirmed identities and rates."""
    thread, issues = await _make_thread(
        db, user, title="Thanos", issue_count=4, queue_position=1, read_through=4
    )
    for index, issue in enumerate(issues[:3], start=1):
        await _confirm_identity(
            db,
            issue,
            external_id=f"cv-{index}",
            series_id=20764,
            series_name="Thanos",
        )
    await _confirm_identity(
        db,
        issues[3],
        external_id="cv-other",
        series_id=99999,
        series_name="Other",
    )
    await _rate(db, issues[0], rating=4.0, timestamp=D1)
    await _rate(db, issues[1], rating=3.5, timestamp=D2)
    await _rate(db, issues[2], rating=5.0, timestamp=D3)
    return thread, issues


@pytest.mark.asyncio
async def test_reader_context_ownership_and_missing_issue(
    auth_client,
    async_db: AsyncSession,
    default_user: User,
) -> None:
    """Another user's issue and a nonexistent issue return 404."""
    other_user = User(username="reader_context_other_owner")
    async_db.add(other_user)
    await async_db.flush()
    owned_thread, owned_issues = await _make_thread(
        async_db, default_user, title="Owned", issue_count=1, queue_position=1
    )
    hidden_thread, hidden_issues = await _make_thread(
        async_db, other_user, title="Hidden", issue_count=1, queue_position=2
    )

    owned = await auth_client.get(
        f"/api/v1/issues/{owned_issues[0].id}/reader-context"
    )
    hidden = await auth_client.get(
        f"/api/v1/issues/{hidden_issues[0].id}/reader-context"
    )
    missing = await auth_client.get("/api/v1/issues/999999/reader-context")

    assert owned.status_code == 200
    assert hidden.status_code == 404
    assert missing.status_code == 404


@pytest.mark.asyncio
async def test_reader_context_canonical_series_stats(
    auth_client,
    async_db: AsyncSession,
    default_user: User,
) -> None:
    """Confirmed identity yields canonical aggregates and previous issue."""
    _thread, issues = await _thanos_scenario(async_db, default_user)

    response = await auth_client.get(
        f"/api/v1/issues/{issues[1].id}/reader-context"
    )

    assert response.status_code == 200
    body = response.json()
    series = body["series"]
    assert series["identity_source"] == "comicvine"
    assert series["canonical_series_id"] == "20764"
    assert series["series_name"] == "Thanos"
    assert series["average_rating"] == pytest.approx(4.17)
    assert series["ratings_count"] == 3
    assert series["previous_issue"] == {
        "issue_id": issues[0].id,
        "issue_number": "1",
        "rating": 4.0,
    }
    assert [item["rating"] for item in series["recent_ratings"]] == [5.0, 3.5, 4.0]
    assert series["highest_rating"] == 5.0
    assert series["lowest_rating"] == 3.5


@pytest.mark.asyncio
async def test_reader_context_duplicate_rate_events_dedupe(
    auth_client,
    async_db: AsyncSession,
    default_user: User,
) -> None:
    """Multiple rate events for one issue count once with the latest winning."""
    _thread, issues = await _thanos_scenario(async_db, default_user)
    await _rate(async_db, issues[0], rating=2.5, timestamp=D4)

    response = await auth_client.get(
        f"/api/v1/issues/{issues[1].id}/reader-context"
    )

    series = response.json()["series"]
    assert series["ratings_count"] == 3
    assert series["average_rating"] == pytest.approx(3.67)
    assert series["recent_ratings"][0]["rating"] == 2.5
    assert series["highest_rating"] == 5.0
    assert series["lowest_rating"] == 2.5


@pytest.mark.asyncio
async def test_reader_context_currently_read_filtering(
    auth_client,
    async_db: AsyncSession,
    default_user: User,
) -> None:
    """Unread confirmed series issues do not contribute to canonical stats."""
    _thread, issues = await _thanos_scenario(async_db, default_user)
    issues[2].status = "unread"
    await async_db.flush()

    response = await auth_client.get(
        f"/api/v1/issues/{issues[1].id}/reader-context"
    )

    series = response.json()["series"]
    assert series["ratings_count"] == 2
    assert series["average_rating"] == pytest.approx(3.75)
    assert series["highest_rating"] == 4.0
    assert series["lowest_rating"] == 3.5
    assert [item["issue_id"] for item in series["recent_ratings"]] == [
        issues[1].id,
        issues[0].id,
    ]


@pytest.mark.asyncio
async def test_reader_context_unavailable_identity(
    auth_client,
    async_db: AsyncSession,
    default_user: User,
) -> None:
    """Missing canonical identity yields unavailable stats, never title fallback."""
    thread, issues = await _make_thread(
        async_db,
        default_user,
        title="No Identity",
        issue_count=2,
        queue_position=1,
        read_through=2,
    )
    await _rate(async_db, issues[0], rating=4.0, timestamp=D1)

    response = await auth_client.get(
        f"/api/v1/issues/{issues[1].id}/reader-context"
    )

    series = response.json()["series"]
    assert series["identity_source"] == "unavailable"
    assert series["canonical_series_id"] is None
    assert series["series_name"] is None
    assert series["average_rating"] is None
    assert series["ratings_count"] == 0
    assert series["recent_ratings"] == []
    assert series["highest_rating"] is None
    assert series["lowest_rating"] is None
    assert series["previous_issue"]["issue_id"] == issues[0].id


@pytest.mark.asyncio
async def test_reader_context_crossover_current_and_future_membership(
    auth_client,
    async_db: AsyncSession,
    default_user: User,
) -> None:
    """Current vs future vs thread-level crossover membership stays exact."""
    thread, issues = await _thanos_scenario(async_db, default_user)
    await _make_group(
        async_db,
        default_user,
        "Annihilation",
        issue_ids=(issues[3].id,),
    )
    await _make_group(
        async_db,
        default_user,
        "Onslaught",
        issue_ids=(issues[1].id,),
    )
    await _make_group(async_db, default_user, "ThreadWide", thread_id=thread.id)

    response = await auth_client.get(
        f"/api/v1/issues/{issues[1].id}/reader-context"
    )

    crossovers = response.json()["crossovers"]
    assert [item["name"] for item in crossovers] == [
        "Annihilation",
        "Onslaught",
        "ThreadWide",
    ]
    by_name = {item["name"]: item for item in crossovers}
    assert by_name["Annihilation"]["applies_to_current_issue"] is False
    assert by_name["Annihilation"]["next_member"] == {
        "issue_id": issues[3].id,
        "issue_number": "4",
    }
    assert by_name["Onslaught"]["applies_to_current_issue"] is True
    assert by_name["Onslaught"]["next_member"] is None
    assert by_name["ThreadWide"]["applies_to_current_issue"] is False
    assert by_name["ThreadWide"]["next_member"] is None


@pytest.mark.asyncio
async def test_reader_context_crossover_aggregates(
    auth_client,
    async_db: AsyncSession,
    default_user: User,
) -> None:
    """Crossover averages and read counts use exact owned members only."""
    _thread, issues = await _thanos_scenario(async_db, default_user)
    other_thread, other_issues = await _make_thread(
        async_db,
        default_user,
        title="Nova",
        issue_count=1,
        queue_position=2,
        read_through=1,
    )
    await _confirm_identity(
        async_db,
        other_issues[0],
        external_id="cv-nova",
        series_id=20764,
        series_name="Thanos",
    )
    await _rate(async_db, other_issues[0], rating=2.0, timestamp=D4)
    await _make_group(
        async_db,
        default_user,
        "Annihilation",
        issue_ids=(issues[0].id, issues[1].id, other_issues[0].id),
    )

    response = await auth_client.get(
        f"/api/v1/issues/{issues[1].id}/reader-context"
    )

    crossover = response.json()["crossovers"][0]
    assert crossover["name"] == "Annihilation"
    assert crossover["ratings_count"] == 3
    assert crossover["average_rating"] == pytest.approx(3.17)
    assert crossover["read_count"] == 2


@pytest.mark.asyncio
async def test_reader_context_local_chain_middle_bound(
    auth_client,
    async_db: AsyncSession,
    default_user: User,
) -> None:
    """A middle issue returns five nodes with previous/current/next/future."""
    _thread, issues = await _make_thread(
        async_db,
        default_user,
        title="Middle",
        issue_count=7,
        queue_position=1,
        read_through=7,
    )

    response = await auth_client.get(
        f"/api/v1/issues/{issues[3].id}/reader-context"
    )

    chain = response.json()["local_chain"]["issues"]
    assert [item["issue_id"] for item in chain] == [
        issues[1].id,
        issues[2].id,
        issues[3].id,
        issues[4].id,
        issues[5].id,
    ]
    assert [item["relation"] for item in chain] == [
        "previous",
        "previous",
        "current",
        "next",
        "future",
    ]


@pytest.mark.asyncio
async def test_reader_context_local_chain_start_and_end_clamped(
    auth_client,
    async_db: AsyncSession,
    default_user: User,
) -> None:
    """Start and end positions clamp the neighborhood at thread boundaries."""
    _thread, issues = await _make_thread(
        async_db,
        default_user,
        title="Clamped",
        issue_count=7,
        queue_position=1,
        read_through=7,
    )

    start = await auth_client.get(
        f"/api/v1/issues/{issues[0].id}/reader-context"
    )
    end = await auth_client.get(
        f"/api/v1/issues/{issues[6].id}/reader-context"
    )

    start_chain = start.json()["local_chain"]["issues"]
    assert [item["issue_id"] for item in start_chain] == [
        issues[0].id,
        issues[1].id,
        issues[2].id,
    ]
    assert [item["relation"] for item in start_chain] == [
        "current",
        "next",
        "future",
    ]
    end_chain = end.json()["local_chain"]["issues"]
    assert [item["issue_id"] for item in end_chain] == [
        issues[4].id,
        issues[5].id,
        issues[6].id,
    ]
    assert [item["relation"] for item in end_chain] == [
        "previous",
        "previous",
        "current",
    ]


@pytest.mark.asyncio
async def test_reader_context_edge_bound_and_deterministic_order(
    auth_client,
    async_db: AsyncSession,
    default_user: User,
) -> None:
    """Edges are capped at 20 and keep a deterministic ordering."""
    _thread, issues = await _make_thread(
        async_db,
        default_user,
        title="Edges",
        issue_count=5,
        queue_position=1,
        read_through=5,
    )
    other_thread, other_issues = await _make_thread(
        async_db,
        default_user,
        title="Targets",
        issue_count=25,
        queue_position=2,
        read_through=25,
    )
    for index, target in enumerate(other_issues):
        async_db.add(
            Dependency(
                source_issue_id=issues[2].id,
                target_issue_id=target.id,
                note=f"edge-{index}",
            )
        )
    await async_db.flush()

    first = await auth_client.get(
        f"/api/v1/issues/{issues[2].id}/reader-context"
    )
    second = await auth_client.get(
        f"/api/v1/issues/{issues[2].id}/reader-context"
    )

    edges = first.json()["local_chain"]["edges"]
    assert len(edges) == 20
    assert all(edge["kind"] == "dependency" for edge in edges)
    assert [edge["id"] for edge in edges] == sorted(edge["id"] for edge in edges)
    assert edges == second.json()["local_chain"]["edges"]


@pytest.mark.asyncio
async def test_reader_context_cross_thread_edge_without_expansion(
    auth_client,
    async_db: AsyncSession,
    default_user: User,
) -> None:
    """An edge may point outside the thread without expanding the neighborhood."""
    _thread, issues = await _make_thread(
        async_db,
        default_user,
        title="Neighborhood",
        issue_count=5,
        queue_position=1,
        read_through=5,
    )
    other_thread, other_issues = await _make_thread(
        async_db,
        default_user,
        title="Distant",
        issue_count=1,
        queue_position=2,
        read_through=1,
    )
    dependency = Dependency(
        source_issue_id=issues[2].id,
        target_issue_id=other_issues[0].id,
        note="cross-thread",
    )
    async_db.add(dependency)
    await async_db.flush()

    response = await auth_client.get(
        f"/api/v1/issues/{issues[2].id}/reader-context"
    )

    body = response.json()
    chain = body["local_chain"]
    assert [item["issue_id"] for item in chain["issues"]] == [
        issue.id for issue in issues
    ]
    assert other_issues[0].id not in {item["issue_id"] for item in chain["issues"]}
    assert chain["edges"] == [
        {
            "id": dependency.id,
            "kind": "dependency",
            "source_issue_id": issues[2].id,
            "target_issue_id": other_issues[0].id,
            "note": "cross-thread",
        }
    ]


@pytest.mark.asyncio
async def test_reader_context_continuity_rule_edges(
    auth_client,
    async_db: AsyncSession,
    default_user: User,
) -> None:
    """Issue-to-issue continuity rules surface as continuity edges once."""
    _thread, issues = await _make_thread(
        async_db,
        default_user,
        title="Rules",
        issue_count=5,
        queue_position=1,
        read_through=5,
    )
    rule = ContinuityRule(
        user_id=default_user.id,
        source_type="issue",
        source_id=issues[1].id,
        target_type="issue",
        target_id=issues[3].id,
        satisfaction_type="item_read",
        note="directive",
    )
    async_db.add(rule)
    await async_db.flush()

    response = await auth_client.get(
        f"/api/v1/issues/{issues[2].id}/reader-context"
    )

    edges = response.json()["local_chain"]["edges"]
    assert edges == [
        {
            "id": rule.id,
            "kind": "continuity",
            "source_issue_id": issues[1].id,
            "target_issue_id": issues[3].id,
            "note": "directive",
        }
    ]


@pytest.mark.asyncio
async def test_reader_context_missing_optional_data(
    auth_client,
    async_db: AsyncSession,
    default_user: User,
) -> None:
    """A lone issue returns an empty but well-formed decorative payload."""
    _thread, issues = await _make_thread(
        async_db,
        default_user,
        title="Lone",
        issue_count=1,
        queue_position=1,
    )

    response = await auth_client.get(
        f"/api/v1/issues/{issues[0].id}/reader-context"
    )

    body = response.json()
    assert body["issue_id"] == issues[0].id
    assert body["series"]["identity_source"] == "unavailable"
    assert body["series"]["previous_issue"] is None
    assert body["crossovers"] == []
    chain = body["local_chain"]
    assert len(chain["issues"]) == 1
    assert chain["issues"][0]["relation"] == "current"
    assert chain["issues"][0]["rating"] is None
    assert chain["issues"][0]["crossover_memberships"] == []
    assert chain["edges"] == []


@pytest.mark.asyncio
async def test_reader_context_no_synchronous_provider_dependency(
    auth_client,
    async_db: AsyncSession,
    default_user: User,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Reader-context never hydrates ComicVine synchronously."""
    _thread, issues = await _make_thread(
        async_db,
        default_user,
        title="Offline",
        issue_count=1,
        queue_position=1,
        read_through=1,
    )
    await _confirm_identity(
        async_db,
        issues[0],
        external_id="cv-offline",
        series_id=20764,
        series_name="Thanos",
    )

    async def _unexpected_call(*_args: object, **_kwargs: object) -> None:
        raise AssertionError("ComicVine provider was hydrated synchronously")

    monkeypatch.setattr(
        "app.services.comicvine_intelligence.schedule_issue_metadata_hydration",
        _unexpected_call,
    )
    monkeypatch.setattr(
        "app.services.comicvine_fallback.schedule_issue_metadata_hydration",
        _unexpected_call,
    )

    response = await auth_client.get(
        f"/api/v1/issues/{issues[0].id}/reader-context"
    )

    assert response.status_code == 200
    assert response.json()["series"]["identity_source"] == "comicvine"