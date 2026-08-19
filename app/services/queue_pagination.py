"""Deterministic Queue pagination contracts."""

from __future__ import annotations

import base64
import binascii
import json
from dataclasses import dataclass
from datetime import datetime
from typing import Any, Literal

from sqlalchemy import ColumnElement, or_
from sqlalchemy.sql.elements import ColumnElement as SQLColumnElement

from app.models.thread import Thread

QueueSort = Literal["position", "title", "created"]


@dataclass(frozen=True)
class QueueCursor:
    """Opaque Queue cursor bound to one search and sort contract."""

    sort: QueueSort
    search: str
    values: tuple[str, ...]


def normalize_queue_search(search: str | None) -> str:
    """Normalize Queue search text for cursor compatibility checks.

    Args:
        search: Optional user-entered Queue search text.

    Returns:
        Trimmed, case-folded search text, or an empty string when absent.
    """
    return search.strip().casefold() if search else ""


def encode_queue_cursor(cursor: QueueCursor) -> str:
    """Encode a Queue cursor as URL-safe opaque text.

    Args:
        cursor: Queue cursor contract to serialize.

    Returns:
        URL-safe base64 text without padding.
    """
    payload = {
        "sort": cursor.sort,
        "search": normalize_queue_search(cursor.search),
        "values": list(cursor.values),
    }
    raw = json.dumps(payload, separators=(",", ":"), sort_keys=True).encode()
    return base64.urlsafe_b64encode(raw).decode().rstrip("=")


def decode_queue_cursor(
    token: str,
    *,
    sort: QueueSort,
    search: str | None,
) -> QueueCursor:
    """Decode and validate that a Queue cursor matches current query inputs.

    Args:
        token: URL-safe opaque Queue cursor text.
        sort: Sort order requested for the current Queue page.
        search: Optional search text requested for the current Queue page.

    Returns:
        Validated Queue cursor bound to the current search and sort contract.

    Raises:
        ValueError: If the token is malformed or belongs to another search/sort contract.
    """
    try:
        padded = token + "=" * (-len(token) % 4)
        decoded = base64.b64decode(padded.encode(), altchars=b"-_", validate=True)
        payload = json.loads(decoded.decode())
        cursor_sort = payload["sort"]
        cursor_search = payload["search"]
        raw_values = payload["values"]
    except (
        binascii.Error,
        KeyError,
        TypeError,
        UnicodeDecodeError,
        ValueError,
        json.JSONDecodeError,
    ) as exc:
        raise ValueError("Invalid Queue page token") from exc

    if not isinstance(cursor_sort, str) or cursor_sort not in {
        "position",
        "title",
        "created",
    }:
        raise ValueError("Invalid Queue page token sort")
    if not isinstance(cursor_search, str) or not isinstance(raw_values, list):
        raise ValueError("Invalid Queue page token payload")
    if not all(isinstance(value, str) for value in raw_values):
        raise ValueError("Invalid Queue page token values")

    normalized_search = normalize_queue_search(search)
    if cursor_sort != sort or cursor_search != normalized_search:
        raise ValueError("Queue page token does not match current search or sort")

    return QueueCursor(
        sort=cursor_sort,
        search=cursor_search,
        values=tuple(raw_values),
    )


def build_sort_order(sort: QueueSort) -> list[SQLColumnElement[Any]]:
    """Return the SQLAlchemy ORDER BY columns for the given sort mode.

    Every sort uses ``Thread.id`` as a deterministic tie-breaker so that
    rows with identical sort values never produce non-deterministic page
    boundaries.

    Args:
        sort: One of ``"position"``, ``"title"``, or ``"created"``.

    Returns:
        List of SQLAlchemy column elements suitable for ``.order_by()``.
    """
    if sort == "position":
        return [Thread.queue_position.asc(), Thread.id.asc()]
    if sort == "title":
        return [Thread.title.asc(), Thread.id.asc()]
    # created: newest first is the natural exploration order
    return [Thread.created_at.desc(), Thread.id.desc()]


def build_cursor_filter(cursor: QueueCursor) -> ColumnElement[bool]:
    """Build a WHERE clause that skips past the cursor row.

    The filter implements keyset pagination: keep every row that sorts
    strictly after the cursor row, using ``(sort_value, id)`` as the
    composite key.

    Args:
        cursor: A validated cursor whose ``values`` tuple matches the
            current sort contract.

    Returns:
        A SQLAlchemy boolean expression for use in ``.where()``.
    """
    if cursor.sort == "position":
        cursor_position = int(cursor.values[0])
        cursor_id = int(cursor.values[1])
        return or_(
            Thread.queue_position > cursor_position,
            (Thread.queue_position == cursor_position) & (Thread.id > cursor_id),
        )

    if cursor.sort == "title":
        cursor_title = cursor.values[0]
        cursor_id = int(cursor.values[1])
        return or_(
            Thread.title > cursor_title,
            (Thread.title == cursor_title) & (Thread.id > cursor_id),
        )

    # created: newest first, so "after" means strictly older
    cursor_created = datetime.fromisoformat(cursor.values[0])
    cursor_id = int(cursor.values[1])
    return or_(
        Thread.created_at < cursor_created,
        (Thread.created_at == cursor_created) & (Thread.id < cursor_id),
    )


def build_cursor_values_from_row(sort: QueueSort, thread: Thread) -> tuple[str, ...]:
    """Extract the cursor values from the last row of a page.

    Args:
        sort: The sort mode used for the query.
        thread: The last ``Thread`` row returned for the current page.

    Returns:
        A tuple of string-encoded sort-key and id values.
    """
    if sort == "position":
        return (str(thread.queue_position), str(thread.id))
    if sort == "title":
        return (thread.title, str(thread.id))
    return (thread.created_at.isoformat(), str(thread.id))
