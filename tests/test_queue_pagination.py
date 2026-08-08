"""Tests for deterministic Queue pagination contracts."""

import base64
import json

import pytest

from app.services.queue_pagination import (
    QueueCursor,
    decode_queue_cursor,
    encode_queue_cursor,
    normalize_queue_search,
)


def test_queue_cursor_round_trips_for_same_query() -> None:
    """Round-trip a cursor when sort and normalized search are unchanged."""
    cursor = QueueCursor(sort="position", search="batman", values=("10", "42"))

    token = encode_queue_cursor(cursor)

    assert decode_queue_cursor(token, sort="position", search=" Batman ") == cursor


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


def test_queue_cursor_rejects_non_string_sort() -> None:
    """Reject malformed cursor payloads whose sort field is not a string."""
    payload = json.dumps(
        {"sort": [], "search": "", "values": ["x-men", "42"]},
        separators=(",", ":"),
    ).encode()
    token = base64.urlsafe_b64encode(payload).decode().rstrip("=")

    with pytest.raises(ValueError, match="Invalid Queue page token sort"):
        decode_queue_cursor(token, sort="title", search=None)


def test_queue_search_normalization_is_case_insensitive_and_trimmed() -> None:
    """Normalize Queue search text before binding it to a pagination cursor."""
    assert normalize_queue_search("  The Flash  ") == "the flash"
