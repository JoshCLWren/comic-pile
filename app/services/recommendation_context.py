"""Bounded candidate-pool snapshots for versioned recommendation contexts.

``app/services/reading_effort.py`` owns the recommendation-context payload
contract and builds the selected-candidate snapshot. This module adds the
bounded candidate-pool projection introduced by ``context_version = 2``
(issue #1704) plus tolerant readers that normalize effort fields from any
historical payload shape.

The candidate list mirrors the current die pool in exact selection order and
carries only scalar decision-time fields. Full thread objects, descriptions,
ComicVine payloads, covers, and other heavy metadata are never serialized.

Compatibility contract
----------------------

- Historical events with ``recommendation_context IS NULL`` remain valid.
- v1 payloads without a ``candidates`` list remain valid; readers normalize
  missing or malformed effort fields to neutral values instead of raising.
- New fields may be added within a version; consumers must ignore unknown keys.
- Any breaking shape change requires bumping
  :data:`~app.services.reading_effort.RECOMMENDATION_CONTEXT_VERSION`.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from datetime import datetime

from app.models import Thread
from app.services.reading_effort import (
    RECOMMENDATION_CONTEXT_VERSION,
    EffortEstimate,
    neutral_estimate,
)

EFFORT_SOURCE_UNKNOWN = "unknown"

_CANDIDATE_EFFORT_KEYS = (
    "effort_minutes",
    "effort_band",
    "effort_source",
    "effort_confidence",
    "effort_sample_count",
)


def _serialize_timestamp(value: datetime | None) -> str | None:
    """Serialize a decision-time timestamp as an ISO-8601 string.

    Args:
        value: Timestamp to serialize, if any.

    Returns:
        ISO-8601 string, or ``None`` when the timestamp is missing.
    """
    if value is None:
        return None
    return value.isoformat()


def attach_candidate_pool(
    context: Mapping[str, object],
    *,
    threads: Sequence[Thread],
    efforts_by_thread: Mapping[int, EffortEstimate],
) -> dict[str, object]:
    """Extend a selected-candidate snapshot with the bounded die pool.

    Purely observational: the input mapping is not mutated, selection
    probabilities are untouched, and every field is JSON-safe by construction.

    Args:
        context: Snapshot produced by
            :func:`~app.services.reading_effort.build_recommendation_context`.
        threads: Bounded candidate threads in exact selection order. Must
            include the selected thread so per-candidate effort covers it.
        efforts_by_thread: Estimates keyed by thread ID; absent entries
            record neutral effort.

    Returns:
        A new dict stamped with the current
        :data:`~app.services.reading_effort.RECOMMENDATION_CONTEXT_VERSION`
        and an ordered ``candidates`` list carrying scalar decision-time
        fields plus the five effort fields per candidate.
    """
    neutral = neutral_estimate()
    candidates: list[dict[str, object]] = []
    for thread in threads:
        estimate = efforts_by_thread.get(thread.id, neutral)
        candidates.append(
            {
                "thread_id": thread.id,
                "queue_position": thread.queue_position,
                "last_rating": thread.last_rating,
                "last_activity_at": _serialize_timestamp(thread.last_activity_at),
                "effort_minutes": (
                    round(estimate.minutes, 2) if estimate.minutes is not None else None
                ),
                "effort_band": estimate.band,
                "effort_source": estimate.source.value,
                "effort_confidence": round(estimate.confidence, 3),
                "effort_sample_count": estimate.sample_count,
            }
        )
    enriched = dict(context)
    enriched["context_version"] = RECOMMENDATION_CONTEXT_VERSION
    enriched["candidates"] = candidates
    return enriched


def _numeric_or_none(value: object) -> float | None:
    """Coerce a stored JSON value to a float, or ``None`` when not numeric.

    Args:
        value: Raw value from a persisted payload.

    Returns:
        The value as a float; ``None`` for missing, boolean, or non-numeric
        values.
    """
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    return float(value)


def _int_or_none(value: object) -> int | None:
    """Coerce a stored JSON value to an int, or ``None`` when not integral.

    Args:
        value: Raw value from a persisted payload.

    Returns:
        The value as an int; ``None`` for missing, boolean, or non-integral
        values.
    """
    if isinstance(value, bool) or not isinstance(value, int):
        return None
    return value


def selected_effort_from_context(
    context: Mapping[str, object] | None,
) -> dict[str, float | str | None]:
    """Normalize the selected-candidate effort block from any context version.

    Reads the flat ``selected_candidate`` effort fields used by every current
    version and tolerates historical events with no context, malformed
    payloads, or missing fields, so analysis code never special-cases legacy
    rows.

    Args:
        context: Stored recommendation-context payload, if any.

    Returns:
        Dict with ``minutes``, ``band``, ``source``, and ``confidence`` keys;
        neutral values when absent or unreadable.
    """
    if not isinstance(context, Mapping):
        return {"minutes": None, "band": None, "source": EFFORT_SOURCE_UNKNOWN, "confidence": None}

    selected = context.get("selected_candidate")
    if not isinstance(selected, Mapping):
        selected = context.get("selected")
    if not isinstance(selected, Mapping):
        return {"minutes": None, "band": None, "source": EFFORT_SOURCE_UNKNOWN, "confidence": None}

    nested = selected.get("effort")
    if isinstance(nested, Mapping):
        selected = nested
        minutes_key, band_key, source_key, confidence_key = (
            "minutes",
            "band",
            "source",
            "confidence",
        )
    else:
        minutes_key, band_key, source_key, confidence_key = (
            "effort_minutes",
            "effort_band",
            "effort_source",
            "effort_confidence",
        )

    minutes = selected.get(minutes_key)
    band = selected.get(band_key)
    source = selected.get(source_key, EFFORT_SOURCE_UNKNOWN)
    confidence = selected.get(confidence_key)

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
        One dict per stored candidate with ``thread_id`` plus the five
        normalized effort keys. Missing or non-list candidate entries yield an
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
        effort_values: dict[str, float | str | int | None] = {
            key: None for key in _CANDIDATE_EFFORT_KEYS
        }
        for key in _CANDIDATE_EFFORT_KEYS:
            value = raw.get(key)
            if isinstance(value, bool):
                continue
            if isinstance(value, (int, float, str)):
                effort_values[key] = value
        normalized.append({"thread_id": _int_or_none(raw.get("thread_id")), **effort_values})
    return normalized
