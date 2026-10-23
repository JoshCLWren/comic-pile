"""Database-backed parity, mutation sensitivity, and measured fixture coverage."""

from datetime import UTC, datetime
from time import perf_counter

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import Event, ExternalIdentity, User
from app.schemas.roll_v2 import RollLastRead
from app.services.roll_v2_parity import compare_roll_projection
from app.services.roll_v2_projection import get_v2_rollable_projection
from tests.test_roll_v2_projection import (
    D1,
    D2,
    _active_session,
    _catalog_series,
    _confirm_identity,
    _make_thread,
    _projection_calls,
    _rate,
)


@pytest.mark.asyncio
@pytest.mark.parametrize("pool_size", [0, 1, 20, 100])
async def test_real_projection_agrees_with_reference(
    async_db: AsyncSession,
    default_user: User,
    pool_size: int,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Compare actual production output at representative candidate sizes."""
    reading_session = await _active_session(async_db, default_user)
    for position in range(pool_size):
        await _make_thread(
            async_db,
            default_user,
            title=f"Parity {position}",
            issue_count=2,
            queue_position=position + 1,
            read_through=1,
        )
    started = perf_counter()
    calls, (items, last_read, _) = await _projection_calls(
        async_db,
        monkeypatch,
        user_id=default_user.id,
        session_id=reading_session.id,
        die_size=max(1, pool_size),
        excluded_thread_ids=[],
    )
    projection_ms = (perf_counter() - started) * 1000
    assert 1 <= calls <= 3
    report = await compare_roll_projection(
        async_db,
        user_id=default_user.id,
        session_id=reading_session.id,
        items=items,
        last_read=last_read,
    )
    print(
        f"pool={pool_size} projection_queries={calls} projection_ms={projection_ms:.2f} "
        f"reference_ms={report.reference_ms:.2f}"
    )
    assert report.compared_items == pool_size
    assert report.reference_ms >= 0
    assert report.differences == ()


@pytest.mark.asyncio
async def test_parity_reports_deliberately_wrong_frontier(
    async_db: AsyncSession,
    default_user: User,
) -> None:
    """A corrupted real response must produce a named, actionable mismatch."""
    reading_session = await _active_session(async_db, default_user)
    thread, issues = await _make_thread(
        async_db,
        default_user,
        title="Mismatch",
        issue_count=2,
        queue_position=1,
    )
    items, last_read, _ = await get_v2_rollable_projection(
        async_db,
        user_id=default_user.id,
        session_id=reading_session.id,
        die_size=6,
        excluded_thread_ids=[],
    )
    items[0].issue.id = issues[1].id
    report = await compare_roll_projection(
        async_db,
        user_id=default_user.id,
        session_id=reading_session.id,
        items=items,
        last_read=last_read,
    )
    difference = next(value for value in report.differences if value.field == "issue.id")
    assert difference.thread_id == thread.id
    assert difference.expected == issues[0].id
    assert difference.actual == issues[1].id


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "volume_shape,volume_id",
    [
        ("flat", 20764),
        ("flat", "20764"),
        ("flat", 20764.0),
        ("nested", "20764"),
        ("nested", 20764.0),
    ],
)
async def test_parity_checks_canonical_ratings_and_detects_a_changed_average(
    async_db: AsyncSession,
    default_user: User,
    volume_id: int | str | float,
    volume_shape: str,
) -> None:
    """Independent history aggregation detects changes to production rating math."""
    thread, issues = await _make_thread(
        async_db,
        default_user,
        title="Canonical",
        issue_count=3,
        queue_position=1,
        read_through=2,
    )
    for position, issue in enumerate(issues):
        await _confirm_identity(
            async_db,
            issue,
            external_id=f"4000-parity-{position}",
            series_id=20764,
            series_name="Canonical",
        )
    for identity in (
        await async_db.scalars(
            select(ExternalIdentity).where(
                ExternalIdentity.provider == "comicvine",
                ExternalIdentity.entity_type == "issue",
            )
        )
    ).all():
        metadata = dict(identity.metadata_json or {})
        if volume_shape == "nested":
            metadata.pop("volume_id", None)
            metadata["volume"] = {"id": volume_id, "name": "Canonical"}
        else:
            metadata["volume_id"] = volume_id
        identity.metadata_json = metadata
    await async_db.flush()
    await _catalog_series(async_db, external_id="20764", name="Canonical", count_of_issues=12)
    await _rate(async_db, issues[0], rating=3.0, timestamp=D1)
    await _rate(async_db, issues[0], rating=4.0, timestamp=D2)
    await _rate(async_db, issues[1], rating=5.0, timestamp=D2)
    reading_session = await _active_session(async_db, default_user)
    items, last_read, _ = await get_v2_rollable_projection(
        async_db,
        user_id=default_user.id,
        session_id=reading_session.id,
        die_size=6,
        excluded_thread_ids=[],
    )
    report = await compare_roll_projection(
        async_db,
        user_id=default_user.id,
        session_id=reading_session.id,
        items=items,
        last_read=last_read,
    )
    assert report.differences == ()
    items[0].reader.average_rating = 0.0
    changed = await compare_roll_projection(
        async_db,
        user_id=default_user.id,
        session_id=reading_session.id,
        items=items,
        last_read=last_read,
    )
    assert any(
        row.field == "reader.average_rating" and row.thread_id == thread.id
        for row in changed.differences
    )


@pytest.mark.asyncio
async def test_parity_last_read_uses_current_number_and_null_rating_events(
    async_db: AsyncSession,
    default_user: User,
) -> None:
    """A renamed Issue and a null rating retain production last-read semantics."""
    reading_session = await _active_session(async_db, default_user)
    thread, issues = await _make_thread(
        async_db,
        default_user,
        title="Last read",
        issue_count=2,
        queue_position=1,
        read_through=1,
    )
    async_db.add(
        Event(
            type="rate",
            session_id=reading_session.id,
            thread_id=thread.id,
            issue_id=issues[0].id,
            issue_number="old-number",
            rating=None,
            timestamp=datetime.now(UTC),
        )
    )
    issues[0].issue_number = "renamed"
    await async_db.flush()
    items, last_read, _ = await get_v2_rollable_projection(
        async_db,
        user_id=default_user.id,
        session_id=reading_session.id,
        die_size=6,
        excluded_thread_ids=[],
    )
    assert last_read is not None and last_read.issue_number == "renamed"
    report = await compare_roll_projection(
        async_db,
        user_id=default_user.id,
        session_id=reading_session.id,
        items=items,
        last_read=last_read,
    )
    assert report.differences == ()
    wrong = RollLastRead.model_validate({**last_read.model_dump(), "issue_number": "old-number"})
    changed = await compare_roll_projection(
        async_db,
        user_id=default_user.id,
        session_id=reading_session.id,
        items=items,
        last_read=wrong,
    )
    assert [row.field for row in changed.differences] == ["last_read"]
