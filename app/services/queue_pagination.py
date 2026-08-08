"""Deterministic Queue pagination contracts."""

from __future__ import annotations

import base64
import json
from dataclasses import dataclass
from typing import Literal

QueueSort = Literal["position", "title", "created"]


@dataclass(frozen=True)
class QueueCursor:
    """Opaque Queue cursor bound to one search and sort contract."""

    sort: QueueSort
    search: str
    values: tuple[str, ...]


def normalize_queue_search(search: str | None) -> str:
    """Normalize Queue search text for cursor compatibility checks."""
    return search.strip().casefold() if search else ""


def encode_queue_cursor(cursor: QueueCursor) -> str:
    """Encode a Queue cursor as URL-safe opaque text."""
    payload = {
        "sort": cursor.sort,
        "search": cursor.search,
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

    Raises:
        ValueError: If the token is malformed or belongs to another search/sort contract.
    """
    try:
        padded = token + "=" * (-len(token) % 4)
        payload = json.loads(base64.urlsafe_b64decode(padded.encode()).decode())
        cursor_sort = payload["sort"]
        cursor_search = payload["search"]
        raw_values = payload["values"]
    except (KeyError, TypeError, ValueError, json.JSONDecodeError) as exc:
        raise ValueError("Invalid Queue page token") from exc

    if cursor_sort not in {"position", "title", "created"}:
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
