"""Read-only recommendation-quality diagnostics service.

This module derives recommendation-quality metrics from persisted decision
history (sessions and events) without mutating any state and without adding
work to the normal Roll bootstrap path. All queries are bounded by an explicit
user and time range.

Metric definitions (numerator / denominator / edge cases)
--------------------------------------------------------
first_roll_adoption_rate
    For each session in range, take the first ``roll`` event. It is "adopted"
    when the session contains a ``rate`` event for that same thread. Numerator =
    adopted first rolls; denominator = sessions with at least one roll. Sessions
    with no roll count as 0/0 and are excluded.

snoozes_per_completed_read
    total ``snooze`` events / total ``rate`` events in range. 0.0 when no
    ``rate`` events exist.

max/avg_consecutive_snoozes_before_acceptance
    Within a session, track the longest run of consecutive ``snooze`` events
    that occurs before the first ``rate`` (acceptance), resetting the run at
    each new ``roll``. Report the max across sessions and the mean across
    sessions that had at least one such run. 0 when none.

avg_time_to_acceptance_seconds
    For adopted first rolls, the delta between the accepting ``rate`` timestamp
    and the owning session ``started_at``. Mean across those sessions; None when
    no adopted first roll exists.

mode_corrections
    Count of roll events whose ``selection_method`` is an explicit launch-mode
    override (``manual`` or ``override``). Quiz-mode corrections are not yet
    instrumented and are excluded.

rating_average / rating_distribution
    Mean and integer-bucket histogram of ``rate.rating`` values in range.
    None / empty when no ``rate`` events exist.

effort_band_outcomes
    Rolls grouped by ``die`` size. A roll is "accepted" when its thread appears
    in any ``rate`` event in range; "snoozed" when it appears in any ``snooze``
    event in range. Bands: low (die <= 6), medium (7-10), high (>= 12).

groups_by_control_mode
    Rolls grouped by a distinguishable control/intent class derived from
    ``selection_method``: ``contextual_auto`` (random), ``explicit_correction``
    (manual/override), ``blocked_recovery`` (dependency_recovery), and
    ``legacy`` (no selection_method). This makes algorithm control mode
    distinguishable from the available history even before per-decision
    algorithm versioning lands (issue #1767).

coverage
    Labels legacy events (no ``selection_method``) separately from instrumented
    events so partial/legacy coverage is never silently mixed.
"""

from __future__ import annotations

from collections import defaultdict
from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING

from sqlalchemy import select

from app.config import get_recommendation_settings
from app.models import Event, Session
from app.schemas.recommendation_diagnostics import (
    ControlModeGroup,
    CoverageInfo,
    EffortBandOutcome,
    RecommendationDiagnosticsResponse,
)

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession

MAX_DIAGNOSTICS_RANGE_DAYS = 365
DEFAULT_DIAGNOSTICS_RANGE_DAYS = 30
EXPLICIT_CORRECTION_METHODS = frozenset({"manual", "override"})


def _effort_band(die: int | None) -> str:
    """Map a die size to a coarse effort band label."""
    if die is None:
        return "low"
    if die <= 6:
        return "low"
    if die <= 10:
        return "medium"
    return "high"


def _control_mode_for(selection_method: str | None) -> str:
    """Classify a roll event into a distinguishable control/intent mode."""
    if selection_method is None:
        return "legacy"
    if selection_method == "legacy_forced":
        return "legacy_forced"
    if selection_method == "random":
        return "contextual_auto"
    if selection_method in EXPLICIT_CORRECTION_METHODS:
        return "explicit_correction"
    if selection_method == "dependency_recovery":
        return "blocked_recovery"
    return "contextual_auto"


def _safe_rate(value: float) -> float:
    """Clamp a ratio into the valid [0, 1] range for schema compliance."""
    if value < 0.0:
        return 0.0
    if value > 1.0:
        return 1.0
    return value


async def compute_recommendation_diagnostics(
    db: AsyncSession,
    *,
    user_id: int,
    range_start: datetime,
    range_end: datetime,
) -> RecommendationDiagnosticsResponse:
    """Compute a bounded recommendation-quality diagnostics summary.

    Args:
        db: Async database session (read-only use).
        user_id: Owner of the summarized sessions and events.
        range_start: Inclusive lower bound for the time range.
        range_end: Exclusive upper bound for the time range.

    Returns:
        A :class:`RecommendationDiagnosticsResponse` describing the metrics,
        effort-band outcomes, control-mode groups, and coverage for the range.
    """
    recommendation_settings = get_recommendation_settings()

    result = await db.execute(
        select(Event, Session.started_at)
        .join(Session, Event.session_id == Session.id)
        .where(Session.user_id == user_id)
        .where(Event.timestamp >= range_start)
        .where(Event.timestamp < range_end)
        .order_by(Session.id, Event.timestamp)
    )
    rows = result.all()

    sessions: dict[int, dict] = {}
    range_rated_threads: set[int] = set()
    range_snoozed_threads: set[int] = set()
    total_rolls = 0
    total_rates = 0
    total_snoozes = 0
    legacy_event_count = 0
    instrumented_event_count = 0
    rating_values: list[float] = []
    mode_corrections = 0

    by_die: dict[int, dict[str, int]] = defaultdict(
        lambda: {"rolls": 0, "accepted": 0, "snoozed": 0}
    )
    by_mode: dict[str, dict[str, int]] = defaultdict(
        lambda: {"rolls": 0, "accepted": 0, "snoozed": 0}
    )
    roll_records: list[Event] = []
    time_to_acceptance_deltas: list[float] = []
    session_max_snooze_runs: list[int] = []
    first_roll_adopted = 0
    first_roll_sessions = 0

    for event, session_started_at in rows:
        if event.session_id not in sessions:
            sessions[event.session_id] = {
                "started_at": session_started_at,
                "events": [],
            }
        sessions[event.session_id]["events"].append(event)

        if event.selection_method is None:
            legacy_event_count += 1
        else:
            instrumented_event_count += 1

        if event.type == "roll":
            total_rolls += 1
            if event.selection_method in EXPLICIT_CORRECTION_METHODS:
                mode_corrections += 1
            roll_records.append(event)
        elif event.type == "rate":
            total_rates += 1
            if event.thread_id is not None:
                range_rated_threads.add(event.thread_id)
            if event.rating is not None:
                rating_values.append(float(event.rating))
        elif event.type == "snooze":
            total_snoozes += 1
            if event.thread_id is not None:
                range_snoozed_threads.add(event.thread_id)

    # Acceptance/snooze per roll is range-scoped and must be computed only after
    # the full rated/snoozed thread sets are known, otherwise ordering within a
    # session would cause undercounting.
    for event in roll_records:
        selected = event.selected_thread_id
        die_key = event.die if event.die is not None else 6
        accepted = selected is not None and selected in range_rated_threads
        snoozed = selected is not None and selected in range_snoozed_threads
        bucket = by_die[die_key]
        bucket["rolls"] += 1
        bucket["accepted"] += 1 if accepted else 0
        bucket["snoozed"] += 1 if snoozed else 0
        control_mode = _control_mode_for(event.selection_method)
        mode_bucket = by_mode[control_mode]
        mode_bucket["rolls"] += 1
        mode_bucket["accepted"] += 1 if accepted else 0
        mode_bucket["snoozed"] += 1 if snoozed else 0

    for session in sessions.values():
        combined = sorted(
            session["events"],
            key=lambda ev: (ev.timestamp or datetime.min.replace(tzinfo=UTC)),
        )

        first_roll = next((ev for ev in combined if ev.type == "roll"), None)
        if first_roll is None:
            continue
        first_roll_sessions += 1
        first_thread = first_roll.selected_thread_id

        accepted_at: datetime | None = None
        for ev in combined:
            if ev.type == "rate" and ev.thread_id == first_thread:
                accepted_at = ev.timestamp
                break
        if accepted_at is not None:
            first_roll_adopted += 1
            if session["started_at"] is not None:
                delta = (accepted_at - session["started_at"]).total_seconds()
                time_to_acceptance_deltas.append(delta)

        run = 0
        session_max_run = 0
        accepted = False
        for ev in combined:
            if accepted:
                break
            if ev.type == "roll":
                run = 0
            elif ev.type == "snooze":
                run += 1
                session_max_run = max(session_max_run, run)
            elif ev.type == "rate":
                accepted = True
        if session_max_run > 0:
            session_max_snooze_runs.append(session_max_run)

    first_roll_adoption_rate = (
        _safe_rate(first_roll_adopted / first_roll_sessions) if first_roll_sessions else 0.0
    )
    snoozes_per_completed_read = total_snoozes / total_rates if total_rates else 0.0
    max_consecutive_snoozes = max(session_max_snooze_runs) if session_max_snooze_runs else 0
    avg_consecutive_snoozes = (
        sum(session_max_snooze_runs) / len(session_max_snooze_runs)
        if session_max_snooze_runs
        else 0.0
    )
    avg_time_to_acceptance = (
        sum(time_to_acceptance_deltas) / len(time_to_acceptance_deltas)
        if time_to_acceptance_deltas
        else None
    )
    rating_average = sum(rating_values) / len(rating_values) if rating_values else None
    rating_distribution: dict[str, int] = {}
    for value in rating_values:
        bucket = f"{value:.1f}"
        rating_distribution[bucket] = rating_distribution.get(bucket, 0) + 1

    effort_band_outcomes: list[EffortBandOutcome] = []
    for die in sorted(by_die):
        bucket = by_die[die]
        rolls = bucket["rolls"]
        effort_band_outcomes.append(
            EffortBandOutcome(
                die=die,
                band=_effort_band(die),
                rolls=rolls,
                accepted=bucket["accepted"],
                snoozed=bucket["snoozed"],
                acceptance_rate=_safe_rate(bucket["accepted"] / rolls) if rolls else 0.0,
                snooze_rate=_safe_rate(bucket["snoozed"] / rolls) if rolls else 0.0,
            )
        )

    groups_by_control_mode: list[ControlModeGroup] = []
    for control_mode in sorted(by_mode):
        bucket = by_mode[control_mode]
        rolls = bucket["rolls"]
        if control_mode == "legacy":
            algorithm_version = "legacy-unknown"
        elif control_mode == "legacy_forced":
            # Forced legacy kill-switch: still versioned but distinguishable bucket
            algorithm_version = f"{recommendation_settings.algorithm_version}:legacy_forced"
        else:
            algorithm_version = recommendation_settings.algorithm_version
        groups_by_control_mode.append(
            ControlModeGroup(
                control_mode=control_mode,
                algorithm_version=algorithm_version,
                rolls=rolls,
                accepted_rolls=bucket["accepted"],
                snoozed_rolls=bucket["snoozed"],
                acceptance_rate=_safe_rate(bucket["accepted"] / rolls) if rolls else 0.0,
                snooze_rate=_safe_rate(bucket["snoozed"] / rolls) if rolls else 0.0,
            )
        )

    partial_coverage = legacy_event_count > 0
    coverage_note = (
        "Some events lack selection_method (pre-instrumentation) and are labeled as "
        "legacy; instrumented metrics attribute them to the active algorithm version."
        if partial_coverage
        else "All events in range carry full selection context."
    )

    return RecommendationDiagnosticsResponse(
        user_id=user_id,
        range_start=range_start,
        range_end=range_end,
        active_algorithm_version=recommendation_settings.algorithm_version,
        active_control_mode=recommendation_settings.control_mode,
        total_sessions=len(sessions),
        total_rolls=total_rolls,
        total_rates=total_rates,
        total_snoozes=total_snoozes,
        first_roll_adoption_rate=first_roll_adoption_rate,
        snoozes_per_completed_read=snoozes_per_completed_read,
        max_consecutive_snoozes_before_acceptance=max_consecutive_snoozes,
        avg_consecutive_snoozes_before_acceptance=avg_consecutive_snoozes,
        avg_time_to_acceptance_seconds=avg_time_to_acceptance,
        mode_corrections=mode_corrections,
        rating_average=rating_average,
        rating_distribution=rating_distribution,
        effort_band_outcomes=effort_band_outcomes,
        groups_by_control_mode=groups_by_control_mode,
        coverage=CoverageInfo(
            instrumented_event_count=instrumented_event_count,
            legacy_event_count=legacy_event_count,
            partial_coverage=partial_coverage,
            note=coverage_note,
        ),
    )


def resolve_diagnostics_range(
    range_start: datetime | None,
    range_end: datetime | None,
) -> tuple[datetime, datetime]:
    """Resolve a bounded diagnostics time range with sane defaults and caps.

    Args:
        range_start: Optional inclusive lower bound.
        range_end: Optional exclusive upper bound.

    Returns:
        A (range_start, range_end) tuple with defaults applied and the span
        capped to :data:`MAX_DIAGNOSTICS_RANGE_DAYS`.
    """
    now = datetime.now(UTC)
    if range_end is None:
        range_end = now
    elif range_end > now:
        range_end = now
    if range_start is None:
        range_start = range_end - timedelta(days=DEFAULT_DIAGNOSTICS_RANGE_DAYS)
    span_days = (range_end - range_start).days
    if span_days > MAX_DIAGNOSTICS_RANGE_DAYS:
        range_start = range_end - timedelta(days=MAX_DIAGNOSTICS_RANGE_DAYS)
    if range_start > range_end:
        range_start = range_end
    return range_start, range_end
