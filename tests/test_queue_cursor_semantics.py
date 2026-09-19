"""Deterministic Queue cursor search and sort semantics tests.

Covers the acceptance criteria for issue #931:
- Every retained sort has a deterministic cursor contract with stable tie-breakers.
- Search results remain correct across multiple pages.
- Changing search or sort cannot reuse an incompatible cursor.
- Duplicate queue positions do not produce gaps or duplicate rows.
- API tests cover empty, multi-page, stale-cursor, and ownership cases.
"""

from datetime import UTC, datetime, timedelta
from inspect import unwrap
from types import SimpleNamespace
from typing import cast

import pytest
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession
from starlette.requests import Request

from app.api.thread import list_threads
from app.models import Thread
from app.models.user import User
from app.services.queue_pagination import (
    QueueCursor,
    QueueSort,
    build_cursor_filter,
    build_cursor_values_from_row,
    build_sort_order,
    decode_queue_cursor,
    encode_queue_cursor,
    normalize_queue_search,
)
from tests.conftest import get_or_create_user_async


# ---------------------------------------------------------------------------
# Unit tests for queue_pagination helpers
# ---------------------------------------------------------------------------


class TestNormalizeQueueSearch:
    """Verify search normalization for cursor binding."""

    def test_none_returns_empty(self) -> None:
        assert normalize_queue_search(None) == ""

    def test_strips_and_casefolds(self) -> None:
        assert normalize_queue_search("  X-Men  ") == "x-men"

    def test_empty_string(self) -> None:
        assert normalize_queue_search("") == ""


class TestCursorRoundTrip:
    """Verify encode/decode round-trips for every sort mode."""

    @pytest.mark.parametrize(
        ("sort", "values"),
        [
            ("position", ("0", "42", "7")),
            ("title", ("42", "7")),
            ("created", ("42", "7")),
        ],
    )
    def test_round_trip_preserves_values(self, sort: str, values: tuple[str, ...]) -> None:
        cursor = QueueCursor(sort=cast(QueueSort, sort), search="batman", values=values)
        token = encode_queue_cursor(cursor)
        decoded = decode_queue_cursor(token, sort=cast(QueueSort, sort), search="batman")
        assert decoded == QueueCursor(
            sort=cast(QueueSort, sort), search="batman", values=values
        )

    def test_position_cursor_values(self) -> None:
        cursor = QueueCursor(sort="position", search="", values=("0", "5", "12"))
        token = encode_queue_cursor(cursor)
        decoded = decode_queue_cursor(token, sort="position", search=None)
        assert decoded.values == ("0", "5", "12")

    def test_position_cursor_values_for_blocked_row(self) -> None:
        cursor = QueueCursor(sort="position", search="", values=("1", "5", "12"))
        token = encode_queue_cursor(cursor)
        decoded = decode_queue_cursor(token, sort="position", search=None)
        assert decoded.values == ("1", "5", "12")

    def test_title_cursor_values(self) -> None:
        cursor = QueueCursor(sort="title", search="", values=("Batman", "3"))
        token = encode_queue_cursor(cursor)
        decoded = decode_queue_cursor(token, sort="title", search=None)
        assert decoded.values == ("Batman", "3")

    def test_created_cursor_values(self) -> None:
        now = datetime.now(UTC)
        cursor = QueueCursor(sort="created", search="", values=(now.isoformat(), "99"))
        token = encode_queue_cursor(cursor)
        decoded = decode_queue_cursor(token, sort="created", search=None)
        assert decoded.values[1] == "99"


class TestCursorRejection:
    """Verify stale and malformed cursors are rejected."""

    def test_rejects_sort_change(self) -> None:
        token = encode_queue_cursor(
            QueueCursor(sort="position", search="", values=("0", "1", "1"))
        )
        with pytest.raises(ValueError, match="does not match"):
            decode_queue_cursor(token, sort="title", search=None)

    def test_rejects_search_change(self) -> None:
        token = encode_queue_cursor(
            QueueCursor(sort="title", search="x-men", values=("x-men", "1"))
        )
        with pytest.raises(ValueError, match="does not match"):
            decode_queue_cursor(token, sort="title", search="x-force")

    def test_rejects_malformed_token(self) -> None:
        with pytest.raises(ValueError, match="Invalid Queue page token"):
            decode_queue_cursor("not-valid!!", sort="position", search=None)

    def test_rejects_invalid_sort_value(self) -> None:
        from tests.test_queue_pagination import _encode_payload

        token = _encode_payload(
            {"sort": "bogus", "search": "", "values": ["1", "1"]}
        )
        with pytest.raises(ValueError, match="token sort"):
            decode_queue_cursor(token, sort="bogus", search=None)


class TestBuildSortOrder:
    """Verify deterministic ORDER BY columns for each sort mode."""

    def test_position_sort(self) -> None:
        cols = build_sort_order("position")
        # blocked grouping key + queue position + deterministic id tie-breaker
        assert len(cols) == 3

    def test_title_sort(self) -> None:
        cols = build_sort_order("title")
        assert len(cols) == 2

    def test_created_sort(self) -> None:
        cols = build_sort_order("created")
        assert len(cols) == 2


class TestBuildCursorFilter:
    """Verify cursor WHERE clauses compile without errors."""

    def test_position_cursor_filter(self) -> None:
        cursor = QueueCursor(sort="position", search="", values=("0", "5", "10"))
        expr = build_cursor_filter(cursor)
        assert expr is not None

    def test_position_cursor_filter_for_blocked_row(self) -> None:
        cursor = QueueCursor(sort="position", search="", values=("1", "5", "10"))
        expr = build_cursor_filter(cursor)
        assert expr is not None

    def test_title_cursor_filter(self) -> None:
        cursor = QueueCursor(sort="title", search="", values=("Batman", "3"))
        expr = build_cursor_filter(cursor)
        assert expr is not None

    def test_created_cursor_filter(self) -> None:
        now = datetime.now(UTC)
        cursor = QueueCursor(sort="created", search="", values=(now.isoformat(), "7"))
        expr = build_cursor_filter(cursor)
        assert expr is not None


class TestBuildCursorValuesFromRow:
    """Verify cursor value extraction from Thread rows."""

    def test_position_values(self) -> None:
        thread = SimpleNamespace(
            queue_position=5,
            id=10,
            title="X",
            created_at=datetime.now(UTC),
            is_blocked=False,
        )
        values = build_cursor_values_from_row("position", cast(Thread, thread))
        assert values == ("0", "5", "10")

    def test_position_values_for_blocked_row(self) -> None:
        thread = SimpleNamespace(
            queue_position=5,
            id=10,
            title="X",
            created_at=datetime.now(UTC),
            is_blocked=True,
        )
        values = build_cursor_values_from_row("position", cast(Thread, thread))
        assert values == ("1", "5", "10")

    def test_title_values(self) -> None:
        thread = SimpleNamespace(queue_position=1, id=3, title="Batman", created_at=datetime.now(UTC))
        values = build_cursor_values_from_row("title", cast(Thread, thread))
        assert values == ("Batman", "3")

    def test_created_values(self) -> None:
        now = datetime.now(UTC)
        thread = SimpleNamespace(queue_position=1, id=5, title="X", created_at=now)
        values = build_cursor_values_from_row("created", cast(Thread, thread))
        assert values[0] == now.isoformat()
        assert values[1] == "5"


# ---------------------------------------------------------------------------
# Integration tests against the list_threads endpoint
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_list_threads_empty_result(
    async_db: AsyncSession,
    db_engine: AsyncEngine,
) -> None:
    """Empty queue returns empty list with no next_page_token."""
    user = await get_or_create_user_async(async_db)
    await async_db.commit()

    request = Request(
        {
            "type": "http",
            "method": "GET",
            "path": "/api/v1/threads/",
            "headers": [],
            "query_string": b"",
        }
    )
    route = unwrap(list_threads)
    response = await route(
        request=request,
        current_user=SimpleNamespace(id=user.id),
        db=async_db,
        search=None,
        sort="position",
        page_size=50,
        page_token=None,
    )
    assert response.threads == []
    assert response.next_page_token is None


@pytest.mark.asyncio
async def test_list_threads_position_sort(
    async_db: AsyncSession,
    db_engine: AsyncEngine,
) -> None:
    """Threads are returned in queue_position order with id tie-breaker."""
    user = await get_or_create_user_async(async_db)

    threads = []
    for pos in [3, 1, 2]:
        t = Thread(
            user_id=user.id,
            title=f"Thread-{pos}",
            format="Comic",
            issues_remaining=0,
            queue_position=pos,
            status="active",
            created_at=datetime.now(UTC),
        )
        async_db.add(t)
        threads.append(t)
    await async_db.flush()
    for t in threads:
        await async_db.refresh(t)
    await async_db.commit()

    request = Request(
        {
            "type": "http",
            "method": "GET",
            "path": "/api/v1/threads/",
            "headers": [],
            "query_string": b"",
        }
    )
    route = unwrap(list_threads)
    response = await route(
        request=request,
        current_user=SimpleNamespace(id=user.id),
        db=async_db,
        search=None,
        sort="position",
        page_size=50,
        page_token=None,
    )
    positions = [t.queue_position for t in response.threads]
    assert positions == [1, 2, 3]


@pytest.mark.asyncio
async def test_list_threads_title_sort(
    async_db: AsyncSession,
    db_engine: AsyncEngine,
) -> None:
    """Threads are returned in alphabetical title order."""
    user = await get_or_create_user_async(async_db)

    for title, pos in [("Charlie", 1), ("Alpha", 2), ("Bravo", 3)]:
        t = Thread(
            user_id=user.id,
            title=title,
            format="Comic",
            issues_remaining=0,
            queue_position=pos,
            status="active",
            created_at=datetime.now(UTC),
        )
        async_db.add(t)
    await async_db.flush()
    await async_db.commit()

    request = Request(
        {
            "type": "http",
            "method": "GET",
            "path": "/api/v1/threads/",
            "headers": [],
            "query_string": b"",
        }
    )
    route = unwrap(list_threads)
    response = await route(
        request=request,
        current_user=SimpleNamespace(id=user.id),
        db=async_db,
        search=None,
        sort="title",
        page_size=50,
        page_token=None,
    )
    titles = [t.title for t in response.threads]
    assert titles == ["Alpha", "Bravo", "Charlie"]


@pytest.mark.asyncio
async def test_list_threads_created_sort(
    async_db: AsyncSession,
    db_engine: AsyncEngine,
) -> None:
    """Threads are returned newest-first by creation date."""
    user = await get_or_create_user_async(async_db)

    now = datetime.now(UTC)
    oldest = Thread(
        user_id=user.id,
        title="Old",
        format="Comic",
        issues_remaining=0,
        queue_position=1,
        status="active",
        created_at=now - timedelta(days=3),
    )
    newest = Thread(
        user_id=user.id,
        title="New",
        format="Comic",
        issues_remaining=0,
        queue_position=2,
        status="active",
        created_at=now,
    )
    async_db.add_all([oldest, newest])
    await async_db.flush()
    await async_db.commit()

    request = Request(
        {
            "type": "http",
            "method": "GET",
            "path": "/api/v1/threads/",
            "headers": [],
            "query_string": b"",
        }
    )
    route = unwrap(list_threads)
    response = await route(
        request=request,
        current_user=SimpleNamespace(id=user.id),
        db=async_db,
        search=None,
        sort="created",
        page_size=50,
        page_token=None,
    )
    titles = [t.title for t in response.threads]
    assert titles == ["New", "Old"]


@pytest.mark.asyncio
async def test_list_threads_multi_page_position(
    async_db: AsyncSession,
    db_engine: AsyncEngine,
) -> None:
    """Multi-page pagination returns all threads without gaps or duplicates."""
    user = await get_or_create_user_async(async_db)

    for i in range(1, 6):
        t = Thread(
            user_id=user.id,
            title=f"Thread-{i:02d}",
            format="Comic",
            issues_remaining=0,
            queue_position=i,
            status="active",
            created_at=datetime.now(UTC),
        )
        async_db.add(t)
    await async_db.flush()
    await async_db.commit()

    request = Request(
        {
            "type": "http",
            "method": "GET",
            "path": "/api/v1/threads/",
            "headers": [],
            "query_string": b"",
        }
    )
    route = unwrap(list_threads)

    all_ids: list[int] = []
    token = None
    for _ in range(5):
        response = await route(
            request=request,
            current_user=SimpleNamespace(id=user.id),
            db=async_db,
            search=None,
            sort="position",
            page_size=2,
            page_token=token,
        )
        all_ids.extend(t.id for t in response.threads)
        token = response.next_page_token
        if token is None:
            break

    assert len(all_ids) == 5
    assert len(set(all_ids)) == 5, "No duplicate rows across pages"


@pytest.mark.asyncio
async def test_list_threads_multi_page_title(
    async_db: AsyncSession,
    db_engine: AsyncEngine,
) -> None:
    """Title-sort multi-page pagination returns all items correctly."""
    user = await get_or_create_user_async(async_db)

    for i, title in enumerate(["Alpha", "Bravo", "Charlie", "Delta"], start=1):
        t = Thread(
            user_id=user.id,
            title=title,
            format="Comic",
            issues_remaining=0,
            queue_position=i,
            status="active",
            created_at=datetime.now(UTC),
        )
        async_db.add(t)
    await async_db.flush()
    await async_db.commit()

    request = Request(
        {
            "type": "http",
            "method": "GET",
            "path": "/api/v1/threads/",
            "headers": [],
            "query_string": b"",
        }
    )
    route = unwrap(list_threads)

    all_titles: list[str] = []
    token = None
    for _ in range(5):
        response = await route(
            request=request,
            current_user=SimpleNamespace(id=user.id),
            db=async_db,
            search=None,
            sort="title",
            page_size=2,
            page_token=token,
        )
        all_titles.extend(t.title for t in response.threads)
        token = response.next_page_token
        if token is None:
            break

    assert all_titles == ["Alpha", "Bravo", "Charlie", "Delta"]
    assert len(set(all_titles)) == 4, "No duplicate rows across pages"


@pytest.mark.asyncio
async def test_list_threads_multi_page_created(
    async_db: AsyncSession,
    db_engine: AsyncEngine,
) -> None:
    """Created-sort multi-page pagination returns items newest-first."""
    user = await get_or_create_user_async(async_db)

    now = datetime.now(UTC)
    items = [
        ("Oldest", now - timedelta(days=10)),
        ("Middle", now - timedelta(days=5)),
        ("Newer", now - timedelta(days=2)),
        ("Newest", now),
    ]
    for i, (title, created) in enumerate(items, start=1):
        t = Thread(
            user_id=user.id,
            title=title,
            format="Comic",
            issues_remaining=0,
            queue_position=i,
            status="active",
            created_at=created,
        )
        async_db.add(t)
    await async_db.flush()
    await async_db.commit()

    request = Request(
        {
            "type": "http",
            "method": "GET",
            "path": "/api/v1/threads/",
            "headers": [],
            "query_string": b"",
        }
    )
    route = unwrap(list_threads)

    all_titles: list[str] = []
    token = None
    for _ in range(5):
        response = await route(
            request=request,
            current_user=SimpleNamespace(id=user.id),
            db=async_db,
            search=None,
            sort="created",
            page_size=2,
            page_token=token,
        )
        all_titles.extend(t.title for t in response.threads)
        token = response.next_page_token
        if token is None:
            break

    assert all_titles == ["Newest", "Newer", "Middle", "Oldest"]
    assert len(set(all_titles)) == 4, "No duplicate rows across pages"


@pytest.mark.asyncio
async def test_list_threads_stale_cursor_rejected_on_sort_change(
    async_db: AsyncSession,
    db_engine: AsyncEngine,
) -> None:
    """A cursor issued for sort=position is rejected when sort=title is requested."""
    user = await get_or_create_user_async(async_db)

    for i in range(1, 4):
        t = Thread(
            user_id=user.id,
            title=f"Thread-{i}",
            format="Comic",
            issues_remaining=0,
            queue_position=i,
            status="active",
            created_at=datetime.now(UTC),
        )
        async_db.add(t)
    await async_db.flush()
    await async_db.commit()

    request = Request(
        {
            "type": "http",
            "method": "GET",
            "path": "/api/v1/threads/",
            "headers": [],
            "query_string": b"",
        }
    )
    route = unwrap(list_threads)

    # Get first page with position sort
    page1 = await route(
        request=request,
        current_user=SimpleNamespace(id=user.id),
        db=async_db,
        search=None,
        sort="position",
        page_size=2,
        page_token=None,
    )
    assert page1.next_page_token is not None

    # Try to use that cursor with a different sort — should fail
    with pytest.raises(Exception, match="does not match"):
        await route(
            request=request,
            current_user=SimpleNamespace(id=user.id),
            db=async_db,
            search=None,
            sort="title",
            page_size=2,
            page_token=page1.next_page_token,
        )


@pytest.mark.asyncio
async def test_list_threads_stale_cursor_rejected_on_search_change(
    async_db: AsyncSession,
    db_engine: AsyncEngine,
) -> None:
    """A cursor issued for search='bat' is rejected when search='flash' is requested."""
    user = await get_or_create_user_async(async_db)

    for i, title in enumerate(["Batman", "Batgirl", "Flash", "Superman"], start=1):
        t = Thread(
            user_id=user.id,
            title=title,
            format="Comic",
            issues_remaining=0,
            queue_position=i,
            status="active",
            created_at=datetime.now(UTC),
        )
        async_db.add(t)
    await async_db.flush()
    await async_db.commit()

    request = Request(
        {
            "type": "http",
            "method": "GET",
            "path": "/api/v1/threads/",
            "headers": [],
            "query_string": b"",
        }
    )
    route = unwrap(list_threads)

    # Get first page with search="bat"
    page1 = await route(
        request=request,
        current_user=SimpleNamespace(id=user.id),
        db=async_db,
        search="bat",
        sort="title",
        page_size=1,
        page_token=None,
    )
    assert page1.next_page_token is not None

    # Try to use that cursor with a different search — should fail
    with pytest.raises(Exception, match="does not match"):
        await route(
            request=request,
            current_user=SimpleNamespace(id=user.id),
            db=async_db,
            search="flash",
            sort="title",
            page_size=1,
            page_token=page1.next_page_token,
        )


@pytest.mark.asyncio
async def test_list_threads_ownership_isolation(
    async_db: AsyncSession,
    db_engine: AsyncEngine,
) -> None:
    """Each user only sees their own threads."""
    from app.models import User as UserModel

    user1 = await get_or_create_user_async(async_db, username="cursor_owner_1")
    user2 = await get_or_create_user_async(async_db, username="cursor_owner_2")

    t1 = Thread(
        user_id=user1.id,
        title="User1-Thread",
        format="Comic",
        issues_remaining=0,
        queue_position=1,
        status="active",
        created_at=datetime.now(UTC),
    )
    t2 = Thread(
        user_id=user2.id,
        title="User2-Thread",
        format="Comic",
        issues_remaining=0,
        queue_position=1,
        status="active",
        created_at=datetime.now(UTC),
    )
    async_db.add_all([t1, t2])
    await async_db.flush()
    await async_db.commit()

    request = Request(
        {
            "type": "http",
            "method": "GET",
            "path": "/api/v1/threads/",
            "headers": [],
            "query_string": b"",
        }
    )
    route = unwrap(list_threads)

    resp1 = await route(
        request=request,
        current_user=SimpleNamespace(id=user1.id),
        db=async_db,
        search=None,
        sort="position",
        page_size=50,
        page_token=None,
    )
    resp2 = await route(
        request=request,
        current_user=SimpleNamespace(id=user2.id),
        db=async_db,
        search=None,
        sort="position",
        page_size=50,
        page_token=None,
    )

    assert len(resp1.threads) == 1
    assert resp1.threads[0].title == "User1-Thread"
    assert len(resp2.threads) == 1
    assert resp2.threads[0].title == "User2-Thread"


@pytest.mark.asyncio
async def test_list_threads_duplicate_positions_no_gaps(
    async_db: AsyncSession,
    db_engine: AsyncEngine,
) -> None:
    """Threads sharing the same position still paginate without gaps or skips."""
    user = await get_or_create_user_async(async_db)

    # Three threads all at position 1 — tie-breaker is id
    for i in range(1, 4):
        t = Thread(
            user_id=user.id,
            title=f"Duplicate-Pos-{i}",
            format="Comic",
            issues_remaining=0,
            queue_position=1,
            status="active",
            created_at=datetime.now(UTC),
        )
        async_db.add(t)
    await async_db.flush()
    await async_db.commit()

    request = Request(
        {
            "type": "http",
            "method": "GET",
            "path": "/api/v1/threads/",
            "headers": [],
            "query_string": b"",
        }
    )
    route = unwrap(list_threads)

    all_ids: list[int] = []
    token = None
    for _ in range(5):
        response = await route(
            request=request,
            current_user=SimpleNamespace(id=user.id),
            db=async_db,
            search=None,
            sort="position",
            page_size=2,
            page_token=token,
        )
        all_ids.extend(t.id for t in response.threads)
        token = response.next_page_token
        if token is None:
            break

    assert len(all_ids) == 3
    assert len(set(all_ids)) == 3, "No duplicate rows even with duplicate positions"


@pytest.mark.asyncio
async def test_list_threads_search_filter(
    async_db: AsyncSession,
    db_engine: AsyncEngine,
) -> None:
    """Search filters results and cursors are bound to the search text."""
    user = await get_or_create_user_async(async_db)

    for i, title in enumerate(["Batman", "Flash", "Batgirl"], start=1):
        t = Thread(
            user_id=user.id,
            title=title,
            format="Comic",
            issues_remaining=0,
            queue_position=i,
            status="active",
            created_at=datetime.now(UTC),
        )
        async_db.add(t)
    await async_db.flush()
    await async_db.commit()

    request = Request(
        {
            "type": "http",
            "method": "GET",
            "path": "/api/v1/threads/",
            "headers": [],
            "query_string": b"",
        }
    )
    route = unwrap(list_threads)
    response = await route(
        request=request,
        current_user=SimpleNamespace(id=user.id),
        db=async_db,
        search="bat",
        sort="position",
        page_size=50,
        page_token=None,
    )
    titles = [t.title for t in response.threads]
    assert "Batman" in titles
    assert "Batgirl" in titles
    assert "Flash" not in titles


@pytest.mark.asyncio
async def test_list_threads_invalid_sort_param(
    async_db: AsyncSession,
    db_engine: AsyncEngine,
) -> None:
    """Invalid sort parameter returns 400."""
    user = await get_or_create_user_async(async_db)
    await async_db.commit()

    request = Request(
        {
            "type": "http",
            "method": "GET",
            "path": "/api/v1/threads/",
            "headers": [],
            "query_string": b"",
        }
    )
    route = unwrap(list_threads)
    with pytest.raises(Exception, match="sort must be one of"):
        await route(
            request=request,
            current_user=SimpleNamespace(id=user.id),
            db=async_db,
            search=None,
            sort="bogus",
            page_size=50,
            page_token=None,
        )


@pytest.mark.asyncio
async def test_list_threads_invalid_page_token(
    async_db: AsyncSession,
    db_engine: AsyncEngine,
) -> None:
    """Malformed page_token returns 400."""
    user = await get_or_create_user_async(async_db)
    await async_db.commit()

    request = Request(
        {
            "type": "http",
            "method": "GET",
            "path": "/api/v1/threads/",
            "headers": [],
            "query_string": b"",
        }
    )
    route = unwrap(list_threads)
    with pytest.raises(Exception, match="Invalid Queue page token"):
        await route(
            request=request,
            current_user=SimpleNamespace(id=user.id),
            db=async_db,
            search=None,
            sort="position",
            page_size=50,
            page_token="definitely-not-valid!!",
        )


@pytest.mark.asyncio
async def test_list_threads_last_page_has_no_token(
    async_db: AsyncSession,
    db_engine: AsyncEngine,
) -> None:
    """The last page of results returns no next_page_token."""
    user = await get_or_create_user_async(async_db)

    for i in range(1, 4):
        t = Thread(
            user_id=user.id,
            title=f"T-{i}",
            format="Comic",
            issues_remaining=0,
            queue_position=i,
            status="active",
            created_at=datetime.now(UTC),
        )
        async_db.add(t)
    await async_db.flush()
    await async_db.commit()

    request = Request(
        {
            "type": "http",
            "method": "GET",
            "path": "/api/v1/threads/",
            "headers": [],
            "query_string": b"",
        }
    )
    route = unwrap(list_threads)

    # Page size equals total — should have no next_page_token
    response = await route(
        request=request,
        current_user=SimpleNamespace(id=user.id),
        db=async_db,
        search=None,
        sort="position",
        page_size=3,
        page_token=None,
    )
    assert response.next_page_token is None
    assert len(response.threads) == 3


@pytest.mark.asyncio
async def test_list_threads_cursor_values_match_last_row(
    async_db: AsyncSession,
    db_engine: AsyncEngine,
) -> None:
    """The cursor in next_page_token encodes the last row's sort key and id."""
    user = await get_or_create_user_async(async_db)

    for i in range(1, 4):
        t = Thread(
            user_id=user.id,
            title=f"Thread-{i}",
            format="Comic",
            issues_remaining=0,
            queue_position=i,
            status="active",
            created_at=datetime.now(UTC),
        )
        async_db.add(t)
    await async_db.flush()
    await async_db.commit()

    request = Request(
        {
            "type": "http",
            "method": "GET",
            "path": "/api/v1/threads/",
            "headers": [],
            "query_string": b"",
        }
    )
    route = unwrap(list_threads)
    response = await route(
        request=request,
        current_user=SimpleNamespace(id=user.id),
        db=async_db,
        search=None,
        sort="position",
        page_size=2,
        page_token=None,
    )
    assert response.next_page_token is not None
    cursor = decode_queue_cursor(response.next_page_token, sort="position", search=None)
    # Last item in page 1 has position=2, and its id
    last = response.threads[-1]
    assert cursor.values == (
        "1" if last.is_blocked else "0",
        str(last.queue_position),
        str(last.id),
    )


def _queue_request() -> Request:
    """Build a minimal GET request for direct list_threads invocation."""
    return Request(
        {
            "type": "http",
            "method": "GET",
            "path": "/api/v1/threads/",
            "headers": [],
            "query_string": b"",
        }
    )


@pytest.mark.asyncio
async def test_list_threads_position_blocked_grouping_across_page_boundary(
    async_db: AsyncSession,
    db_engine: AsyncEngine,
) -> None:
    """Blocked rows sort after unblocked rows even when the page boundary splits them."""
    user = await get_or_create_user_async(async_db)
    async_db.add_all(
        [
            Thread(
                user_id=user.id,
                title="Unblocked-Back",
                format="Comic",
                issues_remaining=0,
                queue_position=5,
                status="active",
                is_blocked=False,
                created_at=datetime.now(UTC),
            ),
            Thread(
                user_id=user.id,
                title="Unblocked-Front",
                format="Comic",
                issues_remaining=0,
                queue_position=1,
                status="active",
                is_blocked=False,
                created_at=datetime.now(UTC),
            ),
            Thread(
                user_id=user.id,
                title="Blocked-A",
                format="Comic",
                issues_remaining=0,
                queue_position=2,
                status="active",
                is_blocked=True,
                created_at=datetime.now(UTC),
            ),
            Thread(
                user_id=user.id,
                title="Blocked-B",
                format="Comic",
                issues_remaining=0,
                queue_position=4,
                status="active",
                is_blocked=True,
                created_at=datetime.now(UTC),
            ),
        ]
    )
    await async_db.flush()
    await async_db.commit()

    request = _queue_request()
    route = unwrap(list_threads)

    first_page_titles: list[str] = []
    all_titles: list[str] = []
    all_ids: list[int] = []
    blocked_flags: list[bool] = []
    token = None
    for page_index in range(5):
        response = await route(
            request=request,
            current_user=SimpleNamespace(id=user.id),
            db=async_db,
            search=None,
            sort="position",
            page_size=2,
            page_token=token,
        )
        page_titles = [t.title for t in response.threads]
        if page_index == 0:
            first_page_titles = page_titles
        all_titles.extend(page_titles)
        all_ids.extend(t.id for t in response.threads)
        blocked_flags.extend(t.is_blocked for t in response.threads)
        token = response.next_page_token
        if token is None:
            break

    # Feasible-only order: unblocked by position, then blocked by position.
    assert all_titles == [
        "Unblocked-Front",
        "Unblocked-Back",
        "Blocked-A",
        "Blocked-B",
    ]
    assert blocked_flags == [False, False, True, True]
    assert len(all_ids) == 4 and len(set(all_ids)) == 4
    # Appending page 2 must not insert a row ahead of an already displayed row.
    assert first_page_titles == ["Unblocked-Front", "Unblocked-Back"]
    assert all_titles[: len(first_page_titles)] == first_page_titles


@pytest.mark.asyncio
async def test_list_threads_position_tied_sort_across_page_boundary(
    async_db: AsyncSession,
    db_engine: AsyncEngine,
) -> None:
    """Threads sharing a position paginate by id with no skips across the boundary."""
    user = await get_or_create_user_async(async_db)
    for i in range(1, 4):
        async_db.add(
            Thread(
                user_id=user.id,
                title=f"Tied-Position-{i}",
                format="Comic",
                issues_remaining=0,
                queue_position=7,
                status="active",
                is_blocked=False,
                created_at=datetime.now(UTC),
            )
        )
    await async_db.flush()
    await async_db.commit()

    request = _queue_request()
    route = unwrap(list_threads)

    all_ids: list[int] = []
    token = None
    for _ in range(5):
        response = await route(
            request=request,
            current_user=SimpleNamespace(id=user.id),
            db=async_db,
            search=None,
            sort="position",
            page_size=2,
            page_token=token,
        )
        all_ids.extend(t.id for t in response.threads)
        token = response.next_page_token
        if token is None:
            break

    assert len(all_ids) == 3
    assert all_ids == sorted(all_ids)


@pytest.mark.asyncio
async def test_list_threads_title_tied_sort_across_page_boundary(
    async_db: AsyncSession,
    db_engine: AsyncEngine,
) -> None:
    """Threads sharing a title paginate by id with no skips across the boundary."""
    user = await get_or_create_user_async(async_db)
    for i in range(1, 4):
        async_db.add(
            Thread(
                user_id=user.id,
                title="Same Title",
                format="Comic",
                issues_remaining=0,
                queue_position=i,
                status="active",
                is_blocked=False,
                created_at=datetime.now(UTC),
            )
        )
    await async_db.flush()
    await async_db.commit()

    request = _queue_request()
    route = unwrap(list_threads)

    all_ids: list[int] = []
    token = None
    for _ in range(5):
        response = await route(
            request=request,
            current_user=SimpleNamespace(id=user.id),
            db=async_db,
            search=None,
            sort="title",
            page_size=2,
            page_token=token,
        )
        all_ids.extend(t.id for t in response.threads)
        token = response.next_page_token
        if token is None:
            break

    assert len(all_ids) == 3
    assert all_ids == sorted(all_ids)


@pytest.mark.asyncio
async def test_list_threads_created_tied_sort_across_page_boundary(
    async_db: AsyncSession,
    db_engine: AsyncEngine,
) -> None:
    """Created sort tie-breaks by id descending with no skips across the boundary."""
    user = await get_or_create_user_async(async_db)
    shared_created = datetime.now(UTC)
    for i in range(1, 4):
        async_db.add(
            Thread(
                user_id=user.id,
                title=f"Tied-Created-{i}",
                format="Comic",
                issues_remaining=0,
                queue_position=i,
                status="active",
                is_blocked=False,
                created_at=shared_created,
            )
        )
    await async_db.flush()
    await async_db.commit()

    request = _queue_request()
    route = unwrap(list_threads)

    all_ids: list[int] = []
    token = None
    for _ in range(5):
        response = await route(
            request=request,
            current_user=SimpleNamespace(id=user.id),
            db=async_db,
            search=None,
            sort="created",
            page_size=2,
            page_token=token,
        )
        all_ids.extend(t.id for t in response.threads)
        token = response.next_page_token
        if token is None:
            break

    assert len(all_ids) == 3
    assert all_ids == sorted(all_ids, reverse=True)
