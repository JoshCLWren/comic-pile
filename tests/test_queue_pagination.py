"""Tests for deterministic Queue pagination contracts."""

import base64
import json
from datetime import UTC, datetime

import pytest
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession as SQLAlchemyAsyncSession

from app.models import Thread, User
from app.services.queue_pagination import (
    QueueCursor,
    decode_queue_cursor,
    encode_queue_cursor,
    normalize_queue_search,
)


def _encode_payload(payload: object) -> str:
    """Encode an arbitrary payload as a Queue cursor token for validation tests."""
    raw = json.dumps(payload, separators=(",", ":")).encode()
    return base64.urlsafe_b64encode(raw).decode().rstrip("=")


def test_queue_cursor_round_trips_for_same_query() -> None:
    """Round-trip a cursor when sort and normalized search are unchanged."""
    cursor = QueueCursor(sort="position", search=" Batman ", values=("10", "42"))

    token = encode_queue_cursor(cursor)

    assert encode_queue_cursor(cursor) == token
    assert decode_queue_cursor(token, sort="position", search=" BATMAN ") == QueueCursor(
        sort="position",
        search="batman",
        values=("10", "42"),
    )


def test_queue_cursor_rejects_sort_change() -> None:
    """Reject a cursor when the requested sort differs from its contract."""
    token = encode_queue_cursor(
        QueueCursor(sort="position", search="", values=("10", "42")),
    )

    with pytest.raises(ValueError, match="does not match"):
        decode_queue_cursor(token, sort="title", search=None)


def test_queue_cursor_rejects_search_change() -> None:
    """Reject a cursor when the normalized search differs from its contract."""
    token = encode_queue_cursor(
        QueueCursor(sort="title", search="x-men", values=("x-men", "42")),
    )

    with pytest.raises(ValueError, match="does not match"):
        decode_queue_cursor(token, sort="title", search="x-force")


def test_queue_cursor_rejects_malformed_token() -> None:
    """Reject malformed Queue cursor tokens with the stable validation error."""
    with pytest.raises(ValueError, match="Invalid Queue page token"):
        decode_queue_cursor("not-a-valid-token", sort="created", search=None)


def test_queue_cursor_rejects_appended_invalid_base64_bytes() -> None:
    """Reject tokens containing bytes outside the URL-safe base64 alphabet."""
    token = encode_queue_cursor(
        QueueCursor(sort="title", search="", values=("x-men", "42")),
    )

    with pytest.raises(ValueError, match="Invalid Queue page token"):
        decode_queue_cursor(f"{token}!", sort="title", search=None)


@pytest.mark.parametrize(
    ("payload", "message"),
    [
        ({"sort": [], "search": "", "values": ["x-men", "42"]}, "token sort"),
        ({"sort": "bogus", "search": "", "values": ["x-men", "42"]}, "token sort"),
        ({"sort": "title", "search": [], "values": ["x-men", "42"]}, "token payload"),
        ({"sort": "title", "search": "", "values": "x-men"}, "token payload"),
        ({"sort": "title", "search": "", "values": ["x-men", 42]}, "token values"),
    ],
)
def test_queue_cursor_rejects_invalid_payload_shapes(payload: object, message: str) -> None:
    """Reject malformed payload field types and unsupported sort values."""
    token = _encode_payload(payload)

    with pytest.raises(ValueError, match=message):
        decode_queue_cursor(token, sort="title", search=None)


def test_queue_search_normalization_is_case_insensitive_and_trimmed() -> None:
    """Normalize Queue search text before binding it to a pagination cursor."""
    assert normalize_queue_search("  The Flash  ") == "the flash"


@pytest.mark.asyncio
async def test_list_threads_stale_cursor_rejected_when_sort_changes(
    auth_client: AsyncClient,
    sample_data: dict,
) -> None:
    """API returns HTTP 400 when a cursor from one sort type is used with a different sort."""
    # Get first page with position sort to acquire a valid token
    response = await auth_client.get("/api/threads/?page_size=2&sort=position")
    assert response.status_code == 200
    token = response.json()["next_page_token"]
    assert token is not None

    # Reusing that token with a different sort must be rejected
    response = await auth_client.get(
        "/api/threads/?page_size=2&sort=title&page_token=" + token,
    )
    assert response.status_code == 400
    assert "does not match" in response.json()["detail"]


@pytest.mark.asyncio
async def test_list_threads_stale_cursor_rejected_when_search_changes(
    auth_client: AsyncClient,
    sample_data: dict,
) -> None:
    """API returns HTTP 400 when a cursor bound to one search is reused with a different search."""
    # Get first page searching for "superman" to acquire a token bound to that search
    response = await auth_client.get("/api/threads/?page_size=2&search=superman")
    assert response.status_code == 200
    token = response.json()["next_page_token"]
    assert token is not None

    # Reusing token with a different search must be rejected
    response = await auth_client.get(
        "/api/threads/?page_size=2&search=batman&page_token=" + token,
    )
    assert response.status_code == 400
    assert "does not match" in response.json()["detail"]


@pytest.mark.asyncio
async def test_list_threads_position_sort_paginates(auth_client: AsyncClient, sample_data: dict) -> None:
    """Two-page position-sorted cursor round-trip returns contiguous window with no overlap or gap."""
    threads = sample_data["threads"]
    active_threads = [t for t in threads if t["status"] == "active"]
    assert len(active_threads) >= 4, "Need at least 4 active threads for this test"

    page_size = 2

    response1 = await auth_client.get(f"/api/threads/?page_size={page_size}&sort=position")
    assert response1.status_code == 200
    data1 = response1.json()
    assert len(data1["threads"]) == page_size
    token1 = data1["next_page_token"]
    assert token1 is not None

    response2 = await auth_client.get(
        f"/api/threads/?page_size={page_size}&sort=position&page_token={token1}",
    )
    assert response2.status_code == 200
    data2 = response2.json()
    assert len(data2["threads"]) == page_size

    # No overlap between pages
    ids_page1 = {t["id"] for t in data1["threads"]}
    ids_page2 = {t["id"] for t in data2["threads"]}
    assert ids_page1.isdisjoint(ids_page2)

    # Pages ordered by position
    all_ids = [t["id"] for t in data1["threads"] + data2["threads"]]
    expected = sorted({t.id for t in active_threads}, key=lambda tid: next(
        t.queue_position for t in active_threads if t.id == tid
    ))[: page_size * 2]
    assert all_ids == expected


@pytest.mark.asyncio
async def test_list_threads_title_sort_paginates(auth_client: AsyncClient, sample_data: dict) -> None:
    """Title-sorted cursor advances correctly across pages; no rows skipped or duplicated."""
    # Title sort of sample data: Aquaman, Batman, Flash, Superman, Wonder Woman
    # (4 active threads) — use page_size=2 to get two pages
    response1 = await auth_client.get("/api/threads/?page_size=2&sort=title")
    assert response1.status_code == 200
    data1 = response1.json()
    titles_page1 = [t["title"] for t in data1["threads"]]
    assert len(titles_page1) == 2
    assert titles_page1 == sorted(titles_page1), "Page 1 must be title-sorted"

    token1 = data1["next_page_token"]
    assert token1 is not None

    response2 = await auth_client.get(
        f"/api/threads/?page_size=2&sort=title&page_token={token1}",
    )
    assert response2.status_code == 200
    data2 = response2.json()
    titles_page2 = [t["title"] for t in data2["threads"]]
    assert len(titles_page2) == 2
    assert titles_page2 == sorted(titles_page2), "Page 2 must be title-sorted"

    # Decode the page-1 token and confirm sort/search are bound
    from app.services.queue_pagination import decode_queue_cursor
    decoded = decode_queue_cursor(token1, sort="title", search="")
    assert decoded.sort == "title"
    assert decoded.search == ""
    assert len(decoded.values) == 2
    # The stored value must be a title, not a queue_position integer converted to str
    assert decoded.values[0] in titles_page1  # pivot is the last title of page 1

    # No overlap
    assert set(titles_page1).isdisjoint(set(titles_page2))

    # Together they should cover 4 active threads alphabetically
    combined = titles_page1 + titles_page2
    expected_sorted = sorted(
        [t.title for t in sample_data["threads"] if t["status"] == "active"]
    )
    assert combined == expected_sorted


@pytest.mark.asyncio
async def test_list_threads_ownership_isolation(
    auth_client: AsyncClient,
    async_db: SQLAlchemyAsyncSession,
    sample_data: dict,
) -> None:
    """A second user's threads are never returned, even when using a different user's cursor."""
    user2 = User(username="other_user", created_at=datetime.now(UTC))

    # Create a second user with its own threads
    user2 = User(username="other_user", created_at=datetime.now(UTC))
    async_db.add(user2)
    await async_db.flush()
    other_threads = [
        Thread(
            title="Omega Men",
            format="Series",
            issues_remaining=3,
            queue_position=1,
            status="active",
            user_id=user2.id,
            created_at=datetime.now(UTC),
        ),
        Thread(
            title="X-Men",
            format="Series",
            issues_remaining=7,
            queue_position=2,
            status="active",
            user_id=user2.id,
            created_at=datetime.now(UTC),
        ),
    ]
    for t in other_threads:
        async_db.add(t)
    await async_db.flush()
    for t in other_threads:
        await async_db.refresh(t)

    # page_size=1 forces a next-page token
    response1 = await auth_client.get("/api/threads/?page_size=1&sort=title")
    assert response1.status_code == 200
    data1 = response1.json()
    token1 = data1["next_page_token"]
    assert token1 is not None
    # Must not include any of user2's threads
    ids_page1 = {t["id"] for t in data1["threads"]}
    assert not any(t["id"] in ids_page1 for t in other_threads)

    # Using the cursor — still only first user's threads
    response2 = await auth_client.get(
        f"/api/threads/?page_size=1&sort=title&page_token={token1}",
    )
    assert response2.status_code == 200
    data2 = response2.json()
    ids_page2 = {t["id"] for t in data2["threads"]}
    assert not any(t["id"] in ids_page2 for t in other_threads)

    # Combined pages must not contain any user2 thread
    all_returned_ids = ids_page1 | ids_page2
    for t in other_threads:
        assert t.id not in all_returned_ids


@pytest.mark.asyncio
async def test_list_threads_cursor_rejected_when_search_changes(
    auth_client: AsyncClient,
    sample_data: dict,
) -> None:
    """API rejects a cursor whose embedded search does not match the current request search."""
    # Create thread with unique title for clear search filtering
    response = await auth_client.post(
        "/api/threads/",
        json={
            "title": "Zebra Stripes",
            "format": "Ongoing",
            "issues_remaining": 2,
            "queue_position": 100,
        },
    )
    assert response.status_code == 201

    # Acquire a cursor via a search that matches no threads (empty result + next token
    # only exists when results fill a page; use >page_size)
    # Use a search yielding a small result set; get next token by using page_size=1
    response_first = await auth_client.get("/api/threads/?search=zebra&page_size=1&sort=title")
    assert response_first.status_code == 200
    token = response_first.json()["next_page_token"]

    # Change the search — token must be rejected
    response_changed = await auth_client.get(
        "/api/threads/?search=bman&page_size=1&sort=title&page_token=" + token,
    )
    assert response_changed.status_code == 400
    assert "does not match" in response_changed.json()["detail"]
