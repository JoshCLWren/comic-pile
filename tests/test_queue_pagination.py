"""Tests for deterministic Queue pagination contracts."""

import base64
import json
from typing import cast

import pytest

from app.services.queue_pagination import (
    QueueCursor,
    QueueSort,
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
    cursor = QueueCursor(sort="position", search=" Batman ", values=("0", "10", "42"))

    token = encode_queue_cursor(cursor)

    assert encode_queue_cursor(cursor) == token
    assert decode_queue_cursor(token, sort="position", search=" BATMAN ") == QueueCursor(
        sort="position",
        search="batman",
        values=("0", "10", "42"),
    )


def test_queue_cursor_rejects_sort_change() -> None:
    """Reject a cursor when the requested sort differs from its contract."""
    token = encode_queue_cursor(
        QueueCursor(sort="position", search="", values=("0", "10", "42")),
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


@pytest.mark.parametrize(
    ("payload", "sort"),
    [
        ({"sort": "position", "search": "", "values": ["5", "10"]}, "position"),
        (
            {"sort": "position", "search": "", "values": ["0", "5", "10", "extra"]},
            "position",
        ),
        ({"sort": "title", "search": "", "values": ["x-men"]}, "title"),
        (
            {"sort": "created", "search": "", "values": ["2024-01-01T00:00:00+00:00"]},
            "created",
        ),
    ],
)
def test_queue_cursor_rejects_wrong_value_count(payload: object, sort: str) -> None:
    """Reject a cursor whose sort-key value count does not match its contract."""
    token = _encode_payload(payload)

    with pytest.raises(ValueError, match="token values"):
        decode_queue_cursor(token, sort=cast(QueueSort, sort), search=None)


@pytest.mark.parametrize("blocked_flag", ["true", "2", ""])
def test_queue_cursor_rejects_invalid_position_blocked_flag(blocked_flag: str) -> None:
    """Reject a position cursor whose blocked grouping key is not 0 or 1."""
    token = _encode_payload(
        {"sort": "position", "search": "", "values": [blocked_flag, "5", "10"]}
    )

    with pytest.raises(ValueError, match="token values"):
        decode_queue_cursor(token, sort="position", search=None)


def test_queue_search_normalization_is_case_insensitive_and_trimmed() -> None:
    """Normalize Queue search text before binding it to a pagination cursor."""
    assert normalize_queue_search("  The Flash  ") == "the flash"
