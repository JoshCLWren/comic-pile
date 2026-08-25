"""Ephemeral reading-bandwidth state for active sessions.

Bandwidth state is session-scoped and ephemeral (issue #1706): it lives only on
the :class:`~app.models.session.Session` row, never on Thread or durable
affinity data. This module is the single validation and mutation entry point so
later phases (inference, Snooze corrections, manual mode API, quiz) cannot
persist invalid values.
"""

from __future__ import annotations

import logging
from datetime import UTC, datetime

from sqlalchemy.ext.asyncio import AsyncSession

from app.constants import Bandwidth, BandwidthSource
from app.models import Session
from app.services.bandwidth_inference import (
    BandwidthPrediction,
    HistoricalObservation,
    infer_bandwidth,
)

logger = logging.getLogger(__name__)

BANDWIDTH_CHOICES: frozenset[str] = frozenset(bandwidth.value for bandwidth in Bandwidth)
BANDWIDTH_SOURCE_CHOICES: frozenset[str] = frozenset(source.value for source in BandwidthSource)

# Confidence recorded when inference cannot run or has no comparable history.
# Mirrors the pure service's insufficient-history default so fail-closed state
# is indistinguishable from a genuinely neutral inference.
NEUTRAL_BANDWIDTH_CONFIDENCE: float = 0.1

# Current inference/mode contract version. Later phases that change how
# predicted bandwidth is produced should bump this so stale session state can
# be identified in analytics.
CURRENT_BANDWIDTH_MODE_VERSION = "v1"


def _validate_confidence(bandwidth_confidence: float | None) -> None:
    """Validate a bandwidth confidence value.

    Args:
        bandwidth_confidence: Confidence value to validate, or None.

    Raises:
        ValueError: If the confidence is outside the inclusive 0..1 range.
    """
    if bandwidth_confidence is None:
        return
    if not 0.0 <= bandwidth_confidence <= 1.0:
        raise ValueError(
            f"bandwidth_confidence must be between 0 and 1, got {bandwidth_confidence}"
        )


def validate_bandwidth_state(
    *,
    predicted_bandwidth: str | None = None,
    active_bandwidth: str | None = None,
    bandwidth_confidence: float | None = None,
    bandwidth_source: str | None = None,
) -> None:
    """Validate ephemeral bandwidth field values without mutating anything.

    Invalid enum/state values are rejected safely before any database write.

    Args:
        predicted_bandwidth: Predicted ``light | balanced | deep`` value.
        active_bandwidth: Active ``light | balanced | deep`` value.
        bandwidth_confidence: Confidence between 0 and 1.
        bandwidth_source: One of ``inferred | manual | snooze | quiz``.

    Raises:
        ValueError: If any value is invalid or provenance is missing while
            bandwidth is being recorded.
    """
    for label, value in (
        ("predicted_bandwidth", predicted_bandwidth),
        ("active_bandwidth", active_bandwidth),
    ):
        if value is not None and value not in BANDWIDTH_CHOICES:
            raise ValueError(f"{label} must be one of {sorted(BANDWIDTH_CHOICES)}, got {value!r}")

    if bandwidth_source is not None and bandwidth_source not in BANDWIDTH_SOURCE_CHOICES:
        raise ValueError(
            f"bandwidth_source must be one of {sorted(BANDWIDTH_SOURCE_CHOICES)}, "
            f"got {bandwidth_source!r}"
        )

    if (predicted_bandwidth is not None or active_bandwidth is not None) and (
        bandwidth_source is None
    ):
        raise ValueError("bandwidth_source is required when recording bandwidth state")

    _validate_confidence(bandwidth_confidence)


async def apply_bandwidth_state(
    db: AsyncSession,
    session: Session,
    *,
    predicted_bandwidth: str | None,
    active_bandwidth: str | None,
    bandwidth_source: str | None = None,
    bandwidth_confidence: float | None = None,
    bandwidth_mode_version: str | None = CURRENT_BANDWIDTH_MODE_VERSION,
) -> Session:
    """Validate and persist ephemeral bandwidth state onto a session.

    Both bandwidth slots are independent: callers may set predicted only,
    active only, both, or neither. Passing ``None`` explicitly clears that slot.
    The update timestamp refreshes whenever bandwidth state is applied.

    Args:
        db: Async database session used for the flush.
        session: The target reading session (typically the current one).
        predicted_bandwidth: Predicted bandwidth, or None to clear it.
        active_bandwidth: Active bandwidth, or None to clear it.
        bandwidth_source: Provenance; required when any bandwidth is set.
        bandwidth_confidence: Confidence between 0 and 1.
        bandwidth_mode_version: Mode contract version stamped with the update.

    Returns:
        The same session instance with validated bandwidth state applied.

    Raises:
        ValueError: If validation fails; no database write occurs.
    """
    validate_bandwidth_state(
        predicted_bandwidth=predicted_bandwidth,
        active_bandwidth=active_bandwidth,
        bandwidth_confidence=bandwidth_confidence,
        bandwidth_source=bandwidth_source,
    )

    session.predicted_bandwidth = predicted_bandwidth
    session.active_bandwidth = active_bandwidth
    session.bandwidth_source = bandwidth_source
    session.bandwidth_confidence = bandwidth_confidence
    session.bandwidth_version = bandwidth_mode_version
    session.bandwidth_updated_at = datetime.now(UTC)

    await db.flush()
    return session


def clear_ephemeral_bandwidth(session: Session) -> None:
    """Clear all ephemeral bandwidth state from a session in memory.

    Ending a session terminates its ephemeral bandwidth lifetime, and newly
    started sessions begin without inherited bandwidth (every bandwidth column
    defaults to NULL), so state never leaks across session boundaries.

    Args:
        session: The session whose bandwidth state should be cleared.
    """
    session.predicted_bandwidth = None
    session.active_bandwidth = None
    session.bandwidth_confidence = None
    session.bandwidth_source = None
    session.bandwidth_version = None
    session.bandwidth_updated_at = None


def capture_ephemeral_bandwidth(session: Session) -> dict[str, object]:
    """Capture a snapshot-compatible copy of a session's bandwidth state.

    Mirrors the pre-state dictionaries stored in snapshot ``session_state`` so
    undo flows can restore bandwidth exactly as it existed earlier in the
    session.

    Args:
        session: The session whose bandwidth state should be captured.

    Returns:
        A JSON-serializable dictionary of all bandwidth fields.
    """
    return {
        "predicted_bandwidth": session.predicted_bandwidth,
        "active_bandwidth": session.active_bandwidth,
        "bandwidth_confidence": session.bandwidth_confidence,
        "bandwidth_source": session.bandwidth_source,
        "bandwidth_mode_version": session.bandwidth_version,
        "bandwidth_updated_at": session.bandwidth_updated_at.isoformat()
        if session.bandwidth_updated_at
        else None,
    }


def restore_ephemeral_bandwidth(session: Session, state: dict[str, object]) -> None:
    """Restore bandwidth state previously captured by capture_ephemeral_bandwidth.

    Only applies keys present in ``state`` so older snapshots that predate
    bandwidth tracking leave current values untouched, following the same
    convention as the existing ``session_state`` restore paths.

    Args:
        session: The session receiving restored bandwidth state.
        state: Snapshot ``session_state`` dictionary possibly containing
            bandwidth keys.

    Raises:
        ValueError: If a present bandwidth key carries a value that can never
            satisfy the persisted CHECK constraints.
    """
    if "predicted_bandwidth" in state:
        predicted = state["predicted_bandwidth"]
        predicted_value = str(predicted) if predicted is not None else None
        if predicted_value is not None and predicted_value not in BANDWIDTH_CHOICES:
            raise ValueError(
                f"predicted_bandwidth must be one of {sorted(BANDWIDTH_CHOICES)}, got {predicted!r}"
            )
        session.predicted_bandwidth = predicted_value

    if "active_bandwidth" in state:
        active = state["active_bandwidth"]
        active_value = str(active) if active is not None else None
        if active_value is not None and active_value not in BANDWIDTH_CHOICES:
            raise ValueError(
                f"active_bandwidth must be one of {sorted(BANDWIDTH_CHOICES)}, got {active!r}"
            )
        session.active_bandwidth = active_value

    if "bandwidth_confidence" in state:
        confidence = state["bandwidth_confidence"]
        session.bandwidth_confidence = float(confidence) if confidence is not None else None

    if "bandwidth_source" in state:
        source = state["bandwidth_source"]
        session.bandwidth_source = str(source) if source is not None else None

    if "bandwidth_mode_version" in state:
        version = state["bandwidth_mode_version"]
        session.bandwidth_version = str(version) if version is not None else None

    if "bandwidth_updated_at" in state:
        updated_at = state["bandwidth_updated_at"]
        if updated_at is None:
            session.bandwidth_updated_at = None
        else:
            restored = datetime.fromisoformat(str(updated_at))
            if restored.tzinfo is None:
                restored = restored.replace(tzinfo=UTC)
            session.bandwidth_updated_at = restored


async def _historical_observations(
    db: AsyncSession,
    user_id: int,
) -> list[HistoricalObservation]:
    """Collect comparable historical reading decisions for bandwidth inference.

    Args:
        db: Async database session used for history reads.
        user_id: Reader whose accepted reading history should be collected.

    Returns:
        Observations capturing accepted effort and snooze behavior. The
        Phase 1 effort model (#1700-#1705) will supply real roll-to-rating
        effort observations once merged; until then no comparable
        observations exist, so inference safely yields its neutral balanced
        prediction instead of guessing from weaker signals.
    """
    return []


async def initialize_session_bandwidth(db: AsyncSession, session: Session) -> Session:
    """Initialize inferred bandwidth state once per session lifetime.

    Applies the Phase 2 inference (issue #1708) when a new/current reading
    session first needs mode state. Sessions that already record bandwidth
    state are returned untouched, so manual/future explicit overrides and
    earlier predictions are never overwritten and repeated bootstrap requests
    never recompute. Any inference failure fails closed to the neutral
    balanced prediction so Roll remains usable.

    The write is flushed but not committed; callers own transaction scope.

    Args:
        db: Async database session used for history reads and the flush.
        session: The current reading session to initialize.

    Returns:
        The same session with initialized (or preserved) bandwidth state.
    """
    if session.bandwidth_source is not None:
        return session

    try:
        observations = await _historical_observations(db, session.user_id)
        started_at = session.started_at
        prediction = infer_bandwidth(observations, session_hour=started_at.hour)
    except Exception:
        logger.warning(
            "Bandwidth inference failed for session %s; failing closed to balanced",
            session.id,
            exc_info=True,
        )
        prediction = BandwidthPrediction(
            level=Bandwidth.BALANCED,
            confidence=NEUTRAL_BANDWIDTH_CONFIDENCE,
        )

    predicted_level = prediction.level.value
    return await apply_bandwidth_state(
        db,
        session,
        predicted_bandwidth=predicted_level,
        active_bandwidth=predicted_level,
        bandwidth_source=prediction.source,
        bandwidth_confidence=prediction.confidence,
    )