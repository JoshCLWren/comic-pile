"""Rate pipeline query construction and persistence.

All SQLAlchemy access for the rate/undo pipeline lives here. Functions
return ORM models, plain rows/tuples, or IDs; callers (services) own
transaction boundaries.
"""

from collections.abc import Sequence

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import Event, ExternalIdentity, Thread, ThreadExternalSeriesMapping


async def fetch_source_roll_event(
    db: AsyncSession,
    session_id: int,
    thread_id: int,
) -> int | None:
    """Return the ID of the most recent roll event selecting a thread.

    Args:
        db: Database session.
        session_id: Session to search within.
        thread_id: Thread whose originating roll event is sought.

    Returns:
        The ID of the most recent roll event selecting this thread,
        or None when no such event exists.
    """
    result = await db.execute(
        select(Event.id)
        .where(Event.session_id == session_id)
        .where(Event.type == "roll")
        .where(Event.selected_thread_id == thread_id)
        .order_by(Event.timestamp.desc(), Event.id.desc())
        .limit(1)
    )
    return result.scalar_one_or_none()


async def fetch_user_rated_threads(
    db: AsyncSession,
    user_id: int,
    min_rating: float = 3.5,
    limit: int = 50,
) -> list[tuple[int, str, float]]:
    """Fetch threads the user still rates at or above a threshold.

    Returns one row per thread: the thread ID, its title, and that thread's most
    recent rating, keeping only threads whose most recent rating is at or above
    ``min_rating`` and ordering by rating descending then most recently rated
    first. A thread rated several times contributes a single row so callers
    never double-count one comic, and a thread the reader later rated lower than
    ``min_rating`` drops out because its current opinion is what the sheet
    describes.

    Args:
        db: Database session.
        user_id: The user whose ratings to fetch.
        min_rating: Minimum rating threshold (default 3.5 for "liked" comics).
        limit: Maximum number of distinct threads to return.

    Returns:
        List of (thread_id, title, rating) tuples.
    """
    return await _fetch_user_rated_threads(
        db,
        user_id,
        min_rating=min_rating,
        limit=limit,
        newest_first=False,
    )


async def fetch_user_recent_rated_threads(
    db: AsyncSession,
    user_id: int,
    limit: int = 20,
) -> list[tuple[int, str, float]]:
    """Fetch the user's most recently rated threads, newest first.

    Returns one row per distinct thread using that thread's most recent rating,
    so a comic rated repeatedly cannot fill the whole "recent reads" window.

    Args:
        db: Database session.
        user_id: The user whose ratings to fetch.
        limit: Maximum number of distinct threads to return.

    Returns:
        List of (thread_id, title, rating) tuples.
    """
    return await _fetch_user_rated_threads(
        db,
        user_id,
        min_rating=None,
        limit=limit,
        newest_first=True,
    )


async def _fetch_user_rated_threads(
    db: AsyncSession,
    user_id: int,
    *,
    min_rating: float | None,
    limit: int,
    newest_first: bool,
) -> list[tuple[int, str, float]]:
    """Run the shared one-row-per-thread user rating query.

    Args:
        db: Database session.
        user_id: The user whose ratings to fetch.
        min_rating: Minimum rating threshold, or None to accept any rating.
        limit: Maximum number of distinct threads to return.
        newest_first: Order by most recently rated first instead of by rating.

    Returns:
        List of (thread_id, title, rating) tuples, one per distinct thread.
    """
    ranked = (
        select(
            Event.thread_id.label("thread_id"),
            Thread.title.label("title"),
            Event.rating.label("rating"),
            Event.timestamp.label("last_rated_at"),
            func.row_number()
            .over(
                partition_by=Event.thread_id,
                order_by=(Event.timestamp.desc(), Event.id.desc()),
            )
            .label("thread_rank"),
        )
        .join(Thread, Thread.id == Event.thread_id)
        .where(Event.type == "rate")
        .where(Thread.user_id == user_id)
        .where(Event.thread_id.is_not(None))
        .where(Event.rating.is_not(None))
        .subquery()
    )

    rating_floor = ranked.c.rating >= min_rating if min_rating is not None else None
    if newest_first:
        order_by = (
            ranked.c.last_rated_at.desc(),
            ranked.c.rating.desc(),
            ranked.c.thread_id,
        )
    else:
        order_by = (
            ranked.c.rating.desc(),
            ranked.c.last_rated_at.desc(),
            ranked.c.thread_id,
        )

    stmt = select(ranked.c.thread_id, ranked.c.title, ranked.c.rating).where(
        ranked.c.thread_rank == 1
    )
    if rating_floor is not None:
        stmt = stmt.where(rating_floor)
    result = await db.execute(stmt.order_by(*order_by).limit(limit))
    return [(row.thread_id, row.title, row.rating) for row in result.all()]


async def fetch_confirmed_series_identity_metadata(
    db: AsyncSession,
    thread_ids: Sequence[int],
) -> dict[int, list[dict[str, object]]]:
    """Return confirmed series identity metadata for each requested thread.

    Batched equivalent of reading one thread's confirmed series identities at a
    time, so callers that need many threads pay one query instead of one per
    thread. Interpretations of the metadata (for example extracting a
    publication year) belong to the calling service.

    Args:
        db: Database session.
        thread_ids: Threads whose confirmed series metadata is requested.

    Returns:
        Mapping of thread ID to that thread's confirmed series metadata
        documents in mapping-id order. Threads with no confirmed series
        identity are absent rather than mapped to an empty guess.
    """
    unique_ids = list(dict.fromkeys(thread_ids))
    if not unique_ids:
        return {}

    result = await db.execute(
        select(
            ThreadExternalSeriesMapping.thread_id,
            ExternalIdentity.metadata_json,
        )
        .join(
            ExternalIdentity,
            ExternalIdentity.id == ThreadExternalSeriesMapping.external_identity_id,
        )
        .where(ThreadExternalSeriesMapping.thread_id.in_(unique_ids))
        .where(ThreadExternalSeriesMapping.status == "confirmed")
        .order_by(
            ThreadExternalSeriesMapping.thread_id,
            ThreadExternalSeriesMapping.id,
        )
    )

    metadata_by_thread: dict[int, list[dict[str, object]]] = {}
    for thread_id, metadata_json in result.all():
        documents = metadata_by_thread.setdefault(thread_id, [])
        if isinstance(metadata_json, dict):
            documents.append(metadata_json)
    return metadata_by_thread
