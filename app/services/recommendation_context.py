"""Versioned recommendation-context selection snapshots persisted on roll events.

Every new ``roll`` event carries a small, bounded JSON snapshot describing the
decision-time selection context that existed when the roll happened: which
algorithm ran, how big the die was, which bounded candidate set the selection
drew from, and where the selected thread stood in the queue at that moment.
The snapshot is stored under the ``selection`` key of the event's
``recommendation_context`` payload, next to the reading-effort decision
context. Later queue changes cannot rewrite this history because the snapshot
is captured before the event commits and is never updated afterward.

This module is instrumentation only. It never changes candidate ordering,
random-selection probability, dice behavior, queue movement, or snooze
semantics.

Payload schema (``schema_version`` 1)::

    {
        "schema_version": 1,
        "algorithm_version": "legacy-unweighted-v1",
        "selection_method": "random" | "override",
        "die_size": int,
        "pool_size": int,
        "candidate_thread_ids": [int, ...],
        "selected_thread_id": int,
        "selected_queue_position": int,
        "selected_candidate_index": int | null,
        "selected_result": int | null,
        "selected_last_rating": float | null,
        "selected_last_activity_at": str | null,
        "session_timezone": str | null,
        "local_hour": int | null,
        "daypart": str | null
    }

Field contract:

- ``schema_version``: Version of this payload shape. Bump when keys change.
- ``algorithm_version``: Identifies the selector that made the choice. The
  current production selector is the legacy uniform-random unweighted roll.
- ``selection_method``: ``"random"`` for die rolls, ``"override"`` for manual
  selections. Override payloads carry ``selected_candidate_index = null`` and
  ``selected_result = 0`` so manual picks are always distinguishable from a
  real draw.
- ``die_size``: Current die size for the session at roll time.
- ``pool_size``: Number of candidates actually available to the selector,
  bounded by the die size (``len(candidate_thread_ids)``).
- ``candidate_thread_ids``: Bounded candidate thread IDs in exact selection
  order (queue order). Never larger than the die size regardless of library
  size; no titles or other heavy metadata are serialized.
- ``selected_thread_id``: Thread chosen by the roll or override.
- ``selected_queue_position``: Queue position of the selected thread at
  decision time; later movement never changes it.
- ``selected_candidate_index``: Zero-based draw index into
  ``candidate_thread_ids`` for random rolls, otherwise null.
- ``selected_result``: One-based die face recorded on the event for random
  rolls; ``0`` for override rolls to match historical event semantics.
- ``selected_last_rating`` / ``selected_last_activity_at``: The selected
  thread's last rating and last-activity timestamp exactly as seen at decision
  time. ``last_activity_at`` is serialized as an ISO 8601 UTC string.
- ``session_timezone``: IANA timezone persisted on the reading session
  (#1690) when available; null when the session has none rather than guessed.
- ``local_hour`` / ``daypart``: Derived only when a usable persisted timezone
  exists. Dayparts: ``night`` (23-4), ``morning`` (5-11), ``afternoon``
  (12-17), ``evening`` (18-22). Unusable timezones fail safe to null.

There is deliberately no effort-estimate key inside this snapshot: no such
signal exists in this contract, and unknown data is omitted instead of
invented. The reading-effort decision context (``context_version`` and
``selected_candidate`` from :mod:`app.services.reading_effort`) is stored at
the top level of ``Event.recommendation_context``; this module's snapshot is
persisted alongside it under the namespaced ``selection`` key so both
contracts remain independently versioned and validated.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Literal
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from pydantic import BaseModel

RECOMMENDATION_CONTEXT_SCHEMA_VERSION = 1
ALGORITHM_VERSION_LEGACY_UNWEIGHTED = "legacy-unweighted-v1"

SELECTION_METHOD_RANDOM = "random"
SELECTION_METHOD_OVERRIDE = "override"


class RecommendationContextV1(BaseModel):
    """Typed contract for schema version 1 recommendation-context payloads."""

    schema_version: Literal[1]
    algorithm_version: str
    selection_method: str
    die_size: int
    pool_size: int
    candidate_thread_ids: list[int]
    selected_thread_id: int
    selected_queue_position: int
    selected_candidate_index: int | None
    selected_result: int | None
    selected_last_rating: float | None
    selected_last_activity_at: str | None
    session_timezone: str | None
    local_hour: int | None
    daypart: str | None


def validate_recommendation_context(payload: object) -> RecommendationContextV1:
    """Validate one stored payload against the schema-version-1 contract.

    Args:
        payload: Raw payload loaded from ``Event.recommendation_context``.

    Returns:
        The validated typed snapshot.

    Raises:
        ValidationError: If the payload does not satisfy the v1 contract.
    """
    return RecommendationContextV1.model_validate(payload)

_DAYPARTS_BY_HOUR: dict[int, str] = {
    **dict.fromkeys(range(5, 12), "morning"),
    **dict.fromkeys(range(12, 18), "afternoon"),
    **dict.fromkeys(range(18, 23), "evening"),
    **{23: "night", 0: "night", 1: "night", 2: "night", 3: "night", 4: "night"},
}


def daypart_for_hour(hour: int) -> str:
    """Map a local hour to its documented daypart bucket.

    Args:
        hour: Local wall-clock hour (0-23).

    Returns:
        One of ``morning``, ``afternoon``, ``evening``, or ``night``.
    """
    return _DAYPARTS_BY_HOUR[hour]


def _derive_local_time_fields(
    session_timezone: str | None, captured_at: datetime
) -> tuple[int | None, str | None]:
    """Derive local hour/daypart from a persisted IANA timezone, failing safe.

    Args:
        session_timezone: Persisted IANA timezone identifier, or None when the
            reading session has no captured timezone.
        captured_at: UTC instant to project into the timezone.

    Returns:
        ``(local_hour, daypart)``, both None when no usable timezone exists.
    """
    if not session_timezone:
        return None, None
    try:
        local_time = captured_at.astimezone(ZoneInfo(session_timezone))
    except (ZoneInfoNotFoundError, ValueError, OSError):
        return None, None
    hour = local_time.hour
    return hour, daypart_for_hour(hour)


def build_recommendation_context(
    *,
    selection_method: str,
    die_size: int,
    candidate_thread_ids: list[int],
    selected_thread_id: int,
    selected_queue_position: int,
    selected_candidate_index: int | None,
    selected_result: int | None,
    selected_last_rating: float | None,
    selected_last_activity_at: datetime | None,
    session_timezone: str | None = None,
    captured_at: datetime | None = None,
) -> dict[str, object]:
    """Build one versioned recommendation-context snapshot for a roll event.

    Args:
        selection_method: ``"random"`` or ``"override"``.
        die_size: Current die size for the session.
        candidate_thread_ids: Bounded candidate IDs in exact selection order.
        selected_thread_id: Thread chosen by the roll or override.
        selected_queue_position: Selected thread's queue position at decision
            time.
        selected_candidate_index: Zero-based draw index for random rolls, None
            for overrides.
        selected_result: Die face for random rolls, 0 for overrides.
        selected_last_rating: Selected thread's last rating at decision time.
        selected_last_activity_at: Selected thread's last-activity timestamp at
            decision time.
        session_timezone: Persisted session IANA timezone when available;
            callers pass the persisted session timezone when available.
        captured_at: Instant used for local-time derivation; defaults to now.

    Returns:
        A JSON-serializable context dict bounded by the candidate pool size.
    """
    instant = captured_at or datetime.now(UTC)
    local_hour, daypart = _derive_local_time_fields(
        session_timezone or None,
        instant if instant.tzinfo is not None else instant.replace(tzinfo=UTC),
    )

    return {
        "schema_version": RECOMMENDATION_CONTEXT_SCHEMA_VERSION,
        "algorithm_version": ALGORITHM_VERSION_LEGACY_UNWEIGHTED,
        "selection_method": selection_method,
        "die_size": die_size,
        "pool_size": len(candidate_thread_ids),
        "candidate_thread_ids": list(candidate_thread_ids),
        "selected_thread_id": selected_thread_id,
        "selected_queue_position": selected_queue_position,
        "selected_candidate_index": selected_candidate_index,
        "selected_result": selected_result,
        "selected_last_rating": selected_last_rating,
        "selected_last_activity_at": (
            selected_last_activity_at.isoformat() if selected_last_activity_at else None
        ),
        "session_timezone": session_timezone,
        "local_hour": local_hour,
        "daypart": daypart,
    }
