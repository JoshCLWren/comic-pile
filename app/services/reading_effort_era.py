"""ComicVine publication-era fallback for reading-effort estimates.

Phase-1 reading-effort work (#1685) needs a conservative prior when a thread or
issue lacks enough observed reading-time history. This module resolves the
publication year from *confirmed* ComicVine external metadata and maps it onto
one deliberately coarse era bucket with a documented effort prior.

Contract:

- Era resolution is a fallback only. Observed user-specific effort takes
  precedence once sufficient evidence exists.
- Estimates always carry an explicit source (``observed_issue``,
  ``observed_thread``, ``era_prior``, ``unknown``) and confidence.
- Unknown, missing, ambiguous, or implausible metadata fails to the neutral
  ``unknown`` estimate. Nothing in this module may raise into the Roll path.

The source/band vocabulary intentionally matches
``app.services.reading_effort`` (issue #1704) so later integration glue can map
:class:`ReadingEffortEstimate` values straight through.

Era buckets follow the commonly used American comic-book age boundaries and are
intentionally coarse; priors are documented medians in minutes, never deep
effort claims, and must only change together with their tests.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from datetime import UTC, datetime
import logging
import re

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.external_identity import (
    ExternalIdentity,
    IssueExternalIdentityMapping,
    ThreadExternalSeriesMapping,
)
from app.models.issue import Issue
from app.models.thread import Thread

logger = logging.getLogger(__name__)

COMICVINE_PROVIDER = "comicvine"

ESTIMATE_SOURCE_OBSERVED_ISSUE = "observed_issue"
ESTIMATE_SOURCE_OBSERVED_THREAD = "observed_thread"
ESTIMATE_SOURCE_ERA_PRIOR = "era_prior"
ESTIMATE_SOURCE_UNKNOWN = "unknown"

KNOWN_EFFORT_SOURCES = frozenset(
    {
        ESTIMATE_SOURCE_OBSERVED_ISSUE,
        ESTIMATE_SOURCE_OBSERVED_THREAD,
        ESTIMATE_SOURCE_ERA_PRIOR,
        ESTIMATE_SOURCE_UNKNOWN,
    }
)

OBSERVED_EFFORT_SOURCES = frozenset(
    {
        ESTIMATE_SOURCE_OBSERVED_ISSUE,
        ESTIMATE_SOURCE_OBSERVED_THREAD,
    }
)

EFFORT_BAND_LIGHT = "light"
EFFORT_BAND_BALANCED = "balanced"
EFFORT_BAND_DEEP = "deep"

KNOWN_EFFORT_BANDS = frozenset({EFFORT_BAND_LIGHT, EFFORT_BAND_BALANCED, EFFORT_BAND_DEEP})

# Reading-effort bands from the parent product contract (#1685): light reads
# finish under 12 minutes, balanced reads run 12-18 minutes, deep reads take 18
# minutes or more.
EFFORT_LIGHT_MAX_MINUTES = 12.0
EFFORT_DEEP_MIN_MINUTES = 18.0

BASIS_ISSUE_COVER_DATE = "issue_cover_date"
BASIS_ISSUE_STORE_DATE = "issue_store_date"
BASIS_SERIES_START_YEAR = "series_start_year"

# Publication years outside this window are treated as provider garbage rather
# than as evidence. The upper bound allows solicited-but-unreleased issues.
MIN_PUBLICATION_YEAR = 1900
FUTURE_YEAR_ALLOWANCE = 1

# Confirmed issue-level dates describe the exact issue; a series start year is
# only a proxy for long-running volumes. Both stay far below observed-data
# confidence because they are population priors, not measurements.
CONFIDENCE_ISSUE_LEVEL_YEAR = 0.3
CONFIDENCE_SERIES_LEVEL_YEAR = 0.15

# Minimum number of valid observations before an observed estimate may outrank
# the era prior. Provisional gate centralized here until the observed-history
# aggregator (#1702) publishes its own documented minimum.
MIN_OBSERVED_EFFORT_SAMPLES = 3


@dataclass(frozen=True)
class EraBucket:
    """One coarse publication-era bucket with its documented effort prior."""

    name: str
    start_year: int
    end_year: int | None
    prior_minutes: float


# Bucket boundaries are inclusive on both ends; ``end_year=None`` extends to
# the plausible-present ceiling. Years inside the plausibility window but
# outside every bucket (proto-comics before 1938) are unmapped and fail to
# neutral rather than borrowing a neighboring era.
ERA_BUCKETS: tuple[EraBucket, ...] = (
    EraBucket(name="golden_age", start_year=1938, end_year=1955, prior_minutes=14.0),
    EraBucket(name="silver_age", start_year=1956, end_year=1969, prior_minutes=13.0),
    EraBucket(name="bronze_age", start_year=1970, end_year=1984, prior_minutes=12.0),
    EraBucket(name="copper_age", start_year=1985, end_year=1996, prior_minutes=10.0),
    EraBucket(name="modern", start_year=1997, end_year=None, prior_minutes=8.0),
)


@dataclass(frozen=True)
class PublicationEvidence:
    """One confirmed publication-year fact and where it came from."""

    year: int
    basis: str


@dataclass(frozen=True)
class ReadingEffortEstimate:
    """A bounded reading-effort estimate with explicit provenance.

    Attributes:
        minutes: Estimated effort in minutes, or ``None`` when unknown.
        band: One of :data:`KNOWN_EFFORT_BANDS`, or ``None`` when unknown.
        source: One of :data:`KNOWN_EFFORT_SOURCES`.
        confidence: Estimate confidence within ``[0.0, 1.0]``, or ``None``.
        samples: Observation count for observed sources, otherwise ``None``.
    """

    minutes: float | None
    band: str | None
    source: str
    confidence: float | None
    samples: int | None = None

    def __post_init__(self) -> None:
        if self.source not in KNOWN_EFFORT_SOURCES:
            raise ValueError(f"Unknown effort source: {self.source!r}")
        if self.band is not None and self.band not in KNOWN_EFFORT_BANDS:
            raise ValueError(f"Unknown effort band: {self.band!r}")
        if self.confidence is not None and not 0.0 <= self.confidence <= 1.0:
            raise ValueError(f"Effort confidence must be within [0, 1]: {self.confidence!r}")
        if self.minutes is not None and self.minutes <= 0:
            raise ValueError(f"Effort minutes must be positive: {self.minutes!r}")
        if self.samples is not None and (
            self.source not in OBSERVED_EFFORT_SOURCES or self.samples < 1
        ):
            raise ValueError(
                f"Sample counts require an observed source and at least one observation: "
                f"source={self.source!r} samples={self.samples!r}"
            )
        if self.source == ESTIMATE_SOURCE_UNKNOWN:
            neutral_fields = (
                self.minutes is None
                and self.band is None
                and self.confidence is None
                and self.samples is None
            )
            if not neutral_fields:
                raise ValueError("Unknown-source estimates must be fully neutral")
        elif self.minutes is None or self.band is None or self.confidence is None:
            raise ValueError(
                f"Era and observed estimates require minutes, band, and confidence: "
                f"source={self.source!r}"
            )


NEUTRAL_READING_EFFORT_ESTIMATE = ReadingEffortEstimate(
    minutes=None,
    band=None,
    source=ESTIMATE_SOURCE_UNKNOWN,
    confidence=None,
)


def effort_band_for_minutes(minutes: float) -> str:
    """Map an effort duration in minutes onto the canonical band vocabulary."""
    if minutes < EFFORT_LIGHT_MAX_MINUTES:
        return EFFORT_BAND_LIGHT
    if minutes < EFFORT_DEEP_MIN_MINUTES:
        return EFFORT_BAND_BALANCED
    return EFFORT_BAND_DEEP


def _plausible_publication_ceiling(reference_year: int | None) -> int:
    if reference_year is not None:
        return reference_year + FUTURE_YEAR_ALLOWANCE
    return datetime.now(UTC).year + FUTURE_YEAR_ALLOWANCE


def _year_in_plausible_window(year: int, reference_year: int | None) -> bool:
    return MIN_PUBLICATION_YEAR <= year <= _plausible_publication_ceiling(reference_year)


def _year_from_date_string(value: object) -> int | None:
    if not isinstance(value, str):
        return None
    match = re.search(r"(\d{4})", value)
    return int(match.group(1)) if match else None


def _year_from_scalar(value: object) -> int | None:
    if isinstance(value, bool):
        return None
    if isinstance(value, int):
        return value
    if isinstance(value, str) and value.strip().isdigit():
        return int(value.strip())
    return None


def publication_year_from_issue_metadata(
    metadata: Mapping[str, object] | None,
    *,
    reference_year: int | None = None,
) -> PublicationEvidence | None:
    """Resolve a publication year from one confirmed issue's external metadata.

    The cover date is the canonical publication fact; the store date is the
    fallback when the cover date is absent or unusable. Unparseable or
    implausible values yield ``None`` instead of guessing.

    Args:
        metadata: Normalized issue ``metadata_json`` payload.
        reference_year: Optional clock override used by tests.

    Returns:
        Publication evidence, or ``None`` when no usable year exists.
    """
    if not isinstance(metadata, Mapping):
        return None
    for key, basis in (
        ("cover_date", BASIS_ISSUE_COVER_DATE),
        ("store_date", BASIS_ISSUE_STORE_DATE),
    ):
        year = _year_from_date_string(metadata.get(key))
        if year is not None and _year_in_plausible_window(year, reference_year):
            return PublicationEvidence(year=year, basis=basis)
    return None


def publication_year_from_series_metadata(
    metadata: Mapping[str, object] | None,
    *,
    reference_year: int | None = None,
) -> PublicationEvidence | None:
    """Resolve a publication year from one confirmed series' external metadata.

    Args:
        metadata: Normalized series/volume ``metadata_json`` payload.
        reference_year: Optional clock override used by tests.

    Returns:
        Publication evidence, or ``None`` when no usable start year exists.
    """
    if not isinstance(metadata, Mapping):
        return None
    year = _year_from_scalar(metadata.get("start_year"))
    if year is not None and _year_in_plausible_window(year, reference_year):
        return PublicationEvidence(year=year, basis=BASIS_SERIES_START_YEAR)
    return None


def era_bucket_for_year(year: int, *, reference_year: int | None = None) -> EraBucket | None:
    """Return the coarse era bucket containing ``year``, else ``None``.

    Args:
        year: Candidate publication year.
        reference_year: Optional clock override bounding plausible years.

    Returns:
        The matching :class:`EraBucket`, or ``None`` when the year falls
        outside the plausibility window or between documented eras.
    """
    if not _year_in_plausible_window(year, reference_year):
        return None
    for bucket in ERA_BUCKETS:
        if bucket.start_year <= year and (bucket.end_year is None or year <= bucket.end_year):
            return bucket
    return None


def era_prior_estimate(
    evidence: PublicationEvidence | None,
    *,
    reference_year: int | None = None,
) -> ReadingEffortEstimate:
    """Build the conservative era-prior estimate for one publication fact.

    Args:
        evidence: Confirmed publication evidence, or ``None``.
        reference_year: Optional clock override used by tests.

    Returns:
        An ``era_prior`` estimate when the evidence maps onto a documented
        bucket, otherwise the neutral ``unknown`` estimate.
    """
    if evidence is None:
        return NEUTRAL_READING_EFFORT_ESTIMATE
    confidence = (
        CONFIDENCE_ISSUE_LEVEL_YEAR
        if evidence.basis in (BASIS_ISSUE_COVER_DATE, BASIS_ISSUE_STORE_DATE)
        else CONFIDENCE_SERIES_LEVEL_YEAR
    )
    bucket = era_bucket_for_year(evidence.year, reference_year=reference_year)
    if bucket is None:
        return NEUTRAL_READING_EFFORT_ESTIMATE
    return ReadingEffortEstimate(
        minutes=bucket.prior_minutes,
        band=effort_band_for_minutes(bucket.prior_minutes),
        source=ESTIMATE_SOURCE_ERA_PRIOR,
        confidence=confidence,
    )


def resolve_reading_effort(
    *,
    observed_issue_estimate: ReadingEffortEstimate | None = None,
    observed_thread_estimate: ReadingEffortEstimate | None = None,
    issue_evidence: PublicationEvidence | None = None,
    series_evidence: PublicationEvidence | None = None,
    reference_year: int | None = None,
) -> ReadingEffortEstimate:
    """Resolve the best available estimate under the documented precedence.

    Precedence: sufficiently-sampled issue-level observations, then
    thread-level observations, then the era prior derived from confirmed
    issue metadata, then from confirmed series metadata, then neutral.

    Slot arguments define precedence order, not identity: each slot accepts
    any observed-source estimate and ignores entries that lack enough samples.

    Args:
        observed_issue_estimate: Issue-level observed estimate, if any.
        observed_thread_estimate: Thread-level observed estimate, if any.
        issue_evidence: Confirmed issue publication evidence, if any.
        series_evidence: Confirmed series publication evidence, if any.
        reference_year: Optional clock override used by tests.

    Returns:
        The highest-precedence trusted estimate, never ``None`` and never an
        exception: unmappable evidence degrades to the neutral estimate.
    """

    def _trusted(estimate: ReadingEffortEstimate | None) -> bool:
        return (
            estimate is not None
            and estimate.source in OBSERVED_EFFORT_SOURCES
            and estimate.samples is not None
            and estimate.samples >= MIN_OBSERVED_EFFORT_SAMPLES
        )

    for observed in (observed_issue_estimate, observed_thread_estimate):
        if _trusted(observed) and observed is not None:
            return observed

    issue_prior = era_prior_estimate(issue_evidence, reference_year=reference_year)
    if issue_prior.source == ESTIMATE_SOURCE_ERA_PRIOR:
        return issue_prior

    series_prior = era_prior_estimate(series_evidence, reference_year=reference_year)
    if series_prior.source == ESTIMATE_SOURCE_ERA_PRIOR:
        return series_prior

    return NEUTRAL_READING_EFFORT_ESTIMATE


async def load_publication_evidence(
    db: AsyncSession,
    thread: Thread,
    *,
    reference_year: int | None = None,
) -> tuple[PublicationEvidence | None, PublicationEvidence | None]:
    """Load confirmed ComicVine publication facts for one thread.

    Issue-level evidence prefers the thread's next unread issue, then falls
    back to the thread's issues in queue order. Series-level evidence uses the
    first confirmed series mapping. Only ``confirmed`` mappings count;
    candidates and rejected mappings are ignored.

    Args:
        db: Async database session.
        thread: Owned thread to inspect.
        reference_year: Optional clock override used by tests.

    Returns:
        ``(issue_evidence, series_evidence)`` where either entry may be ``None``
        when no confirmed, usable metadata exists.
    """
    issue_id_order: list[int] = []
    if thread.next_unread_issue_id is not None:
        issue_id_order.append(thread.next_unread_issue_id)
    rows = await db.execute(
        select(Issue.id)
        .where(Issue.thread_id == thread.id)
        .order_by(Issue.position.asc(), Issue.id.asc())
    )
    for issue_id in rows.scalars():
        if issue_id not in issue_id_order:
            issue_id_order.append(issue_id)

    issue_evidence: PublicationEvidence | None = None
    if issue_id_order:
        result = await db.execute(
            select(IssueExternalIdentityMapping.issue_id, ExternalIdentity.metadata_json)
            .join(
                ExternalIdentity,
                ExternalIdentity.id == IssueExternalIdentityMapping.external_identity_id,
            )
            .where(
                IssueExternalIdentityMapping.issue_id.in_(issue_id_order),
                IssueExternalIdentityMapping.status == "confirmed",
                ExternalIdentity.provider == COMICVINE_PROVIDER,
                ExternalIdentity.entity_type == "issue",
            )
        )
        metadata_by_issue: dict[int, Mapping[str, object]] = {}
        for row_issue_id, metadata_json in result.all():
            if isinstance(metadata_json, dict):
                metadata_by_issue[row_issue_id] = metadata_json
        for candidate_issue_id in issue_id_order:
            evidence = publication_year_from_issue_metadata(
                metadata_by_issue.get(candidate_issue_id), reference_year=reference_year
            )
            if evidence is not None:
                issue_evidence = evidence
                break

    series_result = await db.execute(
        select(ExternalIdentity.metadata_json)
        .join(
            ThreadExternalSeriesMapping,
            ThreadExternalSeriesMapping.external_identity_id == ExternalIdentity.id,
        )
        .where(
            ThreadExternalSeriesMapping.thread_id == thread.id,
            ThreadExternalSeriesMapping.status == "confirmed",
            ExternalIdentity.provider == COMICVINE_PROVIDER,
            ExternalIdentity.entity_type == "series",
        )
        .order_by(ThreadExternalSeriesMapping.id.asc())
        .limit(1)
    )
    series_metadata = series_result.scalar()
    series_evidence = publication_year_from_series_metadata(
        series_metadata if isinstance(series_metadata, dict) else None,
        reference_year=reference_year,
    )

    return issue_evidence, series_evidence


async def reading_effort_estimate_for_thread(
    db: AsyncSession,
    thread: Thread,
    *,
    observed_issue_estimate: ReadingEffortEstimate | None = None,
    observed_thread_estimate: ReadingEffortEstimate | None = None,
    reference_year: int | None = None,
) -> ReadingEffortEstimate:
    """Resolve one thread's reading-effort estimate without ever raising.

    Any unexpected loader failure is logged and degraded to the neutral
    estimate so estimate problems can never block or alter a Roll.

    Args:
        db: Async database session.
        thread: Owned thread to resolve an estimate for.
        observed_issue_estimate: Issue-level observed estimate, if any.
        observed_thread_estimate: Thread-level observed estimate, if any.
        reference_year: Optional clock override used by tests.

    Returns:
        The resolved :class:`ReadingEffortEstimate`; neutral when nothing is
        known or the lookup fails.
    """
    try:
        issue_evidence, series_evidence = await load_publication_evidence(
            db, thread, reference_year=reference_year
        )
        return resolve_reading_effort(
            observed_issue_estimate=observed_issue_estimate,
            observed_thread_estimate=observed_thread_estimate,
            issue_evidence=issue_evidence,
            series_evidence=series_evidence,
            reference_year=reference_year,
        )
    except Exception:
        logger.warning(
            "reading_effort_era_lookup_failed thread_id=%s; returning neutral estimate",
            thread.id,
            exc_info=True,
        )
        return NEUTRAL_READING_EFFORT_ESTIMATE
