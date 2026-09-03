"""Read-only recommendation-quality metrics derived from decision history.

This service is the canonical definition of the Phase 9 recommendation-quality
metrics (issue #1766). Every metric below states its numerator, denominator,
and edge-case handling so later reports cannot drift in meaning. The service
never writes: callers only run ``SELECT`` queries and pure projections.

Decision model
--------------

A *decision attempt* is one ``roll`` event plus the first following outcome
event in the same session, where outcomes are:

- ``rate`` -> accepted (the rolled comic was read and rated),
- ``snooze`` -> snoozed (explicit "not now" correction),
- ``rolled_but_skipped`` -> skipped (rolled but abandoned without snoozing).

Attempts are reconstructed from linked session events ordered by
``(timestamp, id)``; mutable current queue state is never consulted.

A new ``roll`` while an attempt is still open closes it as *superseded* (an
unresolved attempt). Outcome events with no open roll in their session are
*unattributed*: they are counted honestly in raw-volume metrics but excluded
from per-decision metrics that require roll linkage.

Metric definitions
------------------

first_roll_acceptance
    Numerator: sessions whose first decision attempt resolved as accepted.
    Denominator: sessions whose first decision attempt resolved at all
    (accepted, snoozed, or skipped). Sessions whose first attempt was
    superseded by another roll are excluded from both and reported under
    coverage as unresolved attempts.

snoozes_per_completed_read
    Numerator: all ``snooze`` outcome events in range (attributed or not).
    Denominator: all ``rate`` events in range (each rate is a completed
    read). Value is ``None`` when there are zero completed reads; zero reads
    is undefined for a ratio, not zero.

consecutive_snoozes_before_acceptance
    Unit: session. Count of consecutive snoozed attempts immediately before
    the first accepted attempt in that session. Sessions that reach an
    acceptance contribute exactly one count; sessions without an acceptance
    are censored and reported as ``never_accepted_sessions``.

time_to_acceptance_seconds
    Unit: session. Duration from ``session.started_at`` to the timestamp of
    the first accepted attempt's ``rate`` event. Samples missing either
    timestamp are excluded; negative durations (clock skew or imports) are
    excluded and counted separately.

mode_corrections
    Numerator: explicit mode-correction events in range (event types
    ``mode_correction`` / ``session_mode_change``). No producers exist before
    the Phase 5/6 mode APIs land, so the honest value today is zero.

launch_mode_prediction
    A *recorded launch* is a session whose opening roll context records a
    predicted bandwidth/intent. Accuracy numerator: recorded launches with no
    explicit correction event later in the same session. Denominator:
    recorded launches. ``None`` when no launches record a prediction.

acceptance/snooze by effort band and mode
    Unit: resolved decision attempt. Attempts bucket by the bandwidth
    ("effort band") and intent recorded on the originating roll context;
    attempts without that context fall into explicit ``unknown`` buckets
    instead of being silently dropped. Rates use acceptances (or snoozes)
    over resolved attempts per bucket.

rating_distribution
    Unit: ``rate`` event in range with a non-null rating (attributed or not).
    Distribution buckets round ratings to half stars; unrated reads are
    counted separately.

algorithm/context version
    Every attempt carries the algorithm version recorded at decision time.
    Events without versioned context are bucketed as ``"legacy"`` so future
    versions can be compared against the historical baseline.

Legacy-context policy
---------------------

Optional decision-time context (algorithm version, bandwidth, intent, launch
prediction) is read defensively from well-known attributes on the roll event
or its ``recommendation_context`` mapping. Events lacking full context are
included only in metrics computable without it and always land in explicit
``legacy``/``unknown`` buckets. This keeps pre-instrumentation history useful
without fabricating values.
"""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Callable, Iterable, Mapping, Sequence
from dataclasses import dataclass, replace
import math
from datetime import UTC, datetime
from typing import Literal

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import Event
from app.models import Session as SessionModel

LEGACY_ALGORITHM_VERSION = "legacy"
UNKNOWN_BUCKET = "unknown"

OUTCOME_ACCEPTED = "accepted"
OUTCOME_SNOOZED = "snoozed"
OUTCOME_SKIPPED = "skipped"
OUTCOME_OPEN = "open"
UNRESOLVED_SUPERSEDED = "superseded"

_OUTCOME_BY_EVENT_TYPE = {
    "rate": OUTCOME_ACCEPTED,
    "snooze": OUTCOME_SNOOZED,
    "rolled_but_skipped": OUTCOME_SKIPPED,
}

MODE_CORRECTION_EVENT_TYPES = frozenset({"mode_correction", "session_mode_change"})

DEFAULT_WINDOW_DAYS = 30
MAX_WINDOW_DAYS = 366

PeriodGrouping = Literal["none", "day", "week", "month"]

_MISSING = object()
_EPOCH = datetime(1970, 1, 1, tzinfo=UTC)


def _as_utc(value: datetime) -> datetime:
    """Normalize a datetime to timezone-aware UTC.

    Args:
        value: Datetime that may be naive or aware.

    Returns:
        Timezone-aware UTC datetime; naive inputs are assumed to be UTC.
    """
    if value.tzinfo is None:
        return value.replace(tzinfo=UTC)
    return value.astimezone(UTC)


def _event_order_key(event: Event) -> tuple[int, datetime, int]:
    """Return a stable ordering key for events within a session.

    Args:
        event: Event to key.

    Returns:
        Tuple of (has-timestamp flag, normalized timestamp, event id). Events
        without timestamps sort after timestamped ones; equal timestamps fall
        back to event id order.
    """
    if event.timestamp is None:
        return (1, _EPOCH, event.id if event.id is not None else 0)
    return (0, _as_utc(event.timestamp), event.id if event.id is not None else 0)


def _optional_attribute(event: Event, name: str) -> object:
    """Read an optional future attribute defensively.

    Later instrumentation phases attach decision-time context columns to
    events. Reading them via ``getattr`` keeps this service usable against
    today's schema while automatically adopting richer context when the
    columns exist.

    Args:
        event: Event possibly carrying the attribute.
        name: Attribute name to look up.

    Returns:
        The attribute value, or ``None`` when absent.
    """
    value = getattr(event, name, _MISSING)
    return None if value is _MISSING else value


def _context_value(context: Mapping[str, object] | None, names: tuple[str, ...]) -> object:
    """Read the first present key from a decision-time context mapping.

    Args:
        context: Mapping snapshot stored with a roll event, if any.
        names: Candidate keys in priority order.

    Returns:
        The first non-null value found, or ``None``.
    """
    if not context:
        return None
    for name in names:
        if name in context and context[name] is not None:
            return context[name]
    return None


def _extract_control_mode(event: Event) -> str | None:
    """Extract the control mode recorded at roll time.

    Args:
        event: Roll event.

    Returns:
        ``contextual`` or ``legacy`` when recorded, or ``None`` for legacy rows.
    """
    raw = _optional_attribute(event, "control_mode")
    if raw is None:
        for attr in ("recommendation_context", "rolling_recommendation_context"):
            ctx = _optional_attribute(event, attr)
            if isinstance(ctx, Mapping):
                raw = _context_value(ctx, ("control_mode",))
                if isinstance(raw, str) and raw.strip():
                    break
                raw = None
    if isinstance(raw, str) and raw.strip():
        return raw.strip()
    return None


def _extract_algorithm_version(event: Event) -> str:
    """Extract the algorithm version recorded at roll time.

    Args:
        event: Roll event.

    Returns:
        Recorded version string, or ``LEGACY_ALGORITHM_VERSION`` when the
        event predates version instrumentation. When the canonical version is
        present but the control mode is ``legacy`` (kill-switch forced), the
        returned bucket is suffixed as ``<version>:legacy_forced`` so forced
        legacy runs remain distinguishable in version-grouped metrics.
    """
    raw = _optional_attribute(event, "algorithm_version")
    if raw is None:
        for attr in ("recommendation_context", "rolling_recommendation_context"):
            ctx = _optional_attribute(event, attr)
            if isinstance(ctx, Mapping):
                candidate = _context_value(
                    ctx if isinstance(ctx, Mapping) else None,
                    ("algorithm_version", "context_version"),
                )
                if isinstance(candidate, str) and candidate.strip():
                    raw = candidate
                    break
    if isinstance(raw, str) and raw.strip():
        base = raw.strip()
    else:
        base = LEGACY_ALGORITHM_VERSION
    control = _extract_control_mode(event)
    # Legacy context already buckets as LEGACY; only suffix the canonical version
    # when the kill switch forced an otherwise-contextual version into legacy mode.
    if control == "legacy" and base != LEGACY_ALGORITHM_VERSION:
        return f"{base}:legacy_forced"
    return base


def _extract_bandwidth(event: Event) -> str | None:
    """Extract the effort band recorded at roll time.

    Args:
        event: Roll event.

    Returns:
        Bandwidth label such as ``light``/``balanced``/``deep``, or ``None``
        when the roll predates bandwidth instrumentation.
    """
    raw = _optional_attribute(event, "bandwidth")
    if raw is None:
        context = _optional_attribute(event, "recommendation_context")
        raw = _context_value(
            context if isinstance(context, Mapping) else None,
            ("bandwidth", "effort_band"),
        )
    if isinstance(raw, str) and raw.strip():
        return raw
    return None


def _extract_intent(event: Event) -> str | None:
    """Extract the reading intent recorded at roll time.

    Args:
        event: Roll event.

    Returns:
        Intent label such as ``momentum``/``familiar``/``explore``, or
        ``None`` when the roll predates intent instrumentation.
    """
    raw = _optional_attribute(event, "intent")
    if raw is None:
        context = _optional_attribute(event, "recommendation_context")
        raw = _context_value(context if isinstance(context, Mapping) else None, ("intent",))
    if isinstance(raw, str) and raw.strip():
        return raw
    return None


def _records_launch_prediction(event: Event) -> bool:
    """Report whether a roll event records a predicted launch mode.

    Args:
        event: Roll event opening a session.

    Returns:
        True when a predicted bandwidth or intent is present in the
        decision-time context.
    """
    if _extract_bandwidth(event) is not None or _extract_intent(event) is not None:
        return True
    context = _optional_attribute(event, "recommendation_context")
    if isinstance(context, Mapping):
        return _context_value(
            context, ("predicted_bandwidth", "predicted_intent")
        ) is not None
    return False


@dataclass(frozen=True, slots=True)
class DecisionAttempt:
    """One roll-plus-outcome decision reconstructed from linked events.

    Attributes:
        session_id: Owning session id.
        roll_event_id: Id of the opening roll event.
        rolled_at: Roll timestamp (may be None for legacy rows).
        thread_id: Selected thread id when recorded.
        outcome: ``accepted``, ``snoozed``, ``skipped``, or ``superseded``
            for attempts closed by another roll.
        outcome_event_id: Id of the closing outcome event when resolved.
        outcome_at: Timestamp of the closing outcome event when resolved.
        rating: Rating captured by an accepting rate event.
        algorithm_version: Decision-time algorithm version label.
        bandwidth: Decision-time effort-band label, if recorded.
        intent: Decision-time intent label, if recorded.
        records_launch_prediction: Whether the roll recorded a predicted
            launch mode.
    """

    session_id: int | None
    roll_event_id: int
    rolled_at: datetime | None
    thread_id: int | None
    outcome: str
    outcome_event_id: int | None = None
    outcome_at: datetime | None = None
    rating: float | None = None
    algorithm_version: str = LEGACY_ALGORITHM_VERSION
    bandwidth: str | None = None
    intent: str | None = None
    records_launch_prediction: bool = False

    @property
    def is_resolved(self) -> bool:
        """Whether this attempt closed with a definite outcome."""
        return self.outcome in {OUTCOME_ACCEPTED, OUTCOME_SNOOZED, OUTCOME_SKIPPED}


@dataclass(frozen=True, slots=True)
class UnattributedOutcomes:
    """Outcome events that could not be linked to any in-session roll.

    Attributes:
        rates: Accepted-read events with no preceding open roll.
        snoozes: Snooze events with no preceding open roll.
        skips: Skipped-roll events with no preceding open roll.
    """

    rates: int = 0
    snoozes: int = 0
    skips: int = 0

    @property
    def total(self) -> int:
        """Total unattributed outcome events."""
        return self.rates + self.snoozes + self.skips


@dataclass(frozen=True, slots=True)
class SessionDecisions:
    """Ordered decision history for one reading session.

    Attributes:
        session_id: Session id (``None`` only for orphaned legacy events).
        started_at: Session start timestamp when known.
        attempts: Decision attempts in event order.
        mode_corrections: Explicit mode-correction events in order.
    """

    session_id: int | None
    started_at: datetime | None
    attempts: tuple[DecisionAttempt, ...] = ()
    mode_corrections: tuple[Event, ...] = ()

    @property
    def resolved_attempts(self) -> tuple[DecisionAttempt, ...]:
        """Attempts that closed with a definite outcome."""
        return tuple(attempt for attempt in self.attempts if attempt.is_resolved)


@dataclass(frozen=True, slots=True)
class DecisionHistoryProjection:
    """Projected decision history for a bounded set of sessions.

    Attributes:
        sessions: One entry per observed session, in first-seen order.
        unattributed: Outcome events that could not be linked to a roll.
    """

    sessions: tuple[SessionDecisions, ...]
    unattributed: UnattributedOutcomes


def project_decision_history(events: Iterable[Event]) -> DecisionHistoryProjection:
    """Project ordered events into per-session decision attempts.

    Args:
        events: Events from any number of sessions. Ordering within each
            session is derived deterministically; input order need only be
            iterable.

    Returns:
        Projection with per-session attempts plus unattributed outcome
        counts for events that lack an in-session preceding roll.
    """
    grouped: dict[int | None, list[Event]] = defaultdict(list)
    for event in events:
        grouped[event.session_id].append(event)

    unattributed_rates = 0
    unattributed_snoozes = 0
    unattributed_skips = 0
    sessions: list[SessionDecisions] = []

    for session_id, session_events in grouped.items():
        attempts: list[DecisionAttempt] = []
        corrections: list[Event] = []
        open_index: int | None = None

        for event in sorted(session_events, key=_event_order_key):
            if event.type == "roll":
                if open_index is not None:
                    attempts[open_index] = replace(
                        attempts[open_index], outcome=UNRESOLVED_SUPERSEDED
                    )
                attempts.append(
                    DecisionAttempt(
                        session_id=session_id,
                        roll_event_id=event.id if event.id is not None else 0,
                        rolled_at=event.timestamp,
                        thread_id=event.selected_thread_id,
                        outcome=OUTCOME_OPEN,
                        algorithm_version=_extract_algorithm_version(event),
                        bandwidth=_extract_bandwidth(event),
                        intent=_extract_intent(event),
                        records_launch_prediction=_records_launch_prediction(event),
                    )
                )
                open_index = len(attempts) - 1
            elif event.type in MODE_CORRECTION_EVENT_TYPES:
                corrections.append(event)
            elif event.type in _OUTCOME_BY_EVENT_TYPE:
                outcome = _OUTCOME_BY_EVENT_TYPE[event.type]
                if open_index is None:
                    if outcome == OUTCOME_ACCEPTED:
                        unattributed_rates += 1
                    elif outcome == OUTCOME_SNOOZED:
                        unattributed_snoozes += 1
                    else:
                        unattributed_skips += 1
                    continue
                open_attempt = attempts[open_index]
                attempts[open_index] = replace(
                    open_attempt,
                    outcome=outcome,
                    outcome_event_id=event.id if event.id is not None else 0,
                    outcome_at=event.timestamp,
                    rating=event.rating if outcome == OUTCOME_ACCEPTED else None,
                )
                open_index = None
            # Other event types ("undo", "unsnooze") do not rewrite recorded
            # decisions; metrics report history exactly as recorded.

        started_at = _infer_session_start(session_events)
        sessions.append(
            SessionDecisions(
                session_id=session_id,
                started_at=started_at,
                attempts=tuple(attempts),
                mode_corrections=tuple(corrections),
            )
        )

    return DecisionHistoryProjection(
        sessions=tuple(sessions),
        unattributed=UnattributedOutcomes(
            rates=unattributed_rates,
            snoozes=unattributed_snoozes,
            skips=unattributed_skips,
        ),
    )


def _infer_session_start(events: Sequence[Event]) -> datetime | None:
    """Infer a session start from its earliest event when needed.

    Real sessions carry ``started_at``; this fallback supports projecting
    bare event lists (unit tests, imported fragments).

    Args:
        events: All events observed for one session.

    Returns:
        Earliest event timestamp, or ``None`` when no event has one.
    """
    stamps = [
        _as_utc(event.timestamp)
        for event in events
        if event.timestamp is not None
    ]
    return min(stamps) if stamps else None


def _ratio(numerator: int, denominator: int) -> float | None:
    """Compute a ratio that stays undefined for empty denominators.

    Args:
        numerator: Non-negative count.
        denominator: Non-negative count.

    Returns:
        Rounded ratio, or ``None`` when the denominator is zero.
    """
    if denominator == 0:
        return None
    return round(numerator / denominator, 4)


def _percentile(sorted_values: Sequence[float], fraction: float) -> float | None:
    """Nearest-rank percentile of pre-sorted values.

    Args:
        sorted_values: Values ascending.
        fraction: Percentile fraction in ``(0, 1]``.

    Returns:
        The nearest-rank percentile value, or ``None`` when empty.
    """
    if not sorted_values:
        return None
    rank = min(max(math.ceil(len(sorted_values) * fraction), 1), len(sorted_values))
    return sorted_values[rank - 1]


@dataclass(frozen=True, slots=True)
class RatioMetric:
    """Count-based ratio kept alongside its raw numerator/denominator."""

    numerator: int
    denominator: int
    value: float | None


@dataclass(frozen=True, slots=True)
class ConsecutiveSnoozeStats:
    """Distribution of consecutive snoozes before first acceptance."""

    sessions_with_acceptance: int
    never_accepted_sessions: int
    distribution: dict[str, int]
    mean_consecutive_snoozes: float | None


@dataclass(frozen=True, slots=True)
class DurationStats:
    """Summary statistics over session-start-to-acceptance durations."""

    sample_count: int
    excluded_negative: int
    mean_seconds: float | None
    median_seconds: float | None
    p90_seconds: float | None


@dataclass(frozen=True, slots=True)
class ModeCorrectionStats:
    """Explicit manual/quiz mode-correction volume."""

    correction_events: int
    sessions_with_corrections: int


@dataclass(frozen=True, slots=True)
class LaunchPredictionStats:
    """Launch-mode prediction accuracy from recorded predictions."""

    recorded_launches: int
    corrected_launches: int
    accuracy: float | None


@dataclass(frozen=True, slots=True)
class RatingStats:
    """Rating volume and distribution across completed reads."""

    rated_reads: int
    unrated_reads: int
    mean_rating: float | None
    distribution: dict[str, int]


@dataclass(frozen=True, slots=True)
class RecommendationMetricSet:
    """Complete metric set for one grouping bucket."""

    first_roll_acceptance: RatioMetric
    snoozes_per_completed_read: RatioMetric
    consecutive_snoozes_before_acceptance: ConsecutiveSnoozeStats
    time_to_acceptance_seconds: DurationStats
    mode_corrections: ModeCorrectionStats
    launch_mode_prediction: LaunchPredictionStats
    ratings: RatingStats


def compute_metric_set(
    sessions: Sequence[SessionDecisions],
    *,
    unattributed: UnattributedOutcomes = UnattributedOutcomes(),
) -> RecommendationMetricSet:
    """Compute the full recommendation-quality metric set for sessions.

    Args:
        sessions: Projected session decisions included in the bucket.
        unattributed: Outcome events in scope that lack roll linkage.

    Returns:
        Metric set where every value follows the documented definitions.
    """
    first_roll = _first_roll_acceptance(sessions)
    snooze_ratio = _snoozes_per_completed_read(sessions, unattributed)
    consecutive = _consecutive_snoozes_before_acceptance(sessions)
    durations = _time_to_acceptance(sessions)
    corrections = _mode_correction_stats(sessions)
    prediction = _launch_prediction_stats(sessions)
    ratings = _rating_stats(sessions, unattributed)
    return RecommendationMetricSet(
        first_roll_acceptance=first_roll,
        snoozes_per_completed_read=snooze_ratio,
        consecutive_snoozes_before_acceptance=consecutive,
        time_to_acceptance_seconds=durations,
        mode_corrections=corrections,
        launch_mode_prediction=prediction,
        ratings=ratings,
    )


def _first_roll_acceptance(sessions: Sequence[SessionDecisions]) -> RatioMetric:
    """First-attempt acceptance ratio over sessions with resolvable starts."""
    numerator = 0
    denominator = 0
    for session in sessions:
        if not session.attempts:
            continue
        first = session.attempts[0]
        if not first.is_resolved:
            continue
        denominator += 1
        if first.outcome == OUTCOME_ACCEPTED:
            numerator += 1
    return RatioMetric(numerator=numerator, denominator=denominator,
                       value=_ratio(numerator, denominator))


def _snoozes_per_completed_read(
    sessions: Sequence[SessionDecisions],
    unattributed: UnattributedOutcomes,
) -> RatioMetric:
    """Snooze volume over completed reads, including unlinked events."""
    numerator = sum(
        1
        for session in sessions
        for attempt in session.attempts
        if attempt.outcome == OUTCOME_SNOOZED
    ) + unattributed.snoozes
    denominator = sum(
        1
        for session in sessions
        for attempt in session.attempts
        if attempt.outcome == OUTCOME_ACCEPTED
    ) + unattributed.rates
    return RatioMetric(numerator=numerator, denominator=denominator,
                       value=_ratio(numerator, denominator))


def _consecutive_snoozes_before_acceptance(
    sessions: Sequence[SessionDecisions],
) -> ConsecutiveSnoozeStats:
    """Consecutive-snooze distribution over sessions reaching acceptance."""
    counts: list[int] = []
    never_accepted = 0
    for session in sessions:
        consecutive = 0
        accepted = False
        for attempt in session.attempts:
            if attempt.outcome == OUTCOME_SNOOZED:
                consecutive += 1
            elif attempt.outcome == OUTCOME_ACCEPTED:
                counts.append(consecutive)
                accepted = True
                break
        if not accepted:
            never_accepted += 1
    distribution: dict[str, int] = defaultdict(int)
    for count in counts:
        distribution[str(count)] += 1
    mean = round(sum(counts) / len(counts), 4) if counts else None
    return ConsecutiveSnoozeStats(
        sessions_with_acceptance=len(counts),
        never_accepted_sessions=never_accepted,
        distribution=dict(sorted(distribution.items(), key=lambda item: int(item[0]))),
        mean_consecutive_snoozes=mean,
    )


def _time_to_acceptance(sessions: Sequence[SessionDecisions]) -> DurationStats:
    """Session-start-to-first-acceptance duration statistics."""
    durations: list[float] = []
    excluded_negative = 0
    for session in sessions:
        if session.started_at is None:
            continue
        start = _as_utc(session.started_at)
        for attempt in session.attempts:
            if attempt.outcome != OUTCOME_ACCEPTED or attempt.outcome_at is None:
                continue
            seconds = (_as_utc(attempt.outcome_at) - start).total_seconds()
            if seconds < 0:
                excluded_negative += 1
                break
            durations.append(seconds)
            break
    durations.sort()
    mean = round(sum(durations) / len(durations), 1) if durations else None
    median = _percentile(durations, 0.5)
    p90 = _percentile(durations, 0.9)
    median_value = round(median, 1) if median is not None else None
    p90_value = round(p90, 1) if p90 is not None else None
    return DurationStats(
        sample_count=len(durations),
        excluded_negative=excluded_negative,
        mean_seconds=mean,
        median_seconds=median_value,
        p90_seconds=p90_value,
    )


def _mode_correction_stats(sessions: Sequence[SessionDecisions]) -> ModeCorrectionStats:
    """Explicit mode-correction counts for the bucket."""
    total = sum(len(session.mode_corrections) for session in sessions)
    touched = sum(1 for session in sessions if session.mode_corrections)
    return ModeCorrectionStats(
        correction_events=total,
        sessions_with_corrections=touched,
    )


def _launch_prediction_stats(sessions: Sequence[SessionDecisions]) -> LaunchPredictionStats:
    """Prediction accuracy over launches that recorded a predicted mode."""
    recorded = 0
    corrected = 0
    for session in sessions:
        if not session.attempts:
            continue
        opening = session.attempts[0]
        if not opening.records_launch_prediction:
            continue
        recorded += 1
        if session.mode_corrections:
            corrected += 1
    return LaunchPredictionStats(
        recorded_launches=recorded,
        corrected_launches=corrected,
        accuracy=_ratio(recorded - corrected, recorded),
    )


def _rating_stats(
    sessions: Sequence[SessionDecisions],
    unattributed: UnattributedOutcomes,
) -> RatingStats:
    """Rating distribution across completed reads in the bucket."""
    ratings: list[float] = []
    unrated_reads = unattributed.rates
    for session in sessions:
        for attempt in session.attempts:
            if attempt.outcome != OUTCOME_ACCEPTED:
                continue
            if attempt.rating is None:
                unrated_reads += 1
            else:
                ratings.append(float(attempt.rating))
    distribution: dict[str, int] = defaultdict(int)
    for rating in ratings:
        bucket = round(rating * 2) / 2
        distribution[f"{bucket:g}"] += 1
    mean = round(sum(ratings) / len(ratings), 4) if ratings else None
    return RatingStats(
        rated_reads=len(ratings),
        unrated_reads=unrated_reads,
        mean_rating=mean,
        distribution=dict(sorted(distribution.items())),
    )


@dataclass(frozen=True, slots=True)
class BucketOutcomeRates:
    """Acceptance and snooze rates for one band/mode bucket."""

    decisions: int
    acceptances: int
    snoozes: int
    skips: int
    acceptance_rate: float | None
    snooze_rate: float | None


def _outcome_rates_by(
    sessions: Sequence[SessionDecisions],
    extractor: Callable[[DecisionAttempt], str],
) -> dict[str, BucketOutcomeRates]:
    """Aggregate resolved-attempt outcomes keyed by a context attribute."""
    totals: dict[str, dict[str, int]] = defaultdict(
        lambda: {"decisions": 0, "accepted": 0, "snoozed": 0, "skipped": 0}
    )
    for session in sessions:
        for attempt in session.attempts:
            if not attempt.is_resolved:
                continue
            bucket = totals[extractor(attempt) or UNKNOWN_BUCKET]
            bucket["decisions"] += 1
            bucket[attempt.outcome] += 1
    rates: dict[str, BucketOutcomeRates] = {}
    for name in sorted(totals):
        counts = totals[name]
        decisions = counts["decisions"]
        acceptances = counts["accepted"]
        snoozes = counts["snoozed"]
        skips = counts["skipped"]
        rates[name] = BucketOutcomeRates(
            decisions=decisions,
            acceptances=acceptances,
            snoozes=snoozes,
            skips=skips,
            acceptance_rate=_ratio(acceptances, decisions),
            snooze_rate=_ratio(snoozes, decisions),
        )
    return rates


def _band_of(attempt: DecisionAttempt) -> str:
    """Bucket key for an attempt's effort band."""
    return attempt.bandwidth or UNKNOWN_BUCKET


def _intent_of(attempt: DecisionAttempt) -> str:
    """Bucket key for an attempt's reading intent."""
    return attempt.intent or UNKNOWN_BUCKET


def acceptance_by_bandwidth(
    sessions: Sequence[SessionDecisions],
) -> dict[str, BucketOutcomeRates]:
    """Acceptance/snooze rates grouped by decision-time effort band.

    Args:
        sessions: Projected session decisions.

    Returns:
        Mapping from bandwidth label (or ``unknown``) to outcome rates.
    """
    return _outcome_rates_by(sessions, _band_of)


def acceptance_by_intent(
    sessions: Sequence[SessionDecisions],
) -> dict[str, BucketOutcomeRates]:
    """Acceptance/snooze rates grouped by decision-time intent.

    Args:
        sessions: Projected session decisions.

    Returns:
        Mapping from intent label (or ``unknown``) to outcome rates.
    """
    return _outcome_rates_by(sessions, _intent_of)


def _period_key(moment: datetime, grouping: PeriodGrouping) -> str:
    """Format a period bucket label for a timestamp.

    Args:
        moment: Timezone-aware timestamp to bucket.
        grouping: Requested period granularity.

    Returns:
        Stable label such as ``2026-08`` (month), ``2026-08-22`` (day), or
        ISO week ``2026-W34``.
    """
    value = _as_utc(moment)
    if grouping == "day":
        return value.strftime("%Y-%m-%d")
    if grouping == "week":
        iso = value.isocalendar()
        return f"{iso.year}-W{iso.week:02d}"
    return value.strftime("%Y-%m")


def _session_version(session: SessionDecisions) -> str:
    """Algorithm version attributed to a whole session."""
    for attempt in session.attempts:
        return attempt.algorithm_version
    return LEGACY_ALGORITHM_VERSION


def group_metric_sets(
    projection: DecisionHistoryProjection,
    *,
    period_grouping: PeriodGrouping = "none",
) -> tuple[
    RecommendationMetricSet,
    dict[str, RecommendationMetricSet],
    dict[str, BucketOutcomeRates],
    dict[str, BucketOutcomeRates],
    dict[str, RecommendationMetricSet],
]:
    """Compute overall metrics plus every documented grouping dimension.

    Args:
        projection: Projected decision history in scope.
        period_grouping: Optional time-range bucketing for sessions.

    Returns:
        Tuple of (overall, by_algorithm_version, by_bandwidth, by_intent,
        by_period). ``by_period`` is empty when grouping is ``none``.
    """
    overall = compute_metric_set(projection.sessions, unattributed=projection.unattributed)

    # Unattributed legacy outcomes carry no version or period, so they are
    # counted only in the overall view; per-group views aggregate exactly the
    # sessions belonging to their bucket to avoid double-counting.
    scoped_unattributed = UnattributedOutcomes()

    by_version_sessions: dict[str, list[SessionDecisions]] = defaultdict(list)
    by_period_sessions: dict[str, list[SessionDecisions]] = defaultdict(list)
    for session in projection.sessions:
        by_version_sessions[_session_version(session)].append(session)
        if period_grouping != "none" and session.started_at is not None:
            by_period_sessions[_period_key(session.started_at, period_grouping)].append(
                session
            )

    by_version = {
        version: compute_metric_set(sessions, unattributed=scoped_unattributed)
        for version, sessions in sorted(by_version_sessions.items())
    }

    by_period = {
        period: compute_metric_set(sessions, unattributed=scoped_unattributed)
        for period, sessions in sorted(by_period_sessions.items())
    }

    return (
        overall,
        by_version,
        acceptance_by_bandwidth(projection.sessions),
        acceptance_by_intent(projection.sessions),
        by_period,
    )


@dataclass(frozen=True, slots=True)
class MetricsCoverage:
    """Data-coverage counters explaining metric honesty boundaries.

    Attributes:
        sessions_in_range: Sessions whose start fell inside the window.
        sessions_with_decisions: Sessions contributing decision attempts.
        decision_attempts: Total reconstructed attempts.
        resolved_attempts: Attempts closing with a definite outcome.
        superseded_attempts: Attempts closed by a subsequent roll.
        unattributed_outcomes: Outcome events without an in-session roll.
        context_complete_attempts: Attempts carrying version + band + intent.
        legacy_context_attempts: Attempts falling back to legacy context.
    """

    sessions_in_range: int
    sessions_with_decisions: int
    decision_attempts: int
    resolved_attempts: int
    superseded_attempts: int
    unattributed_outcomes: int
    context_complete_attempts: int
    legacy_context_attempts: int


def compute_coverage(
    sessions_in_range: int,
    projection: DecisionHistoryProjection,
) -> MetricsCoverage:
    """Summarize how much decision history carries full context.

    Args:
        sessions_in_range: Number of session rows inside the query window.
        projection: Projected decision history for those sessions.

    Returns:
        Coverage counters used by reports to state metric confidence.
    """
    attempts = [
        attempt
        for session in projection.sessions
        for attempt in session.attempts
    ]
    resolved = sum(1 for attempt in attempts if attempt.is_resolved)
    superseded = sum(
        1 for attempt in attempts if attempt.outcome == UNRESOLVED_SUPERSEDED
    )
    complete = sum(
        1
        for attempt in attempts
        if attempt.algorithm_version != LEGACY_ALGORITHM_VERSION
        and attempt.bandwidth is not None
        and attempt.intent is not None
    )
    return MetricsCoverage(
        sessions_in_range=sessions_in_range,
        sessions_with_decisions=sum(1 for s in projection.sessions if s.attempts),
        decision_attempts=len(attempts),
        resolved_attempts=resolved,
        superseded_attempts=superseded,
        unattributed_outcomes=projection.unattributed.total,
        context_complete_attempts=complete,
        legacy_context_attempts=len(attempts) - complete,
    )


async def load_decision_history(
    db: AsyncSession,
    *,
    user_id: int,
    window_start: datetime,
    window_end: datetime,
) -> tuple[DecisionHistoryProjection, int]:
    """Load one user's bounded decision history for metrics computation.

    The read is strictly read-only and bounded both by owner and by the
    half-open time window ``[window_start, window_end)`` applied to session
    starts and event timestamps.

    Args:
        db: Async database session used for the reads.
        user_id: Owner whose history is loaded.
        window_start: Inclusive window start (naive treated as UTC).
        window_end: Exclusive window end (naive treated as UTC).

    Returns:
        Projected decision history plus the count of session rows whose
        start fell inside the window (for coverage reporting).
    """
    start = _as_utc(window_start)
    end = _as_utc(window_end)

    session_rows = (
        await db.scalars(
            select(SessionModel).where(
                SessionModel.user_id == user_id,
                SessionModel.started_at >= start,
                SessionModel.started_at < end,
            )
        )
    ).all()

    events = (
        await db.scalars(
            select(Event)
            .join(SessionModel, Event.session_id == SessionModel.id)
            .where(
                SessionModel.user_id == user_id,
                Event.timestamp >= start,
                Event.timestamp < end,
            )
            .order_by(Event.session_id, Event.timestamp, Event.id)
        )
    ).all()

    projection = project_decision_history(events)
    started_lookup = {row.id: row.started_at for row in session_rows}
    enriched = [
        SessionDecisions(
            session_id=session.session_id,
            started_at=started_lookup.get(session.session_id) or session.started_at,
            attempts=session.attempts,
            mode_corrections=session.mode_corrections,
        )
        for session in projection.sessions
    ]
    return (
        DecisionHistoryProjection(
            sessions=tuple(enriched), unattributed=projection.unattributed
        ),
        len(session_rows),
    )
