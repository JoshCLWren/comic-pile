"""Versioned recommendation-context snapshots attached to roll events.

Every new roll event persists a small, versioned JSON snapshot describing what
ComicPile knew at decision time. The payload is observational instrumentation
for later analysis; building it never changes selection probabilities, dice
behavior, queue movement, or snooze semantics.

Payload is bounded by the current die pool: only bounded candidate threads in
exact selection order appear, with scalar decision-time fields. Full thread
objects, descriptions, ComicVine payloads, covers, and other heavy metadata are
never serialized here.

Schema version history
----------------------

``context_version = 1``
    Phase-0 baseline shape: algorithm version, die size, pool size, selection
    method, session timezone/daypart when known, the ``selected`` block, and
    the ordered ``candidates`` list. No effort fields.

``context_version = 2`` (current)
    Extends v1 with reading-effort estimates captured at decision time:

    - ``selected.effort``: ``{minutes, band, source, confidence}``.
    - Each entry in ``candidates`` additionally carries ``effort_minutes``,
      ``effort_band``, ``effort_source``, and ``effort_confidence``.

Compatibility contract
----------------------

- Historical events with ``recommendation_context IS NULL`` remain valid.
- v1 payloads without effort fields remain valid readers of every consumer;
  use :func:`selected_effort_from_context` and
  :func:`candidate_efforts_from_context`, which normalize missing or malformed
  effort fields to neutral ``None`` values instead of raising.
- New fields may be added within a version; consumers must ignore unknown keys.
- Any breaking shape change requires bumping :data:`RECOMMENDATION_CONTEXT_VERSION`.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import datetime

from app.services.reading_effort import (
    EFFORT_SOURCE_UNKNOWN,
    EffortEstimate,
    NEUTRAL_EFFORT_ESTIMATE,
)

RECOMMENDATION_CONTEXT_VERSION = 2

LEGACY_ALGORITHM_VERSION = "legacy-unweighted-dice-v1"

SELECTION_METHOD_RANDOM = "random"
SELECTION_METHOD_OVERRIDE = "override"

_CANDIDATE_EFFORT_KEYS = (
    "effort_minutes",
    "effort_band",
    "effort_source",
    "effort_confidence",
)


@dataclass(frozen=True)
class ContextCandidate:
    """Bounded decision-time facts about one candidate thread."""

    thread_id: int
    queue_position: int | None
    last_rating: float | None
    last_activity_at: datetime | None


def _serialize_timestamp(value: datetime | None) -> str | None:
    """Serialize a decision-time timestamp as an ISO-8601 string."""
    if value is None:
        return None
    return value.isoformat()


def _candidate_effort_fields(
    candidate: ContextCandidate,
    efforts_by_thread: Mapping[int, EffortEstimate],
) -> dict[str, float | str | None]:
    """Return the four bounded effort fields recorded for one candidate."""
    estimate = efforts_by_thread.get(candidate.thread_id, NEUTRAL_EFFORT_ESTIMATE)
    return {
        "effort_minutes": estimate.minutes,
        "effort_band": estimate.band,
        "effort_source": estimate.source,
        "effort_confidence": estimate.confidence,
    }


def build_recommendation_context(
    *,
    selection_method: str,
    die_size: int,
    candidates: Sequence[ContextCandidate],
    selected_index: int,
    result: int,
    efforts_by_thread: Mapping[int, EffortEstimate],
    algorithm_version: str = LEGACY_ALGORITHM_VERSION,
    session_timezone: str | None = None,
    local_hour: int | None = None,
    daypart: str | None = None,
) -> dict[str, object]:
    """Build the versioned recommendation-context snapshot for a roll event.

    Args:
        selection_method: How the roll chose its winner (``random`` or
            ``override``).
        die_size: Current die size bounding the candidate pool.
        candidates: Bounded candidate threads in exact selection order.
        selected_index: Zero-based index into ``candidates`` that won.
        result: Recorded die result (1-based for random rolls, 0 for overrides).
        efforts_by_thread: Reading-effort estimates keyed by thread ID;
            candidates absent from the mapping record neutral/null effort.
        algorithm_version: Identifier of the selection algorithm in effect.
        session_timezone: Reader timezone name when known from the reading
            session; ``None`` until #1690 lands.
        local_hour: Local clock hour derived from the persisted timezone when
            safely derivable; ``None`` otherwise.
        daypart: Coarse local daypart label when derivable; ``None`` otherwise.

    Returns:
        JSON-safe context dictionary stamped with
        :data:`RECOMMENDATION_CONTEXT_VERSION`.
    """
    if not candidates:
        raise ValueError("Recommendation context requires at least the selected candidate")
    if not 0 <= selected_index < len(candidates):
        raise ValueError(
            f"Selected index {selected_index} outside candidate pool size {len(candidates)}"
        )

    selected = candidates[selected_index]
    selected_effort = efforts_by_thread.get(selected.thread_id, NEUTRAL_EFFORT_ESTIMATE)

    return {
        "context_version": RECOMMENDATION_CONTEXT_VERSION,
        "algorithm_version": algorithm_version,
        "selection_method": selection_method,
        "die_size": die_size,
        "pool_size": len(candidates),
        "session_timezone": session_timezone,
        "local_hour": local_hour,
        "daypart": daypart,
        "selected": {
            "thread_id": selected.thread_id,
            "candidate_index": selected_index,
            "result": result,
            "queue_position": selected.queue_position,
            "last_rating": selected.last_rating,
            "last_activity_at": _serialize_timestamp(selected.last_activity_at),
            "effort": {
                "minutes": selected_effort.minutes,
                "band": selected_effort.band,
                "source": selected_effort.source,
                "confidence": selected_effort.confidence,
            },
        },
        "candidates": [
            {
                "thread_id": candidate.thread_id,
                "queue_position": candidate.queue_position,
                "last_rating": candidate.last_rating,
                "last_activity_at": _serialize_timestamp(candidate.last_activity_at),
                **_candidate_effort_fields(candidate, efforts_by_thread),
            }
            for candidate in candidates
        ],
    }


def _neutral_effort_payload() -> dict[str, float | str | None]:
    """Return the neutral selected-candidate effort payload."""
    return {
        "minutes": None,
        "band": None,
        "source": EFFORT_SOURCE_UNKNOWN,
        "confidence": None,
    }


def _numeric_or_none(value: object) -> float | None:
    """Return the value as a float when it is a real number, else ``None``."""
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    return float(value)


def selected_effort_from_context(
    context: Mapping[str, object] | None,
) -> dict[str, float | str | None]:
    """Normalize the selected-candidate effort block from any context version.

    Tolerates historical events with no context, v1 payloads without effort
    fields, and malformed payloads, so analysis code never has to special-case
    legacy rows.

    Args:
        context: Stored recommendation-context payload, if any.

    Returns:
        Dict with ``minutes``, ``band``, ``source``, and ``confidence`` keys;
        neutral values when absent or unreadable.
    """
    neutral = _neutral_effort_payload()
    if not isinstance(context, Mapping):
        return neutral

    selected = context.get("selected")
    if not isinstance(selected, Mapping):
        return neutral

    effort = selected.get("effort")
    if not isinstance(effort, Mapping):
        return neutral

    minutes = effort.get("minutes")
    band = effort.get("band")
    source = effort.get("source", EFFORT_SOURCE_UNKNOWN)
    confidence = effort.get("confidence")

    return {
        "minutes": _numeric_or_none(minutes),
        "band": band if isinstance(band, str) else None,
        "source": source if isinstance(source, str) else EFFORT_SOURCE_UNKNOWN,
        "confidence": _numeric_or_none(confidence),
    }


def candidate_efforts_from_context(
    context: Mapping[str, object] | None,
) -> list[dict[str, float | str | int | None]]:
    """Normalize per-candidate effort fields from any context version.

    Args:
        context: Stored recommendation-context payload, if any.

    Returns:
        One dict per stored candidate with ``thread_id`` plus the four
        normalized effort keys. Missing or non-dict candidate lists yield an
        empty list, matching the bounded-pool contract.
    """
    if not isinstance(context, Mapping):
        return []

    raw_candidates = context.get("candidates")
    if not isinstance(raw_candidates, Sequence) or isinstance(raw_candidates, (str, bytes)):
        return []

    normalized: list[dict[str, float | str | int | None]] = []
    for raw in raw_candidates:
        if not isinstance(raw, Mapping):
            continue
        raw_thread_id = raw.get("thread_id")
        thread_id = (
            raw_thread_id
            if isinstance(raw_thread_id, int) and not isinstance(raw_thread_id, bool)
            else None
        )
        effort_values: dict[str, float | str | None] = {
            key: None for key in _CANDIDATE_EFFORT_KEYS
        }
        for key in _CANDIDATE_EFFORT_KEYS:
            value = raw.get(key)
            if isinstance(value, bool):
                continue
            if isinstance(value, (int, float, str)):
                effort_values[key] = value
        normalized.append({"thread_id": thread_id, **effort_values})
    return normalized
