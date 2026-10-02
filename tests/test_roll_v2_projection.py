"""Bounded Roll v2 bootstrap projection tests (issue #2717).

Covers the closure-critical acceptance contract for
``GET /api/v2/roll/bootstrap``: a constant 1-3 round-trip projection with no
per-row queries, non-null rollable issues with omission of exhausted threads,
#1401 canonical-series stats (split-thread aggregation, no composite
flattening), stored catalog run lengths, same-origin covers, capped group
routes, session last-read, #2102 fail-open recovery, and unchanged
session/partition semantics.
"""

from datetime import UTC, datetime

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import Event, Issue, ReadingSession, Thread, User
from app.models.dependency_group import DependencyGroup, DependencyGroupMembership
from app.models.external_identity import (
    ExternalIdentity,
    IssueExternalIdentityMapping,
    ThreadExternalSeriesMapping,
)
from app.services.roll_v2_projection import (
    build_cover_url,
    derive_identity_state,
    extract_cover_source,
    extract_volume,
    get_v2_rollable_projection,
)
from app.schemas.roll_v2 import IdentityState, RollableItem, RollLastRead

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
    """Create an owned thread with contiguous issues and a next pointer."""
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
            read_at=D1 if position <= read_through else None,
        )
        db.add(issue)
        issues.append(issue)
    await db.flush()
    if issue_count and read_through < issue_count:
        thread.next_unread_issue_id = issues[read_through].id
    await db.flush()
    return thread, issues


async def _confirm_identity(
    db: AsyncSession,
    issue: Issue,
    *,
    external_id: str,
    series_id: int,
    series_name: str,
    image_url: str | None = None,
    status: str = "confirmed",
) -> None:
    """Attach a stored ComicVine issue identity mapping."""
    metadata: dict[str, object] = {
        "issue_number": issue.issue_number,
        "volume_id": series_id,
        "volume_name": series_name,
    }
    if image_url is not None:
        metadata["image"] = {"medium_url": image_url}
    identity = ExternalIdentity(
        provider="comicvine",
        entity_type="issue",
        external_id=external_id,
        metadata_json=metadata,
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


async def _catalog_series(
    db: AsyncSession,
    *,
    external_id: str,
    name: str,
    count_of_issues: int | None = None,
) -> ExternalIdentity:
    """Store one shared catalog series row with provider run length."""
    metadata: dict[str, object] = {"name": name}
    if count_of_issues is not None:
        metadata["count_of_issues"] = count_of_issues
    identity = ExternalIdentity(
        provider="comicvine",
        entity_type="series",
        external_id=external_id,
        metadata_json=metadata,
    )
    db.add(identity)
    await db.flush()
    return identity


async def _rate(
    db: AsyncSession,
    issue: Issue,
    *,
    rating: float,
    timestamp: datetime,
    session_id: int | None = None,
) -> None:
    """Record one rate event for an issue."""
    db.add(
        Event(
            type="rate",
            thread_id=issue.thread_id,
            issue_id=issue.id,
            issue_number=issue.issue_number,
            rating=rating,
            timestamp=timestamp,
            session_id=session_id,
        )
    )
    await db.flush()


async def _active_session(db: AsyncSession, user: User) -> ReadingSession:
    """Create an active reading session for last-read tests."""
    session = ReadingSession(user_id=user.id, start_die=6)
    db.add(session)
    await db.flush()
    return session


class _ExecuteCounter:
    """Count database round trips through an AsyncSession."""

    def __init__(self, db: AsyncSession) -> None:
        """Wrap the session's execute entry point."""
        self.calls = 0
        from collections.abc import Awaitable, Callable

        self._original: Callable[..., Awaitable[object]] = db.execute  # type: ignore[assignment]

    async def __call__(self, *args: object, **kwargs: object) -> object:
        """Count one round trip and delegate to the real execute."""
        self.calls += 1
        return await self._original(*args, **kwargs)


async def _projection_calls(
    db: AsyncSession,
    monkeypatch: pytest.MonkeyPatch,
    **kwargs: object,
) -> tuple[int, tuple[list[RollableItem], RollLastRead | None, list[int]]]:
    """Run the projection while counting its database round trips."""
    counter = _ExecuteCounter(db)
    monkeypatch.setattr(db, "execute", counter)
    result = await get_v2_rollable_projection(db, **kwargs)
    return counter.calls, result


class TestPureHelpers:
    """Unit coverage for the synchronous projection helpers."""

    def test_extract_volume_supports_both_stored_shapes(self) -> None:
        """Volume parsing handles nested and flat stored metadata."""
        assert extract_volume({"volume": {"id": 7, "name": "Saga"}}) == (7, "Saga")
        assert extract_volume({"volume_id": 9, "volume_name": "Thanos"}) == (9, "Thanos")
        assert extract_volume(None) == (None, None)
        assert extract_volume({}) == (None, None)

    def test_cover_url_is_same_origin_proxy_only(self) -> None:
        """Covers are proxied; raw or non-remote sources yield nulls."""
        proxied = build_cover_url("https://comicvine.gamespot.com/a.jpg")
        assert proxied is not None
        assert proxied.startswith("/api/v1/images/optimize?url=")
        assert "comicvine.gamespot.com" not in proxied.split("?", 1)[0]
        assert "https://" not in proxied.split("?", 1)[0]
        assert build_cover_url(None) is None
        assert build_cover_url("data:image/png;base64,AAA") is None

    def test_extract_cover_source_prefers_direct_then_image_dict(self) -> None:
        """Cover extraction never fabricates a URL from missing metadata."""
        assert extract_cover_source({"image_url": "https://img/a.jpg"}) == "https://img/a.jpg"
        assert (
            extract_cover_source({"image": {"medium_url": "https://img/b.jpg"}})
            == "https://img/b.jpg"
        )
        assert extract_cover_source(None) is None
        assert extract_cover_source({}) is None

    def test_derive_identity_state_covers_frozen_enum(self) -> None:
        """Derived states distinguish confirmed, candidate, and review cases."""
        assert derive_identity_state(["4000-1"], 0, True) == IdentityState.CONFIRMED
        assert derive_identity_state(["a", "b"], 0, True) == IdentityState.CONFLICTING
        assert derive_identity_state([], 1, True) == IdentityState.CANDIDATE
        assert derive_identity_state([], 3, True) == IdentityState.AMBIGUOUS
        assert derive_identity_state([], 0, False) == IdentityState.UNRESOLVED


@pytest.mark.asyncio
async def test_projection_query_budget_empty_normal_and_d100(
    async_db: AsyncSession, default_user: User, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The projection costs 1-3 round trips and does not grow per row."""
    session = await _active_session(async_db, default_user)

    empty_calls, (empty_items, _, _) = await _projection_calls(
        async_db,
        monkeypatch,
        user_id=default_user.id,
        die_size=100,
        excluded_thread_ids=[],
        session_id=session.id,
    )
    assert empty_items == []
    assert 1 <= empty_calls <= 3

    for position in range(1, 4):
        thread, _ = await _make_thread(
            async_db, default_user, title=f"Normal {position}", issue_count=2, queue_position=position
        )
        assert thread.id is not None
    normal_calls, (normal_items, _, _) = await _projection_calls(
        async_db,
        monkeypatch,
        user_id=default_user.id,
        die_size=6,
        excluded_thread_ids=[],
        session_id=session.id,
    )
    assert len(normal_items) == 3
    assert 1 <= normal_calls <= 3

    for position in range(4, 104):
        await _make_thread(
            async_db,
            default_user,
            title=f"Bulk {position}",
            issue_count=2,
            queue_position=position,
        )
    d100_calls, (d100_items, _, _) = await _projection_calls(
        async_db,
        monkeypatch,
        user_id=default_user.id,
        die_size=100,
        excluded_thread_ids=[],
        session_id=session.id,
    )
    assert len(d100_items) == 100
    assert 1 <= d100_calls <= 3
    assert d100_calls == normal_calls


@pytest.mark.asyncio
async def test_omitted_threads_hold_no_valid_roll_target(
    async_db: AsyncSession, default_user: User
) -> None:
    """Threads without a next unread issue are omitted, never null-issued."""
    good, _ = await _make_thread(
        async_db, default_user, title="Good", issue_count=2, queue_position=1
    )
    exhausted, _ = await _make_thread(
        async_db, default_user, title="Exhausted", issue_count=1, queue_position=2, read_through=1
    )
    stale, stale_issues = await _make_thread(
        async_db, default_user, title="Stale", issue_count=2, queue_position=3, read_through=1
    )
    # Corrupt the pointer to reference an already-read issue: no readable
    # next issue exists until pointer repair runs.
    stale.next_unread_issue_id = stale_issues[0].id
    await async_db.flush()
    assert good.next_unread_issue_id is not None

    session = await _active_session(async_db, default_user)
    items, _, omitted = await get_v2_rollable_projection(
        async_db,
        user_id=default_user.id,
        die_size=6,
        excluded_thread_ids=[],
        session_id=session.id,
    )
    assert [item.thread.id for item in items] == [good.id]
    assert all(item.issue is not None for item in items)
    assert sorted(omitted) == sorted([exhausted.id, stale.id])
    # Omitted threads resolve to no readable next issue: the pointer is null
    # or references a missing/read issue, so neither is a valid roll target.
    for thread_id in omitted:
        thread = await async_db.get(Thread, thread_id)
        assert thread is not None
        if thread.next_unread_issue_id is None:
            continue
        pointed = await async_db.get(Issue, thread.next_unread_issue_id)
        assert pointed is None or pointed.status != "unread"


@pytest.mark.asyncio
async def test_canonical_stats_use_effective_ratings(async_db: AsyncSession, default_user: User) -> None:
    """Average/count/latest follow #1401 distinct-issue effective ratings."""
    thread, issues = await _make_thread(
        async_db, default_user, title="Thanos", issue_count=4, queue_position=1, read_through=3
    )
    for position, issue in enumerate(issues[:3]):
        await _confirm_identity(
            async_db, issue, external_id=f"4000-{position}", series_id=20764, series_name="Thanos"
        )
    await _confirm_identity(
        async_db, issues[3], external_id="4000-9", series_id=20764, series_name="Thanos"
    )
    await _rate(async_db, issues[0], rating=4.0, timestamp=D1)
    await _rate(async_db, issues[1], rating=3.5, timestamp=D2)
    await _rate(async_db, issues[2], rating=5.0, timestamp=D3)

    session = await _active_session(async_db, default_user)
    items, _, _ = await get_v2_rollable_projection(
        async_db,
        user_id=default_user.id,
        die_size=6,
        excluded_thread_ids=[],
        session_id=session.id,
    )
    assert len(items) == 1
    item = items[0]
    assert item.identity.source == "comicvine"
    assert item.identity.canonical_series_id == "20764"
    assert item.issue.canonical_series_title == "Thanos"
    assert item.reader.progress_scope.value == "canonical_series_run"
    assert item.reader.rating_count == 3
    assert item.reader.average_rating == pytest.approx(4.17)
    assert item.reader.latest_rating == 5.0
    assert item.reader.read_count == 3
    assert thread.id == item.thread.id


@pytest.mark.asyncio
async def test_duplicate_rate_events_count_once_latest_wins(
    async_db: AsyncSession, default_user: User
) -> None:
    """Re-rating one issue keeps a single distinct contribution."""
    _, issues = await _make_thread(
        async_db, default_user, title="Thanos", issue_count=4, queue_position=1, read_through=3
    )
    for position, issue in enumerate(issues[:3]):
        await _confirm_identity(
            async_db, issue, external_id=f"4000-{position}", series_id=20764, series_name="Thanos"
        )
    # Next unread issue also needs confirmed identity for canonical series resolution.
    await _confirm_identity(
        async_db, issues[3], external_id="4000-9", series_id=20764, series_name="Thanos"
    )
    await _rate(async_db, issues[0], rating=4.0, timestamp=D1)
    await _rate(async_db, issues[1], rating=3.5, timestamp=D2)
    await _rate(async_db, issues[2], rating=5.0, timestamp=D3)
    await _rate(async_db, issues[0], rating=2.5, timestamp=D4)

    session = await _active_session(async_db, default_user)
    items, _, _ = await get_v2_rollable_projection(
        async_db,
        user_id=default_user.id,
        die_size=6,
        excluded_thread_ids=[],
        session_id=session.id,
    )
    assert items[0].reader.rating_count == 3
    assert items[0].reader.average_rating == pytest.approx(3.67)
    assert items[0].reader.latest_rating == 2.5


@pytest.mark.asyncio
async def test_unread_confirmed_issues_do_not_contribute(
    async_db: AsyncSession, default_user: User
) -> None:
    """Only currently-read issues feed canonical stats."""
    _, issues = await _make_thread(
        async_db, default_user, title="Thanos", issue_count=4, queue_position=1, read_through=3
    )
    for position, issue in enumerate(issues[:3]):
        await _confirm_identity(
            async_db, issue, external_id=f"4000-{position}", series_id=20764, series_name="Thanos"
        )
    # Next unread issue also needs confirmed identity for canonical series resolution.
    await _confirm_identity(
        async_db, issues[3], external_id="4000-9", series_id=20764, series_name="Thanos"
    )
    await _rate(async_db, issues[0], rating=4.0, timestamp=D1)
    await _rate(async_db, issues[1], rating=3.5, timestamp=D2)
    await _rate(async_db, issues[2], rating=5.0, timestamp=D3)
    issues[2].status = "unread"
    await async_db.flush()

    session = await _active_session(async_db, default_user)
    items, _, _ = await get_v2_rollable_projection(
        async_db,
        user_id=default_user.id,
        die_size=6,
        excluded_thread_ids=[],
        session_id=session.id,
    )
    assert items[0].reader.rating_count == 2
    assert items[0].reader.average_rating == pytest.approx(3.75)
    assert items[0].reader.read_count == 2


@pytest.mark.asyncio
async def test_split_threads_aggregate_same_series(
    async_db: AsyncSession, default_user: User
) -> None:
    """Two ComicPile threads for one provider volume share canonical stats."""
    _, first_issues = await _make_thread(
        async_db, default_user, title="Thanos A", issue_count=3, queue_position=1, read_through=2
    )
    _, second_issues = await _make_thread(
        async_db, default_user, title="Thanos B", issue_count=3, queue_position=2, read_through=2
    )
    await _confirm_identity(
        async_db, first_issues[0], external_id="4000-1", series_id=20764, series_name="Thanos"
    )
    await _confirm_identity(
        async_db, first_issues[1], external_id="4000-2", series_id=20764, series_name="Thanos"
    )
    # Next unread issue for first thread also needs confirmed identity.
    await _confirm_identity(
        async_db, first_issues[2], external_id="4000-5", series_id=20764, series_name="Thanos"
    )
    await _confirm_identity(
        async_db, second_issues[0], external_id="4000-3", series_id=20764, series_name="Thanos"
    )
    await _confirm_identity(
        async_db, second_issues[1], external_id="4000-4", series_id=20764, series_name="Thanos"
    )
    # Next unread issue for second thread also needs confirmed identity.
    await _confirm_identity(
        async_db, second_issues[2], external_id="4000-6", series_id=20764, series_name="Thanos"
    )
    await _rate(async_db, first_issues[0], rating=4.0, timestamp=D1)
    await _rate(async_db, second_issues[0], rating=2.0, timestamp=D2)

    session = await _active_session(async_db, default_user)
    items, _, _ = await get_v2_rollable_projection(
        async_db,
        user_id=default_user.id,
        die_size=6,
        excluded_thread_ids=[],
        session_id=session.id,
    )
    assert len(items) == 2
    for item in items:
        assert item.identity.canonical_series_id == "20764"
        assert item.reader.rating_count == 2
        assert item.reader.average_rating == pytest.approx(3.0)
        assert item.reader.read_count == 4


@pytest.mark.asyncio
async def test_composite_threads_do_not_flatten_volumes(
    async_db: AsyncSession, default_user: User
) -> None:
    """Mixed-volume threads resolve canonical identity from the next issue only."""
    mixed, mixed_issues = await _make_thread(
        async_db, default_user, title="Mixed", issue_count=3, queue_position=1, read_through=2
    )
    # Next unread issue (position 3) belongs to volume 2 while earlier issues
    # belong to volume 1: the row must report volume 2, not a flattened mix.
    await _confirm_identity(
        async_db, mixed_issues[0], external_id="4000-1", series_id=1, series_name="Alpha"
    )
    await _confirm_identity(
        async_db, mixed_issues[1], external_id="4000-2", series_id=1, series_name="Alpha"
    )
    await _confirm_identity(
        async_db, mixed_issues[2], external_id="4000-3", series_id=2, series_name="Beta"
    )
    await _rate(async_db, mixed_issues[0], rating=5.0, timestamp=D1)

    session = await _active_session(async_db, default_user)
    items, _, _ = await get_v2_rollable_projection(
        async_db,
        user_id=default_user.id,
        die_size=6,
        excluded_thread_ids=[],
        session_id=session.id,
    )
    assert len(items) == 1
    assert mixed.id == items[0].thread.id
    assert items[0].identity.canonical_series_id == "2"
    assert items[0].issue.canonical_series_title == "Beta"
    # Volume 2 has no read issues yet, so stats stay empty rather than
    # borrowing volume 1's rating.
    assert items[0].reader.rating_count == 0
    assert items[0].reader.average_rating is None


@pytest.mark.asyncio
async def test_run_length_comes_from_catalog_and_nullable_when_unknown(
    async_db: AsyncSession, default_user: User
) -> None:
    """canonical_series_run.issue_count is the stored full volume size."""
    _, known_issues = await _make_thread(
        async_db, default_user, title="Known", issue_count=3, queue_position=1, read_through=2
    )
    _, unknown_issues = await _make_thread(
        async_db, default_user, title="Unknown", issue_count=3, queue_position=2, read_through=2
    )
    # Confirm identity for read issues so series aggregates query returns rows.
    await _confirm_identity(
        async_db, known_issues[0], external_id="4000-1", series_id=20764, series_name="Thanos"
    )
    await _confirm_identity(
        async_db, known_issues[1], external_id="4000-2", series_id=20764, series_name="Thanos"
    )
    # Next unread issue also needs confirmed identity for canonical series resolution.
    await _confirm_identity(
        async_db, known_issues[2], external_id="4000-3", series_id=20764, series_name="Thanos"
    )
    await _confirm_identity(
        async_db, unknown_issues[2], external_id="4000-4", series_id=99999, series_name="Lost"
    )
    await _catalog_series(async_db, external_id="20764", name="Thanos", count_of_issues=12)

    session = await _active_session(async_db, default_user)
    items, _, _ = await get_v2_rollable_projection(
        async_db,
        user_id=default_user.id,
        die_size=6,
        excluded_thread_ids=[],
        session_id=session.id,
    )
    by_title = {item.thread.title: item for item in items}
    assert by_title["Known"].reader.issue_count == 12
    assert by_title["Known"].reader.progress_scope.value == "canonical_series_run"
    assert by_title["Unknown"].reader.issue_count is None


@pytest.mark.asyncio
async def test_thread_fallback_progress_without_identity(
    async_db: AsyncSession, default_user: User
) -> None:
    """Unavailable identity falls back to thread-scoped progress."""
    _, _ = await _make_thread(
        async_db, default_user, title="Plain", issue_count=4, queue_position=1, read_through=1
    )
    session = await _active_session(async_db, default_user)
    items, _, _ = await get_v2_rollable_projection(
        async_db,
        user_id=default_user.id,
        die_size=6,
        excluded_thread_ids=[],
        session_id=session.id,
    )
    assert len(items) == 1
    assert items[0].identity.source == "unavailable"
    assert items[0].identity.canonical_series_id is None
    assert items[0].reader.progress_scope.value == "thread"
    assert items[0].reader.read_count == 1
    assert items[0].reader.issue_count == 4
    assert items[0].reader.latest_rating is None
    assert items[0].reader.average_rating is None


@pytest.mark.asyncio
async def test_cover_is_same_origin_proxy_only(
    async_db: AsyncSession, default_user: User
) -> None:
    """Stored covers surface as proxy URLs; raw URLs never leak."""
    _, with_cover = await _make_thread(
        async_db, default_user, title="Cover", issue_count=2, queue_position=1, read_through=1
    )
    _, bare = await _make_thread(
        async_db, default_user, title="Bare", issue_count=2, queue_position=2, read_through=1
    )
    await _confirm_identity(
        async_db,
        with_cover[1],
        external_id="4000-1",
        series_id=5,
        series_name="Covered",
        image_url="https://comicvine.gamespot.com/a/uploads/scale_large/0/1/cover.jpg",
    )
    await _confirm_identity(
        async_db, bare[1], external_id="4000-2", series_id=6, series_name="Bare"
    )
    session = await _active_session(async_db, default_user)
    items, _, _ = await get_v2_rollable_projection(
        async_db,
        user_id=default_user.id,
        die_size=6,
        excluded_thread_ids=[],
        session_id=session.id,
    )
    by_title = {item.thread.title: item for item in items}
    cover = by_title["Cover"].issue.cover_url
    assert cover is not None
    assert cover.startswith("/api/v1/images/optimize?url=")
    assert "comicvine.gamespot.com" not in cover.split("?", 1)[0]
    assert by_title["Bare"].issue.cover_url is None


@pytest.mark.asyncio
async def test_routes_are_capped_group_references(
    async_db: AsyncSession, default_user: User
) -> None:
    """At most three group routes surface with an overflow count."""
    thread, issues = await _make_thread(
        async_db, default_user, title="Routed", issue_count=2, queue_position=1, read_through=1
    )
    for index in range(5):
        group = DependencyGroup(user_id=default_user.id, name=f"Crossover {index:02d}")
        async_db.add(group)
        await async_db.flush()
        async_db.add(
            DependencyGroupMembership(
                group_id=group.id,
                thread_id=thread.id if index % 2 == 0 else None,
                issue_id=issues[1].id if index % 2 == 1 else None,
            )
        )
    await async_db.flush()

    session = await _active_session(async_db, default_user)
    items, _, _ = await get_v2_rollable_projection(
        async_db,
        user_id=default_user.id,
        die_size=6,
        excluded_thread_ids=[],
        session_id=session.id,
    )
    assert len(items) == 1
    assert len(items[0].routes) == 3
    assert all(route.kind.value == "group" for route in items[0].routes)
    assert items[0].overflow_routes_count == 2


@pytest.mark.asyncio
async def test_last_read_comes_from_latest_session_rate_event(
    async_db: AsyncSession, default_user: User
) -> None:
    """Session last-read reflects the newest rate event, not the next issue."""
    thread, issues = await _make_thread(
        async_db, default_user, title="Reading", issue_count=3, queue_position=1, read_through=1
    )
    session = await _active_session(async_db, default_user)
    other_session = ReadingSession(user_id=default_user.id, start_die=6)
    async_db.add(other_session)
    await async_db.flush()
    await _rate(async_db, issues[0], rating=3.0, timestamp=D1, session_id=session.id)
    await _rate(async_db, issues[1], rating=4.5, timestamp=D3, session_id=session.id)
    # A newer event in another session must not leak into this session's read.
    await _rate(async_db, issues[0], rating=5.0, timestamp=D4, session_id=other_session.id)

    items, last_read, _ = await get_v2_rollable_projection(
        async_db,
        user_id=default_user.id,
        die_size=6,
        excluded_thread_ids=[],
        session_id=session.id,
    )
    assert len(items) == 1
    assert last_read is not None
    assert last_read.issue_id == issues[1].id
    assert last_read.issue_number == issues[1].issue_number
    assert last_read.thread_id == thread.id
    assert last_read.thread_title == thread.title
    assert last_read.read_at == D3


@pytest.mark.asyncio
async def test_last_read_absent_without_session_rate_events(
    async_db: AsyncSession, default_user: User
) -> None:
    """Sessions without ratings expose a null last-read."""
    await _make_thread(
        async_db, default_user, title="Unread", issue_count=2, queue_position=1
    )
    session = await _active_session(async_db, default_user)
    _, last_read, _ = await get_v2_rollable_projection(
        async_db,
        user_id=default_user.id,
        die_size=6,
        excluded_thread_ids=[],
        session_id=session.id,
    )
    assert last_read is None


@pytest.mark.asyncio
async def test_v2_endpoint_shape_and_session_semantics(
    auth_client, async_db: AsyncSession, default_user: User
) -> None:
    """v2 replaces roll_pool with rollable while preserving session fields."""
    await _make_thread(
        async_db, default_user, title="Endpoint", issue_count=2, queue_position=1
    )
    v1 = await auth_client.get("/api/v1/roll/bootstrap")
    assert v1.status_code == 200
    v2 = await auth_client.get("/api/v2/roll/bootstrap")
    assert v2.status_code == 200
    v1_body = v1.json()
    v2_body = v2.json()
    assert "roll_pool" not in v2_body
    assert isinstance(v2_body["rollable"], list)
    assert "last_read" in v2_body
    for field in (
        "session_id",
        "user_id",
        "current_die",
        "pending_thread_id",
        "session_mode",
        "bandwidth",
        "snoozed_count",
        "blocked_count",
        "stale_thread_count",
        "timezone",
    ):
        assert v2_body[field] == v1_body[field], field
    assert all(item["issue"] is not None for item in v2_body["rollable"])


@pytest.mark.asyncio
async def test_v2_has_no_unversioned_alias(auth_client) -> None:
    """The v2 contract lives only under /api/v2/roll/bootstrap."""
    v1 = await auth_client.get("/api/roll/bootstrap")
    assert v1.status_code == 200
    assert "roll_pool" in v1.json()
    assert "rollable" not in v1.json()


@pytest.mark.asyncio
async def test_v2_survives_provider_outage(
    auth_client, async_db: AsyncSession, default_user: User, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A ComicVine outage never breaks bootstrap (stored data only)."""
    from comic_pile import comicvine_provider

    async def _boom(*args: object, **kwargs: object):
        raise comicvine_provider.ComicVineError("provider down")

    monkeypatch.setattr(comicvine_provider.ComicVineClient, "request", _boom)
    await _make_thread(
        async_db, default_user, title="Offline", issue_count=2, queue_position=1
    )
    response = await auth_client.get("/api/v2/roll/bootstrap")
    assert response.status_code == 200
    assert isinstance(response.json()["rollable"], list)


@pytest.mark.asyncio
async def test_v2_preserves_fail_open_recovery(
    auth_client, async_db: AsyncSession, default_user: User, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The #2102 continuity-capacity failure yields valid bootstrap, null recovery."""
    from fastapi import HTTPException

    from app import roll_recovery

    async def _too_large(*args: object, **kwargs: object):
        raise HTTPException(
            status_code=422, detail={"code": "continuity_graph_too_large", "limit": 5000}
        )

    monkeypatch.setattr(roll_recovery, "resolve_continuity_chains", _too_large)
    thread, _ = await _make_thread(
        async_db, default_user, title="Pending", issue_count=2, queue_position=1
    )
    bootstrap = await auth_client.get("/api/v2/roll/bootstrap")
    assert bootstrap.status_code == 200
    session_id = bootstrap.json()["session_id"]
    session = await async_db.get(ReadingSession, session_id)
    assert session is not None
    session.pending_thread_id = thread.id
    await async_db.flush()
    retry = await auth_client.get("/api/v2/roll/bootstrap")
    assert retry.status_code == 200
    body = retry.json()
    assert body["pending_thread_id"] == thread.id
    assert body["roll_recovery"] is None
    assert isinstance(body["rollable"], list)


@pytest.mark.asyncio
async def test_thread_series_mapping_state_reported(
    async_db: AsyncSession, default_user: User
) -> None:
    """Thread-level series evidence surfaces without becoming canonical identity."""
    thread, issues = await _make_thread(
        async_db, default_user, title="Mapped", issue_count=2, queue_position=1, read_through=1
    )
    series = await _catalog_series(async_db, external_id="42", name="Mapped Series")
    async_db.add(
        ThreadExternalSeriesMapping(
            thread_id=thread.id,
            external_identity_id=series.id,
            status="confirmed",
            confidence=0.9,
        )
    )
    await async_db.flush()
    session = await _active_session(async_db, default_user)
    items, _, _ = await get_v2_rollable_projection(
        async_db,
        user_id=default_user.id,
        die_size=6,
        excluded_thread_ids=[],
        session_id=session.id,
    )
    assert len(items) == 1
    # No confirmed *issue* identity: canonical stats stay null per #1401 even
    # though thread-level series evidence exists.
    assert items[0].identity.series_mapping_state == IdentityState.CONFIRMED
    assert items[0].identity.canonical_series_id is None
    assert items[0].reader.progress_scope.value == "thread"
    assert issues[1].id == items[0].issue.id
