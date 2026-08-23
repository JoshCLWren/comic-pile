"""Bandwidth inference service for Phase 2 session bandwidth state.

Infers reading bandwidth (light | balanced | deep) from historical reading
decisions. Uses conservative thresholds and fails closed to balanced when
insufficient evidence exists.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Literal

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import Event

logger = logging.getLogger(__name__)

BandwidthLevel = Literal["light", "balanced", "deep"]
BandwidthSource = Literal["inferred", "manual", "snooze", "quiz"]

# Minimum number of comparable historical decisions required for inference
_MIN_EVIDENCE_THRESHOLD = 3

# Confidence thresholds for non-neutral predictions
_HIGH_CONFIDENCE_THRESHOLD = 0.7
_MODERATE_CONFIDENCE_THRESHOLD = 0.5

# Effort band boundaries (minutes) based on observed roll-to-rating latency
_LIGHT_EFFORT_MAX = 12.0
_DEEP_EFFORT_MIN = 18.0

# Snooze rate thresholds by effort band for bandwidth classification
_LIGHT_SNOOZE_MAX_RATE = 0.15
_DEEP_SNOOZE_MIN_RATE = 0.30

# Bandwidth version - increment when inference logic changes
BANDWIDTH_VERSION = 1


@dataclass(frozen=True)
class BandwidthInference:
    """Result of bandwidth inference from historical reading decisions."""

    predicted: BandwidthLevel
    confidence: float
    evidence_count: int
    light_ratio: float
    deep_ratio: float
    snooze_rate_by_band: dict[str, float]

    @property
    def source(self) -> BandwidthSource:
        """Source is always inferred for this service."""
        return "inferred"


def _classify_effort_band(roll_to_rating_minutes: float) -> str:
    """Classify reading effort into bands based on time.

    Args:
        roll_to_rating_minutes: Minutes between roll and rating events.

    Returns:
        One of 'light', 'medium', or 'deep' effort band.
    """
    if roll_to_rating_minutes < _LIGHT_EFFORT_MAX:
        return "light"
    if roll_to_rating_minutes >= _DEEP_EFFORT_MIN:
        return "deep"
    return "medium"


async def infer_bandwidth(
    db: AsyncSession,
    user_id: int,
) -> BandwidthInference:
    """Infer reading bandwidth from historical reading decisions.

    Uses roll-to-rating latency and snooze patterns to predict whether the
    reader tends toward light, balanced, or deep reading sessions.

    Fails closed to balanced with low confidence when evidence is insufficient.

    Args:
        db: Async database session for querying historical events.
        user_id: User whose reading history to analyze.

    Returns:
        BandwidthInference with predicted level, confidence, and evidence data.
    """
    # Query paired roll→rate events to measure reading effort
    roll_events = await db.execute(
        select(
            Event.id.label("roll_id"),
            Event.session_id,
            Event.timestamp.label("roll_timestamp"),
            Event.selected_thread_id,
        )
        .where(Event.session_id.is_not(None))
        .where(Event.type == "roll")
        .where(Event.selected_thread_id.is_not(None))
        .order_by(Event.timestamp.desc())
        .limit(50)
    )
    roll_rows = roll_events.all()

    if not roll_rows:
        return _neutral_result()

    # For each roll, find the subsequent rate event on the same thread
    comparable_decisions: list[dict[str, float | str]] = []

    for roll_row in roll_rows:
        rate_result = await db.execute(
            select(
                Event.timestamp.label("rate_timestamp"),
                Event.rating,
                Event.issues_read,
            )
            .where(Event.session_id == roll_row.session_id)
            .where(Event.type == "rate")
            .where(Event.thread_id == roll_row.selected_thread_id)
            .where(Event.timestamp > roll_row.roll_timestamp)
            .order_by(Event.timestamp.asc())
            .limit(1)
        )
        rate_row = rate_result.first()

        if rate_row is None:
            continue

        roll_ts = roll_row.roll_timestamp
        if roll_ts.tzinfo is None:
            roll_ts = roll_ts.replace(tzinfo=UTC)
        rate_ts = rate_row.rate_timestamp
        if rate_ts.tzinfo is None:
            rate_ts = rate_ts.replace(tzinfo=UTC)

        minutes_to_rate = (rate_ts - roll_ts).total_seconds() / 60.0
        if minutes_to_rate < 0:
            continue

        effort_band = _classify_effort_band(minutes_to_rate)
        comparable_decisions.append(
            {
                "effort_band": effort_band,
                "minutes": minutes_to_rate,
                "rating": rate_row.rating or 0.0,
            }
        )

    if len(comparable_decisions) < _MIN_EVIDENCE_THRESHOLD:
        return _neutral_result(evidence_count=len(comparable_decisions))

    # Count snooze events for effort-band analysis
    snooze_counts = await _count_snoozes_by_effort_band(db, user_id, comparable_decisions)

    return _classify_bandwidth(comparable_decisions, snooze_counts)


async def _count_snoozes_by_effort_band(
    db: AsyncSession,
    user_id: int,
    decisions: list[dict[str, float | str]],
) -> dict[str, int]:
    """Count snooze events that follow rolls by effort band."""
    snooze_counts: dict[str, int] = {"light": 0, "medium": 0, "deep": 0}

    # Query recent snooze events
    snooze_result = await db.execute(
        select(
            Event.session_id,
            Event.thread_id,
            Event.timestamp.label("snooze_timestamp"),
        )
        .where(Event.type == "snooze")
        .where(Event.thread_id.is_not(None))
        .order_by(Event.timestamp.desc())
        .limit(50)
    )
    snooze_rows = snooze_result.all()

    # Build a set of (session_id, thread_id) pairs that were snoozed
    snoozed_pairs = {(row.session_id, row.thread_id) for row in snooze_rows}

    for decision in decisions:
        effort = decision["effort_band"]
        if effort in snooze_counts:
            snooze_counts[effort] += 1

    return snooze_counts


def _classify_bandwidth(
    decisions: list[dict[str, float | str]],
    snooze_counts: dict[str, int],
) -> BandwidthInference:
    """Classify bandwidth from comparable decisions and snooze patterns.

    Args:
        decisions: List of comparable roll→rate decisions with effort data.
        snooze_counts: Snooze counts by effort band.

    Returns:
        BandwidthInference with predicted level and confidence.
    """
    total = len(decisions)
    if total == 0:
        return _neutral_result()

    light_count = sum(1 for d in decisions if d["effort_band"] == "light")
    deep_count = sum(1 for d in decisions if d["effort_band"] == "deep")

    light_ratio = light_count / total
    deep_ratio = deep_count / total

    # Calculate snooze rates by band
    snooze_rates: dict[str, float] = {}
    for band in ("light", "medium", "deep"):
        band_decisions = [d for d in decisions if d["effort_band"] == band]
        band_count = len(band_decisions)
        if band_count > 0:
            snooze_rates[band] = snooze_counts.get(band, 0) / band_count
        else:
            snooze_rates[band] = 0.0

    # Classification logic:
    # - Light: predominantly light effort AND low snooze rate in light band
    # - Deep: predominantly deep effort AND high snooze rate in deep band
    # - Balanced: everything else

    if (
        light_ratio >= 0.6
        and snooze_rates.get("light", 0.0) <= _LIGHT_SNOOZE_MAX_RATE
    ):
        confidence = min(1.0, light_ratio * (1.0 - snooze_rates.get("light", 0.0)))
        return BandwidthInference(
            predicted="light",
            confidence=round(confidence, 3),
            evidence_count=total,
            light_ratio=round(light_ratio, 3),
            deep_ratio=round(deep_ratio, 3),
            snooze_rate_by_band={k: round(v, 3) for k, v in snooze_rates.items()},
        )

    if (
        deep_ratio >= 0.5
        and snooze_rates.get("deep", 0.0) >= _DEEP_SNOOZE_MIN_RATE
    ):
        confidence = min(1.0, deep_ratio * snooze_rates.get("deep", 1.0))
        return BandwidthInference(
            predicted="deep",
            confidence=round(confidence, 3),
            evidence_count=total,
            light_ratio=round(light_ratio, 3),
            deep_ratio=round(deep_ratio, 3),
            snooze_rate_by_band={k: round(v, 3) for k, v in snooze_rates.items()},
        )

    # Default to balanced with moderate confidence
    balance_ratio = 1.0 - abs(light_ratio - deep_ratio)
    confidence = balance_ratio * 0.6
    return BandwidthInference(
        predicted="balanced",
        confidence=round(confidence, 3),
        evidence_count=total,
        light_ratio=round(light_ratio, 3),
        deep_ratio=round(deep_ratio, 3),
        snooze_rate_by_band={k: round(v, 3) for k, v in snooze_rates.items()},
    )


def _neutral_result(evidence_count: int = 0) -> BandwidthInference:
    """Return neutral balanced result for insufficient evidence."""
    return BandwidthInference(
        predicted="balanced",
        confidence=0.0,
        evidence_count=evidence_count,
        light_ratio=0.0,
        deep_ratio=0.0,
        snooze_rate_by_band={"light": 0.0, "medium": 0.0, "deep": 0.0},
    )
