"""Deterministic audit and safe repair of read-without-rating issues (#3175).

The creator comparison counts "read with no stored rating" mechanically as
owned issues with ``status == "read"`` and no latest effective ``rate``
event. This service explains that population row by row and repairs only the
rows where a known historical rating is safely matchable.

Classification contract (one cause per row, first match wins):
- ``edition_conflict``: another owned read issue is confirmed against the same
  external issue identity, so no historical rating can be attributed to one
  copy without guessing. Never repaired.
- ``ambiguous_thread_rating``: thread-level historical rating(s) exist but
  cannot be attributed safely (several unrated read issues share the thread,
  or the thread's historical ratings disagree). Never repaired.
- ``missing_rate_event``: exactly one agreed thread-level historical rating
  exists and the thread holds exactly one unrated read issue, so the rating
  is safely matchable. Repaired by inserting one issue-linked ``rate``
  event; idempotent because repaired issues leave the population.
- ``unresolved_mapping``: no confirmed external issue identity exists, so
  the missing evidence is the confirmed mapping. Never repaired.
- ``no_source_rating``: confirmed identity exists but no rating signal was
  found anywhere, so the issue was read but never rated. Never repaired.

Nothing is ever inferred from averages, neighbors, or creator statistics.
"""

from __future__ import annotations

from collections import Counter
from dataclasses import dataclass, field
from datetime import UTC, datetime

from sqlalchemy.ext.asyncio import AsyncSession

from app.models.event import Event
from app.repositories.creator_summary import (
    CreatorSummaryInputs,
    load_creator_summary_inputs,
)
from app.repositories.read_without_rating_audit import (
    OwnedIssueIdentity,
    ReadWithoutRatingSignals,
    ThreadHistoricalRating,
    count_effective_ratings,
    load_owned_issue_identities,
    load_read_without_rating_signals,
    load_repair_event_issue_ids,
)

CAUSE_MISSING_RATE_EVENT = "missing_rate_event"
CAUSE_AMBIGUOUS_THREAD_RATING = "ambiguous_thread_rating"
CAUSE_UNRESOLVED_MAPPING = "unresolved_mapping"
CAUSE_EDITION_CONFLICT = "edition_conflict"
CAUSE_NO_SOURCE_RATING = "no_source_rating"

#: Human-readable cause labels surfaced in drilldown and audit evidence.
CAUSE_LABELS: dict[str, str] = {
    CAUSE_MISSING_RATE_EVENT: "Known historical rating is safely matchable",
    CAUSE_AMBIGUOUS_THREAD_RATING: "Historical rating exists but attribution is ambiguous",
    CAUSE_UNRESOLVED_MAPPING: "Issue identity mapping is unresolved",
    CAUSE_EDITION_CONFLICT: "Edition or duplicate conflict prevents a safe match",
    CAUSE_NO_SOURCE_RATING: "No known historical source rating",
}

#: Provenance marker written into the ``context`` of repair-created events so
#: reruns and readers can distinguish repairs from user-recorded ratings.
REPAIR_CONTEXT_SOURCE = "read_without_rating_audit"


@dataclass
class MissingRatingCause:
    """Evidenced classification for one read-without-rating issue.

    Attributes:
        cause: Machine-readable cause key (one of the ``CAUSE_*`` constants).
        label: Human-readable cause label.
        repair_safe: True only for safely matchable rows.
        missing_evidence: Names the evidence that would resolve an
            unresolved row (empty for resolved or needs-no-evidence rows).
        detail: Inspectable evidence (source event ids, rating values,
            mapping statuses, duplicate issue ids).
        source_rating: Agreed historical rating value when one exists.
        source_event_id: Source thread-level event id for safe repairs.
        source_recorded_at: Timestamp of the source event for safe repairs.
    """

    cause: str
    label: str
    repair_safe: bool
    missing_evidence: str = ""
    detail: dict[str, object] = field(default_factory=dict)
    source_rating: float | None = None
    source_event_id: int | None = None
    source_recorded_at: datetime | None = None


@dataclass
class AuditedIssue:
    """One read-without-rating row with identity and classification.

    Attributes:
        issue_id: Local ComicPile issue id.
        issue_number: Display issue number within its thread.
        thread_id: Owning thread id.
        thread_title: Owning thread title.
        cause: Evidenced classification for the row.
    """

    issue_id: int
    issue_number: str
    thread_id: int
    thread_title: str
    cause: MissingRatingCause


@dataclass
class ThreadCauseSummary:
    """Per-thread rollup of a read-without-rating population.

    Attributes:
        thread_id: Owning thread id.
        thread_title: Owning thread title.
        total: Read-without-rating rows in the thread.
        by_cause: Cause key to row count within the thread.
    """

    thread_id: int
    thread_title: str
    total: int
    by_cause: dict[str, int]


@dataclass
class CreatorCauseSummary:
    """Per-creator rollup of a read-without-rating population.

    Attributes:
        display_name: Provider display name, or ``"Uncredited"`` when no
            confirmed creator credit names the issue.
        total: Read-without-rating rows attributed to the creator.
        by_cause: Cause key to row count for the creator.
    """

    display_name: str
    total: int
    by_cause: dict[str, int]


@dataclass
class ReadWithoutRatingAudit:
    """Complete deterministic audit of a user's read-without-rating rows.

    Attributes:
        user_id: Owner of the audited library.
        total: Total read-without-rating rows counted.
        by_cause: Cause key to row count across the population.
        by_thread: Per-thread rollups keyed by thread id.
        creator_impact: Creator rollups ordered by total descending.
        issues: Every audited row with identity and classification,
            ordered by (thread title, issue number, issue id).
        effective_rated_issues: Owned issues carrying a latest effective
            rating at audit time (pre-repair reconciliation anchor).
    """

    user_id: int
    total: int
    by_cause: dict[str, int]
    by_thread: dict[int, ThreadCauseSummary]
    creator_impact: list[CreatorCauseSummary]
    issues: list[AuditedIssue]
    effective_rated_issues: int


@dataclass
class ReadWithoutRatingRepairReport:
    """Outcome of one idempotent safe-repair pass.

    Attributes:
        user_id: Owner of the repaired library.
        effective_before: Effective rated-issue count before the pass.
        effective_after: Effective rated-issue count after the pass.
        repaired: Number of issue-linked ``rate`` events inserted.
        repaired_issue_ids: Sorted issue ids that gained an effective rating.
        skipped_by_cause: Unrepaired population counts by cause.
    """

    user_id: int
    effective_before: int
    effective_after: int
    repaired: int
    repaired_issue_ids: list[int]
    skipped_by_cause: dict[str, int]


def classify_missing_rating(
    *,
    issue_id: int,
    thread_id: int,
    historical_ratings: list[ThreadHistoricalRating],
    mapping_statuses: list[str],
    duplicate_issue_ids: list[int],
    unrated_read_in_thread: int,
) -> MissingRatingCause:
    """Classify one read-without-rating issue from batched evidence.

    Pure function: no database access, so classification is deterministic
    for a fixed evidence snapshot.

    Args:
        issue_id: Read-without-rating issue being classified.
        thread_id: Thread owning the issue.
        historical_ratings: Thread-level historical ratings for the thread,
            oldest first.
        mapping_statuses: Distinct identity-mapping statuses for the issue.
        duplicate_issue_ids: Other owned read issues confirmed against a
            shared external issue identity.
        unrated_read_in_thread: Count of read issues without an effective
            rating in the thread, including this issue.

    Returns:
        The evidenced classification; only ``missing_rate_event`` is repair
        safe.
    """
    if duplicate_issue_ids:
        return MissingRatingCause(
            cause=CAUSE_EDITION_CONFLICT,
            label=CAUSE_LABELS[CAUSE_EDITION_CONFLICT],
            repair_safe=False,
            detail={
                "duplicate_issue_ids": list(duplicate_issue_ids),
                "reason": (
                    "Another read issue is confirmed against the same external "
                    "issue identity, so the library holds two copies and a "
                    "historical rating cannot be attributed to one of them."
                ),
            },
        )
    agreed_rating = _agreed_historical_rating(historical_ratings)
    if historical_ratings and agreed_rating is None:
        values = sorted({entry.rating for entry in historical_ratings})
        return MissingRatingCause(
            cause=CAUSE_AMBIGUOUS_THREAD_RATING,
            label=CAUSE_LABELS[CAUSE_AMBIGUOUS_THREAD_RATING],
            repair_safe=False,
            detail={
                "source_event_ids": [entry.event_id for entry in historical_ratings],
                "rating_values": values,
                "reason": (
                    "Thread-level historical ratings disagree, so no single "
                    "value can be attributed."
                ),
            },
        )
    if historical_ratings and unrated_read_in_thread != 1:
        return MissingRatingCause(
            cause=CAUSE_AMBIGUOUS_THREAD_RATING,
            label=CAUSE_LABELS[CAUSE_AMBIGUOUS_THREAD_RATING],
            repair_safe=False,
            detail={
                "source_event_ids": [entry.event_id for entry in historical_ratings],
                "rating_values": sorted({entry.rating for entry in historical_ratings}),
                "unrated_read_in_thread": unrated_read_in_thread,
                "reason": (
                    "Several unrated read issues share this thread, so the "
                    "thread-level historical rating cannot be attributed to "
                    "one issue."
                ),
            },
        )
    if historical_ratings and agreed_rating is not None:
        source = historical_ratings[0]
        return MissingRatingCause(
            cause=CAUSE_MISSING_RATE_EVENT,
            label=CAUSE_LABELS[CAUSE_MISSING_RATE_EVENT],
            repair_safe=True,
            detail={
                "source_event_ids": [entry.event_id for entry in historical_ratings],
                "thread_id": thread_id,
                "reason": (
                    "One agreed thread-level historical rating exists and "
                    "this is the thread's only unrated read issue."
                ),
            },
            source_rating=agreed_rating,
            source_event_id=source.event_id,
            source_recorded_at=source.recorded_at,
        )
    if "confirmed" not in mapping_statuses:
        if mapping_statuses:
            reason = (
                "Identity mappings exist but none is confirmed "
                f"({', '.join(mapping_statuses)}), so the issue identity "
                "needed to match a historical rating is missing."
            )
        else:
            reason = (
                "No external issue identity mapping exists, so the issue "
                "identity needed to match a historical rating is missing."
            )
        return MissingRatingCause(
            cause=CAUSE_UNRESOLVED_MAPPING,
            label=CAUSE_LABELS[CAUSE_UNRESOLVED_MAPPING],
            repair_safe=False,
            missing_evidence="confirmed external issue identity mapping",
            detail={"mapping_statuses": list(mapping_statuses), "reason": reason},
        )
    return MissingRatingCause(
        cause=CAUSE_NO_SOURCE_RATING,
        label=CAUSE_LABELS[CAUSE_NO_SOURCE_RATING],
        repair_safe=False,
        detail={
            "reason": (
                "Identity is confirmed and no rating signal exists, so the "
                "issue was read but never rated."
            ),
        },
    )


def _agreed_historical_rating(
    historical_ratings: list[ThreadHistoricalRating],
) -> float | None:
    """Return the single agreed rating, or None when absent or conflicting.

    Args:
        historical_ratings: Thread-level historical ratings, oldest first.

    Returns:
        The agreed rating value, or None when there are no ratings or the
        ratings disagree.
    """
    values = {entry.rating for entry in historical_ratings}
    if len(values) == 1:
        return next(iter(values))
    return None


async def audit_read_without_rating(
    db: AsyncSession,
    user_id: int,
) -> ReadWithoutRatingAudit:
    """Audit the user's full read-without-rating population.

    The population uses the exact #2028 effective-rating semantics shared
    with the creator comparison, so the total reconciles with the surfaced
    "read with no stored rating" counts.

    Args:
        db: Async database session.
        user_id: Owner of the library being audited.

    Returns:
        The complete audit with per-row causes, per-thread rollups, and
        creator impact ordered by total descending.
    """
    inputs = await load_creator_summary_inputs(db, user_id)
    population = _read_without_rating_ids(inputs, None)
    signals = await load_read_without_rating_signals(db, user_id, population)
    identities = await load_owned_issue_identities(db, user_id, population)
    thread_unrated_counts = _thread_unrated_counts(inputs)
    issues = [
        _audit_row(inputs, signals, thread_unrated_counts, identities, issue_id)
        for issue_id in population
    ]
    issues.sort(
        key=lambda row: (row.thread_title.casefold(), row.issue_number, row.issue_id)
    )
    effective_rated = await count_effective_ratings(db, user_id)
    return ReadWithoutRatingAudit(
        user_id=user_id,
        total=len(issues),
        by_cause=dict(Counter(row.cause.cause for row in issues)),
        by_thread=_rollup_threads(issues),
        creator_impact=_rollup_creators(inputs, issues),
        issues=issues,
        effective_rated_issues=effective_rated,
    )


async def classify_issue_ids(
    db: AsyncSession,
    user_id: int,
    issue_ids: list[int],
    *,
    inputs: CreatorSummaryInputs | None = None,
) -> dict[int, MissingRatingCause]:
    """Classify exactly the requested read-without-rating issues.

    Bounded helper for drilldown surfaces that must explain one page of rows
    without auditing the whole library.

    Args:
        db: Async database session.
        user_id: Owner of the library.
        issue_ids: Read-without-rating issue ids to classify.
        inputs: Already-loaded creator summary inputs. Callers that hold them
            must pass them so the shared aggregation is not re-read; omit only
            when the caller has none.

    Returns:
        Mapping of issue id to its evidenced classification. Requested ids
        that are not read-without-rating rows are absent.
    """
    unique_ids = list(dict.fromkeys(issue_ids))
    if not unique_ids:
        return {}
    if inputs is None:
        inputs = await load_creator_summary_inputs(db, user_id)
    population = _read_without_rating_ids(inputs, unique_ids)
    if not population:
        return {}
    signals = await load_read_without_rating_signals(db, user_id, population)
    identities = await load_owned_issue_identities(db, user_id, population)
    thread_unrated_counts = _thread_unrated_counts(inputs)
    causes: dict[int, MissingRatingCause] = {}
    for issue_id in population:
        series = inputs.owned_issue_series.get(issue_id)
        identity = identities.get(issue_id)
        if series is None or identity is None:
            continue
        causes[issue_id] = classify_missing_rating(
            issue_id=issue_id,
            thread_id=series.thread_id,
            historical_ratings=signals.thread_historical_ratings.get(series.thread_id, []),
            mapping_statuses=signals.mapping_statuses.get(issue_id, []),
            duplicate_issue_ids=signals.duplicate_issue_ids.get(issue_id, []),
            unrated_read_in_thread=thread_unrated_counts.get(series.thread_id, 1),
        )
    return causes


async def repair_safe_missing_ratings(
    db: AsyncSession,
    user_id: int,
) -> ReadWithoutRatingRepairReport:
    """Insert issue-linked ``rate`` events for safely matchable rows only.

    Idempotent: repaired issues gain an effective rating and leave the
    population, so reruns insert nothing. Issues with an effective rating
    are never touched, so already-correct latest-effective ratings cannot
    change. Each repair copies the source rating value and timestamp and
    records audit provenance in the event ``context``.

    Args:
        db: Async database session.
        user_id: Owner of the library being repaired.

    Returns:
        The repair report with pre/post effective totals and per-cause
        skip counts.
    """
    effective_before = await count_effective_ratings(db, user_id)
    audit = await audit_read_without_rating(db, user_id)
    candidates = [
        row
        for row in audit.issues
        if row.cause.repair_safe
        and row.cause.source_rating is not None
        and row.cause.source_event_id is not None
    ]
    # Defense in depth for idempotency: population membership already
    # excludes rated issues, but this guard keeps a rerun from duplicating
    # a repair even if the source evidence changed underneath it.
    already_repaired = await load_repair_event_issue_ids(
        db, [row.issue_id for row in candidates], REPAIR_CONTEXT_SOURCE
    )
    repaired_ids: list[int] = []
    for row in candidates:
        if row.issue_id in already_repaired:
            continue
        recorded_at = row.cause.source_recorded_at or datetime.now(UTC)
        db.add(
            Event(
                type="rate",
                rating=row.cause.source_rating,
                issue_id=row.issue_id,
                thread_id=row.thread_id,
                issue_number=row.issue_number,
                timestamp=recorded_at,
                context={
                    "source": REPAIR_CONTEXT_SOURCE,
                    "source_event_id": row.cause.source_event_id,
                    "cause": CAUSE_MISSING_RATE_EVENT,
                },
            )
        )
        repaired_ids.append(row.issue_id)

    # Extract ids before commit: attribute access after commit can expire.
    repaired_sorted = sorted(repaired_ids)
    repaired_count = len(repaired_sorted)
    if repaired_count:
        await db.commit()
    effective_after = await count_effective_ratings(db, user_id)
    skipped = Counter(
        row.cause.cause for row in audit.issues if row.issue_id not in repaired_ids
    )
    return ReadWithoutRatingRepairReport(
        user_id=user_id,
        effective_before=effective_before,
        effective_after=effective_after,
        repaired=repaired_count,
        repaired_issue_ids=repaired_sorted,
        skipped_by_cause=dict(skipped),
    )


def _read_without_rating_ids(
    inputs: CreatorSummaryInputs,
    only: list[int] | None,
) -> list[int]:
    """List population issue ids using shared effective-rating semantics.

    Args:
        inputs: Creator summary inputs with ownership and rating data.
        only: Optional allow-list of issue ids; None audits the whole
            library.

    Returns:
        Sorted read-without-rating issue ids within the allow-list.
    """
    wanted = set(only) if only is not None else None
    return sorted(
        issue_id
        for issue_id, status in inputs.owned_issues.items()
        if status == "read"
        and issue_id not in inputs.effective_ratings
        and (wanted is None or issue_id in wanted)
    )


def _thread_unrated_counts(inputs: CreatorSummaryInputs) -> Counter[int]:
    """Count unrated read issues per thread over the full population.

    Always computed over the whole library (never a bounded subset) so a
    bounded classification still sees every competing sibling issue.

    Args:
        inputs: Creator summary inputs with ownership, series, and rating
            data.

    Returns:
        Mapping of thread id to unrated-read issue count.
    """
    counts: Counter[int] = Counter()
    for issue_id, status in inputs.owned_issues.items():
        if status != "read" or issue_id in inputs.effective_ratings:
            continue
        series = inputs.owned_issue_series.get(issue_id)
        if series is not None:
            counts[series.thread_id] += 1
    return counts


def _audit_row(
    inputs: CreatorSummaryInputs,
    signals: ReadWithoutRatingSignals,
    thread_unrated_counts: Counter[int],
    identities: dict[int, OwnedIssueIdentity],
    issue_id: int,
) -> AuditedIssue:
    """Build one audited row from shared inputs and batched signals.

    Args:
        inputs: Creator summary inputs with ownership and series data.
        signals: Batched audit evidence for the population.
        thread_unrated_counts: Unrated-read counts keyed by thread id.
        identities: Local issue identities keyed by issue id.
        issue_id: Read-without-rating issue being audited.

    Returns:
        The audited row with identity and classification.
    """
    series = inputs.owned_issue_series[issue_id]
    identity = identities[issue_id]
    cause = classify_missing_rating(
        issue_id=issue_id,
        thread_id=series.thread_id,
        historical_ratings=signals.thread_historical_ratings.get(series.thread_id, []),
        mapping_statuses=signals.mapping_statuses.get(issue_id, []),
        duplicate_issue_ids=signals.duplicate_issue_ids.get(issue_id, []),
        unrated_read_in_thread=thread_unrated_counts.get(series.thread_id, 1),
    )
    return AuditedIssue(
        issue_id=issue_id,
        issue_number=identity.issue_number,
        thread_id=series.thread_id,
        thread_title=series.thread_title,
        cause=cause,
    )


def _rollup_threads(issues: list[AuditedIssue]) -> dict[int, ThreadCauseSummary]:
    """Roll audited rows up by owning thread.

    Args:
        issues: Audited rows to roll up.

    Returns:
        Per-thread summaries keyed by thread id.
    """
    grouped: dict[int, list[AuditedIssue]] = {}
    for row in issues:
        grouped.setdefault(row.thread_id, []).append(row)
    summaries: dict[int, ThreadCauseSummary] = {}
    for thread_id, rows in grouped.items():
        summaries[thread_id] = ThreadCauseSummary(
            thread_id=thread_id,
            thread_title=rows[0].thread_title,
            total=len(rows),
            by_cause=dict(Counter(row.cause.cause for row in rows)),
        )
    return summaries


def _rollup_creators(
    inputs: CreatorSummaryInputs,
    issues: list[AuditedIssue],
) -> list[CreatorCauseSummary]:
    """Roll audited rows up by creator display name.

    Issues sharing several credited creators count once per creator; issues
    with no usable credit fall under ``"Uncredited"``.

    Args:
        inputs: Creator summary inputs with confirmed credit data.
        issues: Audited rows to roll up.

    Returns:
        Creator summaries ordered by total descending, then name.
    """
    per_creator: dict[str, list[AuditedIssue]] = {}
    for row in issues:
        names = {
            credit.display_name or "Uncredited"
            for credit in inputs.issue_creator_credits.get(row.issue_id, ())
        } or {"Uncredited"}
        for name in names:
            per_creator.setdefault(name, []).append(row)
    summaries = [
        CreatorCauseSummary(
            display_name=name,
            total=len(rows),
            by_cause=dict(Counter(row.cause.cause for row in rows)),
        )
        for name, rows in per_creator.items()
    ]
    summaries.sort(key=lambda summary: (-summary.total, summary.display_name.casefold()))
    return summaries


__all__ = [
    "CAUSE_AMBIGUOUS_THREAD_RATING",
    "CAUSE_EDITION_CONFLICT",
    "CAUSE_LABELS",
    "CAUSE_MISSING_RATE_EVENT",
    "CAUSE_NO_SOURCE_RATING",
    "CAUSE_UNRESOLVED_MAPPING",
    "REPAIR_CONTEXT_SOURCE",
    "AuditedIssue",
    "CreatorCauseSummary",
    "MissingRatingCause",
    "ReadWithoutRatingAudit",
    "ReadWithoutRatingRepairReport",
    "audit_read_without_rating",
    "classify_issue_ids",
    "classify_missing_rating",
    "repair_safe_missing_ratings",
]
