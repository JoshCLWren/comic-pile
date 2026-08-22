"""Mutation coherence and scale evidence for the paginated Queue (#933).

Covers the closure-critical contract shared by epic #687 and #933:

- Real mutations (create, edit, reposition, delete, shuffle) keep the
  cursor-paginated Queue complete: a fresh walk yields every thread exactly
  once with no duplicates and no missing rows.
- Repositioning across the loaded/unloaded page boundary has defined behavior:
  the moved row leaves the previously loaded head pages and lands exactly once
  at its new position in a fresh walk.
- Initial requests, SQL work, and payload size stay bounded as the library
  grows across the required 50 / 250 / 1,000 / 5,000 thread sizes.

Each scale run prints one ``MEASUREMENT issue=933`` line so timing and byte
measurements can be captured from CI or local runs without fabricating them.
"""

from __future__ import annotations

import time
from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from inspect import unwrap
from types import SimpleNamespace, TracebackType

import pytest
from sqlalchemy import delete, event, insert, select
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession
from starlette.requests import Request

from app.api.thread import list_threads
from app.models import Thread
from app.schemas import QueueThreadListResponse
from comic_pile.queue import move_to_back, move_to_position, shuffle_queue
from tests.conftest import get_or_create_user_async

FIRST_PAGE_SIZE = 50
# Threads without issue tracking (no total_issues) only execute 1 SELECT for the thread list.
# Migrated threads would execute 3 SELECTs (threads + unread counts + next issue numbers).
EXPECTED_SELECTS_PER_PAGE = 1


def _make_request() -> Request:
    """Build a minimal Starlette request matching the ``list_threads`` signature."""
    return Request(
        {
            "type": "http",
            "method": "GET",
            "path": "/api/v1/threads/"
            "headers": [],
            "query_string": b"",
        }
    )


async def _seed_library(db: AsyncSession, user_id: int, count: int) -> None:
    """Insert ``count`` active threads with deterministic titles and positions.

    Args:
        db: Async database session.
        user_id: Owning user for every seeded thread.
        count: Number of threads to insert.
    """
    now = datetime.now(UTC)
    await db.execute(
        insert(Thread),
        [
            {
                "user_id": user_id,
                "title": f"Scale Thread {i:05d}",
                "format": "Comic",
                "issues_remaining": 3,
                "queue_position": i,
                "status": "active",
                "created_at": now - timedelta(minutes=count - i),
            }
            for i in range(1, count + 1)
        ],
    )
    await db.commit()


async def _fetch_page(
    db: AsyncSession,
    request: Request,
    user_id: int,
    *,
    page_size: int = FIRST_PAGE_SIZE,
    page_token: str | None = None,
    sort: str = "position",
) -> QueueThreadListResponse:
    """Call the unwrapped ``list_threads`` route exactly as the API would.

    Args:
        db: Async database session.
        request: Starlette request for the rate-limiting argument.
        user_id: Authenticated user id for the request.
        page_size: Requested page size.
        page_token: Opaque cursor continuation token.
        sort: Retained sort contract.

    Returns:
        The paginated Queue response for the requested page.
    """
    route = unwrap(list_threads)
    return await route(
        request=request,
        current_user=SimpleNamespace(id=user_id),
        db=db,
        search=None,
        sort=sort,
        page_size=page_size,
        page_token=page_token,
    )


async def _walk_all_pages(
    db: AsyncSession,
    request: Request,
    user_id: int,
    *,
    page_size: int = FIRST_PAGE_SIZE,
) -> tuple[list[int], int]:
    """Follow cursor pages to the end of the library.

    Args:
        db: Async database session.
        request: Starlette request for the rate-limiting argument.
        user_id: Authenticated user id for the request.
        page_size: Page size used for every walked page.

    Returns:
        Tuple of the visited thread ids in walk order and the number of pages.
    """
    seen: list[int] = []
    pages = 0
    token: str | None = None
    while True:
        page = await _fetch_page(db, request, user_id, page_size=page_size, page_token=token)
        seen.extend(thread.id for thread in page.threads)
        pages += 1
        if page.next_page_token is None:
            return seen, pages
        token = page.next_page_token
        assert pages <= 10_000, "cursor walk did not terminate"


class _SelectCounter:
    """Count SELECT statements executed against an engine within a context."""

    def __init__(self, engine: AsyncEngine) -> None:
        """Bind the counter to an engine.

        Args:
            engine: Async engine whose sync facade emits cursor events.
        """
        self._engine = engine
        self._listener: (
            Callable[[object, object, str, object, object, bool], None] | None
        ) = None
        self.count = 0

    def __enter__(self) -> _SelectCounter:
        """Start counting SELECT statements."""
        self.count = 0

        def _capture(
            conn: object,
            cursor: object,
            statement: str,
            parameters: object,
            context: object,
            executemany: bool,
        ) -> None:
            if statement.lstrip().upper().startswith("SELECT"):
                self.count += 1

        self._listener = _capture
        event.listen(self._engine.sync_engine, "before_cursor_execute", _capture)
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc_value: BaseException | None,
        traceback: TracebackType | None,
    ) -> None:
        """Stop counting SELECT statements."""
        if self._listener is not None:
            event.remove(self._engine.sync_engine, "before_cursor_execute", self._listener)
            self._listener = None


@pytest.mark.asyncio
@pytest.mark.parametrize("library_size", [50, 250, 1000, 5000])
async def test_initial_requests_and_payload_remain_bounded_as_library_grows(
    library_size: int,
    async_db: AsyncSession,
    db_engine: AsyncEngine,
) -> None:
    """First-page SQL work and payload stay flat as the library grows 50 → 5,000."""
    user = await get_or_create_user_async(async_db)
    await _seed_library(async_db, user.id, library_size)

    started = time.perf_counter()
    with _SelectCounter(db_engine) as first_counter:
        first = await _fetch_page(async_db, _make_request(), user.id)
    first_page_ms = (time.perf_counter() - started) * 1000
    first_bytes = len(first.model_dump_json().encode())

    assert len(first.threads) == FIRST_PAGE_SIZE
    # For library_size == FIRST_PAGE_SIZE, all items fit in one page so next_page_token is None
    if library_size > FIRST_PAGE_SIZE:
        assert first.next_page_token is not None, (
            f"library={library_size} must yield a continuation token"
        )
    assert first_counter.count == EXPECTED_SELECTS_PER_PAGE, (
        f"first page issued {first_counter.count} SELECTs at library={library_size}"
    )
    assert first_bytes <= 75_000, f"first page payload was {first_bytes} bytes"

    if library_size > FIRST_PAGE_SIZE:
        started = time.perf_counter()
        with _SelectCounter(db_engine) as second_counter:
            second = await _fetch_page(
                async_db, _make_request(), user.id, page_token=first.next_page_token
            )
        next_page_ms = (time.perf_counter() - started) * 1000

        expected_second_rows = min(FIRST_PAGE_SIZE, library_size - FIRST_PAGE_SIZE)
        assert len(second.threads) == expected_second_rows
        assert second_counter.count == EXPECTED_SELECTS_PER_PAGE
    else:
        assert first.next_page_token is None
        next_page_ms = 0.0

    print(
        f"MEASUREMENT issue=933 kind=pagination library={library_size} "
        f"page_size={FIRST_PAGE_SIZE} first_page_ms={first_page_ms:.1f} "
        f"next_page_ms={next_page_ms:.1f} "
        f"first_page_selects={first_counter.count} first_page_bytes={first_bytes}"
    )


@pytest.mark.asyncio
async def test_reposition_across_loaded_boundary_keeps_full_walk_complete(
    async_db: AsyncSession,
) -> None:
    """Repositioning out of the loaded window keeps a fresh walk complete."""
    library_size = 120
    user = await get_or_create_user_async(async_db)
    await _seed_library(async_db, user.id, library_size)

    page_one = await _fetch_page(async_db, _make_request(), user.id)
    assert page_one.next_page_token is not None
    page_two = await _fetch_page(
        async_db, _make_request(), user.id, page_token=page_one.next_page_token
    )
    loaded_ids = [thread.id for thread in page_one.threads]
    loaded_ids += [thread.id for thread in page_two.threads]
    assert len(loaded_ids) == 100

    moved_thread_id = loaded_ids[4]
    changes = await move_to_position(moved_thread_id, user.id, 118, async_db)
    assert moved_thread_id in changes

    page_after = await _fetch_page(async_db, _make_request(), user.id)
    after_ids = {thread.id for thread in page_after.threads}
    assert moved_thread_id not in after_ids

    seen, pages = await _walk_all_pages(async_db, _make_request(), user.id)

    assert pages == 3
    assert len(seen) == library_size
    assert len(set(seen)) == library_size
    assert seen.index(moved_thread_id) == 117


@pytest.mark.asyncio
async def test_delete_then_mutation_followed_paging_has_no_duplicates_or_missing_rows(
    async_db: AsyncSession,
) -> None:
    """Deleting rows near an unloaded boundary keeps mutation-followed paging coherent."""
    library_size = 120
    user = await get_or_create_user_async(async_db)
    await _seed_library(async_db, user.id, library_size)

    first = await _fetch_page(async_db, _make_request(), user.id)
    assert len(first.threads) == FIRST_PAGE_SIZE

    result = await async_db.execute(
        select(Thread.id)
        .where(Thread.user_id == user.id)
        .where(Thread.status == "active")
        .where(Thread.queue_position >= 1)
        .order_by(Thread.queue_position, Thread.id)
        .offset(58)
        .limit(3)
    )
    doomed_ids = [row[0] for row in result.fetchall()]
    assert len(doomed_ids) == 3

    await async_db.execute(delete(Thread).where(Thread.id.in_(doomed_ids)))
    await async_db.commit()

    seen, pages = await _walk_all_pages(async_db, _make_request(), user.id)

    expected_rows = library_size - len(doomed_ids)
    assert pages == 3
    assert len(seen) == expected_rows
    assert len(set(seen)) == expected_rows
    assert not set(doomed_ids) & set(seen)


@pytest.mark.asyncio
async def test_create_edit_shuffle_then_full_walk_is_coherent(
    async_db: AsyncSession,
) -> None:
    """Create/edit/shuffle mutations compose into one complete duplicate-free walk."""
    library_size = 100
    user = await get_or_create_user_async(async_db)
    await _seed_library(async_db, user.id, library_size)

    created = Thread(
        user_id=user.id,
        title="Brand New Thread",
        format="Comic",
        issues_remaining=5,
        queue_position=1,
        status="active",
        created_at=datetime.now(UTC),
    )
    async_db.add(created)
    await async_db.commit()
    created_id = created.id

    shuffled = await shuffle_queue(user.id, async_db)
    assert shuffled == library_size + 1

    result = await async_db.execute(select(Thread).where(Thread.id == created_id))
    stored = result.scalar_one()
    stored.notes = "edited after shuffle"
    await async_db.commit()

    await move_to_back(created_id, user.id, async_db)

    seen, _pages = await _walk_all_pages(async_db, _make_request(), user.id)

    assert len(seen) == library_size + 1
    assert len(set(seen)) == library_size + 1
    assert created_id in seen
