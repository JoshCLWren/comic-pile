"""Tests for the Roll correction-sheet personalized examples (issue #2744).

The correction sheet explains each steering choice in plain language and
illustrates it with one short example drawn from the signed-in reader's own
rated/read history. These tests pin the parts that are easy to get quietly
wrong:

- the endpoint is versioned-only (``/api/v1/...``), never a new bare ``/api/*``
  client route (the docs/API.md convention guarded by ``test_route_versioning``);
- the reader's own history is the only source of examples;
- effort/commitment examples are grounded in the canonical reading-effort bands
  instead of a second definition invented for the UI, and an option with no
  honest example degrades to ``None`` rather than inventing one;
- ``Surprise me`` never shows a preference-derived example;
- the whole sheet is served by a bounded number of queries, not one per option.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Final

import pytest
from httpx import AsyncClient
from sqlalchemy import event as sa_event
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession

from app.models import Event, ExternalIdentity, Thread, ThreadExternalSeriesMapping
from app.models import Session as SessionModel
from app.models.user import User
from app.repositories.rate_repository import fetch_user_recent_rated_threads
from app.services.correction_examples import generate_correction_examples
from app.services.reading_effort import DEEP_MIN_MINUTES

CORRECTION_EXAMPLES_PATH: Final[str] = "/api/v1/sessions/correction-examples"

#: Elapsed roll-to-rate seconds that land inside the canonical "light" and
#: "deep" bands respectively.
LIGHT_READ_SECONDS: Final[int] = 300
DEEP_READ_SECONDS: Final[int] = int(DEEP_MIN_MINUTES * 60) + 120
#: Two linked reads are the documented minimum before the canonical model trusts
#: an observed estimate (``MIN_OBSERVED_SAMPLES``).
OBSERVATIONS_PER_THREAD: Final[int] = 2
#: Minutes between successive reads of the same thread.
READ_SPACING_MINUTES: Final[int] = 30


async def _seed_thread(async_db: AsyncSession, user: User, title: str) -> Thread:
    """Create one owned thread.

    Args:
        async_db: Database session.
        user: Thread owner.
        title: Thread title.

    Returns:
        The created thread.
    """
    thread = Thread(
        title=title,
        format="Comic",
        issues_remaining=1,
        queue_position=1,
        status="active",
        user_id=user.id,
    )
    async_db.add(thread)
    await async_db.flush()
    return thread


async def _new_session(async_db: AsyncSession, user: User) -> SessionModel:
    """Create a session to attach reading events to.

    Args:
        async_db: Database session.
        user: Session owner.

    Returns:
        The created session.
    """
    session = SessionModel(start_die=6, user_id=user.id)
    async_db.add(session)
    await async_db.flush()
    return session


async def _seed_rated_reads(
    async_db: AsyncSession,
    user: User,
    thread: Thread,
    *,
    rating: float,
    read_seconds: int,
    minutes_ago: int,
    occurrences: int = OBSERVATIONS_PER_THREAD,
    session: SessionModel | None = None,
) -> None:
    """Record explicit roll -> rate reads so the canonical effort model sees them.

    Each rate event is linked to its own roll event, which is the only signal
    ``collect_classified_observations`` accepts. The newest read is
    ``minutes_ago`` in the past and older reads step further back, so recency
    ordering in the service is deterministic.

    Args:
        async_db: Database session.
        user: Thread owner.
        thread: Thread that was read.
        rating: Rating recorded for each read.
        read_seconds: Roll-to-rate latency driving the canonical effort band.
        minutes_ago: Minutes to backdate the newest read.
        occurrences: Number of linked reads to record.
        session: Session to attach events to; created when omitted.
    """
    if session is None:
        session = await _new_session(async_db, user)

    newest_rate_at = datetime.now(UTC) - timedelta(minutes=minutes_ago)
    for index in range(occurrences):
        rate_at = newest_rate_at - timedelta(minutes=index * READ_SPACING_MINUTES)
        roll_event = Event(
            type="roll",
            die=6,
            result=1,
            selected_thread_id=thread.id,
            selection_method="random",
            session_id=session.id,
            thread_id=thread.id,
            timestamp=rate_at - timedelta(seconds=read_seconds),
        )
        async_db.add(roll_event)
        await async_db.flush()
        async_db.add(
            Event(
                type="rate",
                die=6,
                result=1,
                selection_method="random",
                session_id=session.id,
                thread_id=thread.id,
                rating=rating,
                source_roll_event_id=roll_event.id,
                timestamp=rate_at,
            )
        )
    await async_db.flush()


async def _seed_unlinked_ratings(
    async_db: AsyncSession,
    user: User,
    thread: Thread,
    *,
    rating: float,
    occurrences: int = OBSERVATIONS_PER_THREAD,
) -> None:
    """Record rating events that are not linked to any roll event.

    Unlinked ratings give the reader a real rating history while leaving the
    canonical reading-effort model with no observations to work from.

    Args:
        async_db: Database session.
        user: Thread owner.
        thread: Thread that was rated.
        rating: Rating to record.
        occurrences: Number of rating events to record.
    """
    session = await _new_session(async_db, user)
    newest_at = datetime.now(UTC)
    for index in range(occurrences):
        async_db.add(
            Event(
                type="rate",
                die=6,
                result=1,
                selection_method="random",
                session_id=session.id,
                thread_id=thread.id,
                rating=rating,
                timestamp=newest_at - timedelta(minutes=index * READ_SPACING_MINUTES),
            )
        )
    await async_db.flush()


async def _seed_confirmed_series_year(
    async_db: AsyncSession,
    thread: Thread,
    year: int,
) -> None:
    """Attach a confirmed series identity carrying a publication year.

    Args:
        async_db: Database session.
        thread: Thread whose series identity is being confirmed.
        year: Publication year stored in the provider metadata.
    """
    identity = ExternalIdentity(
        provider="comicvine",
        entity_type="series",
        external_id=f"series-{thread.id}",
        metadata_json={"name": thread.title, "cover_date": f"{year}-01-01"},
    )
    async_db.add(identity)
    await async_db.flush()
    async_db.add(
        ThreadExternalSeriesMapping(
            thread_id=thread.id,
            external_identity_id=identity.id,
            status="confirmed",
        )
    )
    await async_db.flush()


@pytest.mark.asyncio
async def test_endpoint_is_versioned_only(auth_client: AsyncClient) -> None:
    """The examples endpoint must not exist as a new bare /api/* client route.

    Adding a bare twin fails ``tests/test_route_versioning.py``, which enforces
    the docs/API.md convention that new client resources live under /api/v1/*.

    Args:
        auth_client: Authenticated HTTP client for API requests.
    """
    response = await auth_client.get(CORRECTION_EXAMPLES_PATH)
    assert response.status_code == 200

    # The bare path either 404s or falls through to a different route (here the
    # session-detail path, which rejects the non-integer ID with 422). Either
    # way it must not serve the examples payload.
    legacy = await auth_client.get("/api/sessions/correction-examples")
    assert legacy.status_code in (404, 422)
    assert "even_easier" not in legacy.text


@pytest.mark.asyncio
async def test_endpoint_requires_authentication(client: AsyncClient) -> None:
    """Unauthenticated callers must not receive personalized examples.

    Args:
        client: Unauthenticated HTTP client.
    """
    response = await client.get(CORRECTION_EXAMPLES_PATH)
    assert response.status_code == 401


@pytest.mark.asyncio
async def test_response_lists_every_choice_with_no_history(
    auth_client: AsyncClient,
) -> None:
    """Every choice is present in the payload even with no usable history.

    Args:
        auth_client: Authenticated HTTP client for API requests.
    """
    response = await auth_client.get(CORRECTION_EXAMPLES_PATH)

    assert response.status_code == 200
    assert response.json() == {
        "even_easier": None,
        "keep_level_different": None,
        "something_familiar": None,
        "something_different": None,
        "pure_random": None,
    }


@pytest.mark.asyncio
async def test_unrated_queue_degrades_without_inventing_examples(
    async_db: AsyncSession,
    default_user: User,
) -> None:
    """A reader with threads but no ratings gets plain copy, not fabricated examples.

    Args:
        async_db: Async database session.
        default_user: Reader whose history is inspected.
    """
    await _seed_thread(async_db, default_user, "Unread Batman")
    await async_db.commit()

    response = await generate_correction_examples(async_db, default_user.id)

    assert response.something_familiar is None
    assert response.even_easier is None
    assert response.keep_level_different is None
    assert response.something_different is None


@pytest.mark.asyncio
async def test_examples_never_leak_another_readers_history(
    async_db: AsyncSession,
    default_user: User,
) -> None:
    """Examples come only from the requesting reader's own rated comics.

    Args:
        async_db: Async database session.
        default_user: Reader whose history is inspected.
    """
    from tests.conftest import get_or_create_user_async

    other_user = await get_or_create_user_async(async_db, username="other-reader-2744")
    other_thread = await _seed_thread(async_db, other_user, "Other Reader Saga")
    await _seed_rated_reads(
        async_db,
        other_user,
        other_thread,
        rating=5.0,
        read_seconds=LIGHT_READ_SECONDS,
        minutes_ago=0,
    )
    await async_db.commit()

    response = await generate_correction_examples(async_db, default_user.id)

    assert "Other Reader Saga" not in response.model_dump_json()


@pytest.mark.asyncio
async def test_familiar_example_uses_best_rated_comic(
    async_db: AsyncSession,
    default_user: User,
) -> None:
    """The "stay close to what I've liked" example is the highest-rated read.

    Args:
        async_db: Async database session.
        default_user: Reader whose history is inspected.
    """
    modest = await _seed_thread(async_db, default_user, "Modest Run")
    favorite = await _seed_thread(async_db, default_user, "Planetary")
    await _seed_rated_reads(
        async_db,
        default_user,
        modest,
        rating=3.6,
        read_seconds=LIGHT_READ_SECONDS,
        minutes_ago=60,
    )
    await _seed_rated_reads(
        async_db,
        default_user,
        favorite,
        rating=5.0,
        read_seconds=LIGHT_READ_SECONDS,
        minutes_ago=0,
    )
    await async_db.commit()

    response = await generate_correction_examples(async_db, default_user.id)

    assert response.something_familiar == "Based on your ratings, think more Planetary territory."


@pytest.mark.asyncio
async def test_lighter_example_requires_the_canonical_light_band(
    async_db: AsyncSession,
    default_user: User,
) -> None:
    """A canonically deep read is never presented as the "lighter" example.

    Regression guard for a title-keyword heuristic that treated any comic
    containing "annual", "special", "one-shot", or "#1" as a lighter commitment
    and otherwise fell back to an arbitrary favourite. The sheet must ground
    effort wording in the canonical reading-effort bands or show no example.

    Args:
        async_db: Async database session.
        default_user: Reader whose history is inspected.
    """
    deep_annual = await _seed_thread(async_db, default_user, "Sandman Annual #1")
    await _seed_rated_reads(
        async_db,
        default_user,
        deep_annual,
        rating=5.0,
        read_seconds=DEEP_READ_SECONDS,
        minutes_ago=0,
    )
    await async_db.commit()

    response = await generate_correction_examples(async_db, default_user.id)

    assert response.even_easier is None


@pytest.mark.asyncio
async def test_lighter_example_uses_canonical_light_band(
    async_db: AsyncSession,
    default_user: User,
) -> None:
    """A canonically light liked read illustrates the lighter option.

    Args:
        async_db: Async database session.
        default_user: Reader whose history is inspected.
    """
    light = await _seed_thread(async_db, default_user, "Jimmy Olsen Special")
    deep = await _seed_thread(async_db, default_user, "Sandman")
    await _seed_rated_reads(
        async_db,
        default_user,
        light,
        rating=4.5,
        read_seconds=LIGHT_READ_SECONDS,
        minutes_ago=0,
    )
    await _seed_rated_reads(
        async_db,
        default_user,
        deep,
        rating=4.0,
        read_seconds=DEEP_READ_SECONDS,
        minutes_ago=180,
    )
    await async_db.commit()

    response = await generate_correction_examples(async_db, default_user.id)

    assert response.even_easier == "Think more like Jimmy Olsen Special."


@pytest.mark.asyncio
async def test_same_effort_example_matches_current_level(
    async_db: AsyncSession,
    default_user: User,
) -> None:
    """The "keep about the same effort" example sits at the reader's current band.

    Args:
        async_db: Async database session.
        default_user: Reader whose history is inspected.
    """
    recent_light = await _seed_thread(async_db, default_user, "Recent Light Read")
    older_light = await _seed_thread(async_db, default_user, "Older Light Read")
    deep = await _seed_thread(async_db, default_user, "Deep Dive")
    await _seed_rated_reads(
        async_db,
        default_user,
        recent_light,
        rating=4.0,
        read_seconds=LIGHT_READ_SECONDS,
        minutes_ago=0,
    )
    await _seed_rated_reads(
        async_db,
        default_user,
        older_light,
        rating=3.8,
        read_seconds=LIGHT_READ_SECONDS,
        minutes_ago=180,
    )
    await _seed_rated_reads(
        async_db,
        default_user,
        deep,
        rating=4.2,
        read_seconds=DEEP_READ_SECONDS,
        minutes_ago=360,
    )
    await async_db.commit()

    response = await generate_correction_examples(async_db, default_user.id)

    assert response.keep_level_different == "Think more like Recent Light Read."


@pytest.mark.asyncio
async def test_same_effort_example_omitted_when_effort_is_unknown(
    async_db: AsyncSession,
    default_user: User,
) -> None:
    """Unlinked ratings carry no effort signal, so no effort example is shown.

    Args:
        async_db: Async database session.
        default_user: Reader whose history is inspected.
    """
    unlinked = await _seed_thread(async_db, default_user, "Unlinked Reads")
    await _seed_unlinked_ratings(async_db, default_user, unlinked, rating=4.0)
    await async_db.commit()

    response = await generate_correction_examples(async_db, default_user.id)

    assert response.keep_level_different is None
    assert response.even_easier is None
    # A well-rated read is still enough to illustrate the familiar option.
    assert response.something_familiar is not None


@pytest.mark.asyncio
async def test_examples_illustrate_a_reader_with_mixed_effort_history(
    async_db: AsyncSession,
    default_user: User,
) -> None:
    """Each option picks a distinct, honestly-grounded example from real history.

    The reader's five most recent reads are all canonically light; the best-rated
    read is an older canonically deep one. That contrast drives the change-of-pace
    example while the light cluster drives the lighter and same-effort examples.

    Args:
        async_db: Async database session.
        default_user: Reader whose history is inspected.
    """
    light_titles = ["Jimmy Olsen", "Peanuts", "Archie", "Garfield", "Calvin"]
    for index, title in enumerate(light_titles):
        thread = await _seed_thread(async_db, default_user, title)
        await _seed_rated_reads(
            async_db,
            default_user,
            thread,
            rating=4.0 - index / 100.0,
            read_seconds=LIGHT_READ_SECONDS,
            minutes_ago=index * 20,
        )
    deep_favorite = await _seed_thread(async_db, default_user, "Planetary")
    await _seed_rated_reads(
        async_db,
        default_user,
        deep_favorite,
        rating=4.5,
        read_seconds=DEEP_READ_SECONDS,
        minutes_ago=600,
    )
    await async_db.commit()

    response = await generate_correction_examples(async_db, default_user.id)

    assert response.even_easier == "Think more like Jimmy Olsen."
    assert response.keep_level_different == "Think more like Jimmy Olsen."
    assert response.something_familiar == "Based on your ratings, think more Planetary territory."
    assert response.something_different == (
        "Based on your ratings, think more Planetary territory."
    )
    assert response.pure_random is None


@pytest.mark.asyncio
async def test_change_of_pace_example_omitted_without_contrast(
    async_db: AsyncSession,
    default_user: User,
) -> None:
    """No honest contrast means no change-of-pace example, not a repeated title.

    Args:
        async_db: Async database session.
        default_user: Reader whose history is inspected.
    """
    first = await _seed_thread(async_db, default_user, "Light One")
    second = await _seed_thread(async_db, default_user, "Light Two")
    await _seed_rated_reads(
        async_db,
        default_user,
        first,
        rating=4.0,
        read_seconds=LIGHT_READ_SECONDS,
        minutes_ago=0,
    )
    await _seed_rated_reads(
        async_db,
        default_user,
        second,
        rating=3.8,
        read_seconds=LIGHT_READ_SECONDS,
        minutes_ago=60,
    )
    await async_db.commit()

    response = await generate_correction_examples(async_db, default_user.id)

    # Both liked reads are also recent reads, so neither can illustrate a change.
    assert response.something_different is None


@pytest.mark.asyncio
async def test_recent_ratings_are_deduplicated_per_thread(
    async_db: AsyncSession,
    default_user: User,
) -> None:
    """A comic rated many times contributes one recent read, not the whole window.

    Without per-thread deduplication the reader's current effort level would be
    derived from a single comic rated over and over.

    Args:
        async_db: Async database session.
        default_user: Reader whose history is inspected.
    """
    reread = await _seed_thread(async_db, default_user, "Reread Deep")
    light_a = await _seed_thread(async_db, default_user, "Light A")
    light_b = await _seed_thread(async_db, default_user, "Light B")
    session = await _new_session(async_db, default_user)
    for _ in range(3):
        await _seed_rated_reads(
            async_db,
            default_user,
            reread,
            rating=4.5,
            read_seconds=DEEP_READ_SECONDS,
            minutes_ago=0,
            session=session,
        )
    await _seed_rated_reads(
        async_db,
        default_user,
        light_a,
        rating=4.0,
        read_seconds=LIGHT_READ_SECONDS,
        minutes_ago=300,
        session=session,
    )
    await _seed_rated_reads(
        async_db,
        default_user,
        light_b,
        rating=3.9,
        read_seconds=LIGHT_READ_SECONDS,
        minutes_ago=600,
        session=session,
    )
    await async_db.commit()

    recent = await fetch_user_recent_rated_threads(async_db, default_user.id, limit=5)
    recent_ids = [thread_id for thread_id, _title, _rating in recent]
    assert len(recent_ids) == len(set(recent_ids))
    assert set(recent_ids) == {reread.id, light_a.id, light_b.id}

    response = await generate_correction_examples(async_db, default_user.id)

    # The modal recent band comes from the two light reads, not six deep ones.
    assert response.keep_level_different == "Think more like Light A."


@pytest.mark.asyncio
async def test_publication_year_fallback_can_supply_the_effort_band(
    async_db: AsyncSession,
    default_user: User,
) -> None:
    """A confirmed classic-era series year is the canonical light-read fallback.

    Args:
        async_db: Async database session.
        default_user: Reader whose history is inspected.
    """
    classic = await _seed_thread(async_db, default_user, "Weirdo Corp")
    await _seed_unlinked_ratings(async_db, default_user, classic, rating=4.0)
    await _seed_confirmed_series_year(async_db, classic, 1965)
    await async_db.commit()

    response = await generate_correction_examples(async_db, default_user.id)

    # The classic-era prior is 10 minutes, which bands as light.
    assert response.even_easier == "Think more like Weirdo Corp."


@pytest.mark.asyncio
async def test_query_count_does_not_grow_with_history(
    async_db: AsyncSession,
    default_user: User,
    db_engine: AsyncEngine,
) -> None:
    """One bounded request serves the whole sheet regardless of history size.

    Estimating effort one thread at a time re-scans the reader's entire
    roll-to-rate history plus one metadata lookup per candidate. The sheet must
    stay flat: two rating reads, one shared observation read, and one batched
    series-metadata read.

    Args:
        async_db: Async database session.
        default_user: Reader whose history is inspected.
        db_engine: Engine used to count statements.
    """
    for index in range(12):
        thread = await _seed_thread(async_db, default_user, f"Series {index}")
        await _seed_rated_reads(
            async_db,
            default_user,
            thread,
            rating=3.5 + index / 100.0,
            read_seconds=DEEP_READ_SECONDS if index % 2 else LIGHT_READ_SECONDS,
            minutes_ago=index * 10,
        )
        await _seed_confirmed_series_year(async_db, thread, 1990 + index)
    await async_db.commit()

    statements: list[str] = []

    def record_statement(
        conn: object,
        cursor: object,
        statement: str,
        parameters: object,
        context: object,
        executemany: bool,
    ) -> None:
        statements.append(statement)

    sa_event.listen(db_engine.sync_engine, "before_cursor_execute", record_statement)
    try:
        await generate_correction_examples(async_db, default_user.id)
    finally:
        sa_event.remove(db_engine.sync_engine, "before_cursor_execute", record_statement)

    selects = [s for s in statements if s.lstrip().upper().startswith("SELECT")]
    assert len(selects) <= 5, f"Expected a bounded query count, got: {selects}"
