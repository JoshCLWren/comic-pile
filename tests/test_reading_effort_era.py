"""Tests for the ComicVine publication-era reading-effort fallback (#1703)."""

from __future__ import annotations

from datetime import UTC, datetime

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import Issue, Thread, User
from app.models.external_identity import (
    ExternalIdentity,
    IssueExternalIdentityMapping,
    ThreadExternalSeriesMapping,
)
from app.services import reading_effort_era as era

REFERENCE_YEAR = 2026


def _observed(
    source: str,
    *,
    minutes: float = 25.0,
    samples: int,
) -> era.ReadingEffortEstimate:
    """Build an observed-source estimate with explicit provenance."""
    return era.ReadingEffortEstimate(
        minutes=minutes,
        band=era.effort_band_for_minutes(minutes),
        source=source,
        confidence=0.9,
        samples=samples,
    )


def test_effort_band_boundaries() -> None:
    """Light reads end below 12 minutes, balanced below 18, deep at 18 or more."""
    assert era.effort_band_for_minutes(0.5) == era.EFFORT_BAND_LIGHT
    assert era.effort_band_for_minutes(11.99) == era.EFFORT_BAND_LIGHT
    assert era.effort_band_for_minutes(12.0) == era.EFFORT_BAND_BALANCED
    assert era.effort_band_for_minutes(17.99) == era.EFFORT_BAND_BALANCED
    assert era.effort_band_for_minutes(18.0) == era.EFFORT_BAND_DEEP


@pytest.mark.parametrize(
    ("year", "expected_name"),
    [
        (1938, "golden_age"),
        (1955, "golden_age"),
        (1956, "silver_age"),
        (1969, "silver_age"),
        (1970, "bronze_age"),
        (1984, "bronze_age"),
        (1985, "copper_age"),
        (1996, "copper_age"),
        (1997, "modern"),
        (2026, "modern"),
        (2027, "modern"),
    ],
)
def test_era_bucket_boundaries(year: int, expected_name: str) -> None:
    """Every documented inclusive boundary maps onto its intended era bucket."""
    bucket = era.era_bucket_for_year(year, reference_year=REFERENCE_YEAR)
    assert bucket is not None
    assert bucket.name == expected_name


@pytest.mark.parametrize("year", [1899, 1937])
def test_era_bucket_unmapped_years_fail_to_neutral(year: int) -> None:
    """Pre-golden and pre-plausibility years stay unmapped instead of borrowing an era."""
    assert era.era_bucket_for_year(year, reference_year=REFERENCE_YEAR) is None


def test_era_bucket_future_ceiling_allows_one_solicited_year() -> None:
    """Only one future year beyond the reference clock remains plausible."""
    assert era.era_bucket_for_year(2027, reference_year=2026) is not None
    assert era.era_bucket_for_year(2028, reference_year=2026) is None


@pytest.mark.parametrize(
    ("bucket_name", "prior_minutes"),
    [
        ("golden_age", 14.0),
        ("silver_age", 13.0),
        ("bronze_age", 12.0),
        ("copper_age", 10.0),
        ("modern", 8.0),
    ],
)
def test_documented_priors_are_centralized(bucket_name: str, prior_minutes: float) -> None:
    """Each era bucket keeps exactly its documented median prior in minutes."""
    bucket = next(b for b in era.ERA_BUCKETS if b.name == bucket_name)
    assert bucket.prior_minutes == prior_minutes


@pytest.mark.parametrize(
    ("year", "basis", "expected_confidence"),
    [
        (1966, era.BASIS_ISSUE_COVER_DATE, era.CONFIDENCE_ISSUE_LEVEL_YEAR),
        (1966, era.BASIS_ISSUE_STORE_DATE, era.CONFIDENCE_ISSUE_LEVEL_YEAR),
        (1956, era.BASIS_SERIES_START_YEAR, era.CONFIDENCE_SERIES_LEVEL_YEAR),
    ],
)
def test_era_prior_estimate_bands_and_confidence(
    year: int,
    basis: str,
    expected_confidence: float,
) -> None:
    """Era priors derive band from prior minutes and confidence from evidence basis."""
    estimate = era.era_prior_estimate(
        era.PublicationEvidence(year=year, basis=basis), reference_year=REFERENCE_YEAR
    )
    bucket = era.era_bucket_for_year(year, reference_year=REFERENCE_YEAR)
    assert estimate.source == era.ESTIMATE_SOURCE_ERA_PRIOR
    assert estimate.confidence == expected_confidence
    assert bucket is not None
    assert estimate.minutes == bucket.prior_minutes
    assert estimate.band == era.effort_band_for_minutes(bucket.prior_minutes)


def test_era_prior_estimate_neutral_without_evidence() -> None:
    """Missing evidence degrades to the shared neutral estimate."""
    assert (
        era.era_prior_estimate(None, reference_year=REFERENCE_YEAR)
        is era.NEUTRAL_READING_EFFORT_ESTIMATE
    )


def test_era_prior_estimate_neutral_for_plausible_but_unmapped_year() -> None:
    """A plausible year before every documented bucket fails to neutral."""
    evidence = era.PublicationEvidence(year=1920, basis=era.BASIS_ISSUE_COVER_DATE)
    assert (
        era.era_prior_estimate(evidence, reference_year=REFERENCE_YEAR)
        is era.NEUTRAL_READING_EFFORT_ESTIMATE
    )


def test_issue_metadata_prefers_cover_date_over_store_date() -> None:
    """The cover date wins when both confirmed issue dates parse."""
    evidence = era.publication_year_from_issue_metadata(
        {"cover_date": "July, 1966", "store_date": "1966-06-01"},
        reference_year=REFERENCE_YEAR,
    )
    assert evidence == era.PublicationEvidence(
        year=1966, basis=era.BASIS_ISSUE_COVER_DATE
    )


def test_issue_metadata_falls_back_to_store_date() -> None:
    """A missing or unusable cover date defers to a plausible store date."""
    missing_cover = era.publication_year_from_issue_metadata(
        {"store_date": "1966-06-01"},
        reference_year=REFERENCE_YEAR,
    )
    garbage_cover = era.publication_year_from_issue_metadata(
        {"cover_date": "unknown", "store_date": "June 1966"},
        reference_year=REFERENCE_YEAR,
    )
    implausible_cover = era.publication_year_from_issue_metadata(
        {"cover_date": "January, 3021", "store_date": "1972-03-00"},
        reference_year=REFERENCE_YEAR,
    )
    assert missing_cover == era.PublicationEvidence(
        year=1966, basis=era.BASIS_ISSUE_STORE_DATE
    )
    assert garbage_cover == era.PublicationEvidence(
        year=1966, basis=era.BASIS_ISSUE_STORE_DATE
    )
    assert implausible_cover == era.PublicationEvidence(
        year=1972, basis=era.BASIS_ISSUE_STORE_DATE
    )


@pytest.mark.parametrize(
    "metadata",
    [
        None,
        "not-a-mapping",
        ["nope"],
        {},
        {"cover_date": None, "store_date": ""},
        {"cover_date": "1899"},
        {"cover_date": 1966},
        {"start_year": 1966},
    ],
)
def test_issue_metadata_rejects_garbage(metadata: object) -> None:
    """Garbage, non-string, and implausible issue metadata yield no evidence."""
    assert (
        era.publication_year_from_issue_metadata(metadata, reference_year=REFERENCE_YEAR) is None
    )


@pytest.mark.parametrize(
    ("start_year", "expected_year"),
    [(1956, 1956), ("1956", 1956), (" 1966 ", 1966)],
)
def test_series_start_year_accepts_int_and_numeric_strings(
    start_year: object,
    expected_year: int,
) -> None:
    """Confirmed series start years accept ints and numeric strings."""
    evidence = era.publication_year_from_series_metadata(
        {"start_year": start_year}, reference_year=REFERENCE_YEAR
    )
    assert evidence == era.PublicationEvidence(
        year=expected_year, basis=era.BASIS_SERIES_START_YEAR
    )


@pytest.mark.parametrize("start_year", [False, True, 3.5, "nineteen fifty-six", 1899, None])
def test_series_start_year_rejects_bools_and_garbage(start_year: object) -> None:
    """Booleans, floats, prose, and implausible start years yield no evidence."""
    assert (
        era.publication_year_from_series_metadata(
            {"start_year": start_year}, reference_year=REFERENCE_YEAR
        )
        is None
    )


@pytest.mark.parametrize("metadata", [None, 1956, ["start_year"]])
def test_series_metadata_rejects_non_mapping(metadata: object) -> None:
    """Missing or non-mapping series metadata yields no evidence."""
    assert (
        era.publication_year_from_series_metadata(metadata, reference_year=REFERENCE_YEAR) is None
    )


def test_neutral_estimate_is_fully_neutral() -> None:
    """The neutral singleton carries no minutes, band, confidence, or samples."""
    neutral = era.NEUTRAL_READING_EFFORT_ESTIMATE
    assert neutral.minutes is None
    assert neutral.band is None
    assert neutral.confidence is None
    assert neutral.samples is None
    assert neutral.source == era.ESTIMATE_SOURCE_UNKNOWN


def test_estimate_rejects_invalid_core_fields() -> None:
    """Invalid sources, bands, minutes, and confidence values are rejected."""
    with pytest.raises(ValueError):
        era.ReadingEffortEstimate(
            minutes=10.0,
            band=era.EFFORT_BAND_LIGHT,
            source="mystery_source",
            confidence=0.5,
        )
    with pytest.raises(ValueError):
        era.ReadingEffortEstimate(
            minutes=None,
            band=None,
            source=era.ESTIMATE_SOURCE_ERA_PRIOR,
            confidence=None,
        )
    with pytest.raises(ValueError):
        era.ReadingEffortEstimate(
            minutes=10.0,
            band="bogus",
            source=era.ESTIMATE_SOURCE_ERA_PRIOR,
            confidence=0.3,
        )
    with pytest.raises(ValueError):
        era.ReadingEffortEstimate(
            minutes=-1.0,
            band=era.EFFORT_BAND_LIGHT,
            source=era.ESTIMATE_SOURCE_ERA_PRIOR,
            confidence=0.3,
        )
    with pytest.raises(ValueError):
        era.ReadingEffortEstimate(
            minutes=10.0,
            band=era.EFFORT_BAND_LIGHT,
            source=era.ESTIMATE_SOURCE_ERA_PRIOR,
            confidence=1.5,
        )


def test_estimate_unknown_source_must_be_fully_neutral() -> None:
    """An unknown-source estimate cannot smuggle in real values."""
    with pytest.raises(ValueError):
        era.ReadingEffortEstimate(
            minutes=None,
            band=None,
            source=era.ESTIMATE_SOURCE_UNKNOWN,
            confidence=0.5,
        )


def test_estimate_samples_require_observed_source_and_positive_count() -> None:
    """Sample counts only exist for observed sources with at least one observation."""
    with pytest.raises(ValueError):
        era.ReadingEffortEstimate(
            minutes=13.0,
            band=era.EFFORT_BAND_BALANCED,
            source=era.ESTIMATE_SOURCE_ERA_PRIOR,
            confidence=0.3,
            samples=4,
        )
    with pytest.raises(ValueError):
        _observed(era.ESTIMATE_SOURCE_OBSERVED_THREAD, samples=0)


def test_resolve_observed_issue_beats_era_prior() -> None:
    """Sufficiently-sampled observed effort always outranks publication-era priors."""
    observed = _observed(era.ESTIMATE_SOURCE_OBSERVED_ISSUE, samples=3)
    issue_evidence = era.PublicationEvidence(year=1966, basis=era.BASIS_ISSUE_COVER_DATE)
    resolved = era.resolve_reading_effort(
        observed_issue_estimate=observed,
        issue_evidence=issue_evidence,
        series_evidence=era.PublicationEvidence(year=1956, basis=era.BASIS_SERIES_START_YEAR),
        reference_year=REFERENCE_YEAR,
    )
    assert resolved is observed


def test_resolve_requires_minimum_observed_samples() -> None:
    """Observed estimates below the documented sample floor fall through to the era prior."""
    sparse = _observed(
        era.ESTIMATE_SOURCE_OBSERVED_ISSUE,
        samples=era.MIN_OBSERVED_EFFORT_SAMPLES - 1,
    )
    issue_evidence = era.PublicationEvidence(year=1987, basis=era.BASIS_ISSUE_COVER_DATE)
    resolved = era.resolve_reading_effort(
        observed_issue_estimate=sparse,
        issue_evidence=issue_evidence,
        reference_year=REFERENCE_YEAR,
    )
    assert resolved.source == era.ESTIMATE_SOURCE_ERA_PRIOR
    assert resolved.minutes == 10.0


def test_resolve_thread_observed_backfills_insufficient_issue_history() -> None:
    """Thread-level observations fill in when the issue slot lacks enough samples."""
    sparse_issue = _observed(era.ESTIMATE_SOURCE_OBSERVED_ISSUE, samples=1)
    thread_observed = _observed(era.ESTIMATE_SOURCE_OBSERVED_THREAD, samples=4, minutes=30.0)
    resolved = era.resolve_reading_effort(
        observed_issue_estimate=sparse_issue,
        observed_thread_estimate=thread_observed,
        reference_year=REFERENCE_YEAR,
    )
    assert resolved is thread_observed


def test_resolve_issue_level_prior_beats_series_level_prior() -> None:
    """A confirmed issue date is more specific than any series start year."""
    issue_evidence = era.PublicationEvidence(year=1987, basis=era.BASIS_ISSUE_COVER_DATE)
    series_evidence = era.PublicationEvidence(year=1956, basis=era.BASIS_SERIES_START_YEAR)
    resolved = era.resolve_reading_effort(
        issue_evidence=issue_evidence,
        series_evidence=series_evidence,
        reference_year=REFERENCE_YEAR,
    )
    assert resolved.source == era.ESTIMATE_SOURCE_ERA_PRIOR
    assert resolved.minutes == 10.0
    assert resolved.confidence == era.CONFIDENCE_ISSUE_LEVEL_YEAR


def test_resolve_ignores_non_observed_sources_in_observed_slots() -> None:
    """Slots define precedence, not identity: era-prior values in observed slots are ignored."""
    misplaced = era.ReadingEffortEstimate(
        minutes=13.0,
        band=era.EFFORT_BAND_BALANCED,
        source=era.ESTIMATE_SOURCE_ERA_PRIOR,
        confidence=0.3,
    )
    resolved = era.resolve_reading_effort(
        observed_issue_estimate=misplaced,
        reference_year=REFERENCE_YEAR,
    )
    assert resolved is era.NEUTRAL_READING_EFFORT_ESTIMATE


def test_resolve_returns_neutral_when_nothing_is_usable() -> None:
    """No evidence anywhere resolves to the shared neutral estimate."""
    resolved = era.resolve_reading_effort(reference_year=REFERENCE_YEAR)
    assert resolved is era.NEUTRAL_READING_EFFORT_ESTIMATE


async def _thread_with_issues(
    db: AsyncSession,
    *,
    username: str,
    issue_count: int = 2,
) -> tuple[User, Thread, list[Issue]]:
    """Create one owned thread with unread issues in stable queue order."""
    user = User(username=username)
    db.add(user)
    await db.flush()
    thread = Thread(
        title="Era fallback test series",
        format="Comic",
        issues_remaining=issue_count,
        total_issues=issue_count,
        queue_position=1,
        status="active",
        user_id=user.id,
    )
    db.add(thread)
    await db.flush()
    issues: list[Issue] = []
    for position in range(1, issue_count + 1):
        issue = Issue(
            thread_id=thread.id,
            issue_number=str(position),
            position=position,
            status="unread",
        )
        db.add(issue)
        issues.append(issue)
    await db.flush()
    return user, thread, issues


async def _confirm_issue_identity(
    db: AsyncSession,
    issue: Issue,
    *,
    external_id: str,
    metadata_json: dict[str, object],
) -> ExternalIdentity:
    """Attach one confirmed ComicVine issue identity to an issue."""
    identity = ExternalIdentity(
        provider=era.COMICVINE_PROVIDER,
        entity_type="issue",
        external_id=external_id,
        metadata_json=metadata_json,
        updated_at=datetime.now(UTC),
    )
    db.add(identity)
    await db.flush()
    db.add(
        IssueExternalIdentityMapping(
            issue_id=issue.id,
            external_identity_id=identity.id,
            status="confirmed",
            confidence=1.0,
        )
    )
    await db.flush()
    return identity


@pytest.mark.asyncio
async def test_load_publication_evidence_prefers_next_unread_issue(
    async_db: AsyncSession,
) -> None:
    """Issue-level evidence comes from the next unread issue before queue order."""
    _user, thread, issues = await _thread_with_issues(async_db, username="era_next_unread")
    await _confirm_issue_identity(
        async_db,
        issues[0],
        external_id="cv-era-first",
        metadata_json={"cover_date": "May, 1954"},
    )
    await _confirm_issue_identity(
        async_db,
        issues[1],
        external_id="cv-era-next",
        metadata_json={"cover_date": "June, 1987"},
    )
    thread.next_unread_issue_id = issues[1].id
    await async_db.flush()

    issue_evidence, series_evidence = await era.load_publication_evidence(
        async_db, thread, reference_year=REFERENCE_YEAR
    )

    assert series_evidence is None
    assert issue_evidence == era.PublicationEvidence(
        year=1987, basis=era.BASIS_ISSUE_COVER_DATE
    )

    estimate = await era.reading_effort_estimate_for_thread(
        async_db, thread, reference_year=REFERENCE_YEAR
    )
    assert estimate.source == era.ESTIMATE_SOURCE_ERA_PRIOR
    assert estimate.minutes == 10.0
    assert estimate.band == era.EFFORT_BAND_LIGHT
    assert estimate.confidence == era.CONFIDENCE_ISSUE_LEVEL_YEAR


@pytest.mark.asyncio
async def test_load_publication_evidence_ignores_candidate_and_foreign_mappings(
    async_db: AsyncSession,
) -> None:
    """Only confirmed ComicVine mappings count as publication evidence."""
    _user, thread, issues = await _thread_with_issues(
        async_db, username="era_candidate_only"
    )
    candidate_identity = ExternalIdentity(
        provider=era.COMICVINE_PROVIDER,
        entity_type="issue",
        external_id="cv-era-candidate",
        metadata_json={"cover_date": "June, 1987"},
        updated_at=datetime.now(UTC),
    )
    foreign_identity = ExternalIdentity(
        provider="metron",
        entity_type="issue",
        external_id="mt-era-foreign",
        metadata_json={"cover_date": "June, 1987"},
        updated_at=datetime.now(UTC),
    )
    async_db.add_all([candidate_identity, foreign_identity])
    await async_db.flush()
    async_db.add_all(
        [
            IssueExternalIdentityMapping(
                issue_id=issues[0].id,
                external_identity_id=candidate_identity.id,
                status="candidate",
            ),
            IssueExternalIdentityMapping(
                issue_id=issues[1].id,
                external_identity_id=foreign_identity.id,
                status="confirmed",
            ),
        ]
    )
    await async_db.flush()

    issue_evidence, series_evidence = await era.load_publication_evidence(
        async_db, thread, reference_year=REFERENCE_YEAR
    )

    assert issue_evidence is None
    assert series_evidence is None


@pytest.mark.asyncio
async def test_series_start_year_provides_low_confidence_prior(
    async_db: AsyncSession,
) -> None:
    """A confirmed series mapping yields a series-level era prior when no issue date exists."""
    _user, thread, _issues = await _thread_with_issues(async_db, username="era_series_only")
    identity = ExternalIdentity(
        provider=era.COMICVINE_PROVIDER,
        entity_type="series",
        external_id="cv-era-series",
        metadata_json={"start_year": "1956"},
        updated_at=datetime.now(UTC),
    )
    async_db.add(identity)
    await async_db.flush()
    async_db.add(
        ThreadExternalSeriesMapping(
            thread_id=thread.id,
            external_identity_id=identity.id,
            status="confirmed",
        )
    )
    await async_db.flush()

    issue_evidence, series_evidence = await era.load_publication_evidence(
        async_db, thread, reference_year=REFERENCE_YEAR
    )

    assert issue_evidence is None
    assert series_evidence == era.PublicationEvidence(
        year=1956, basis=era.BASIS_SERIES_START_YEAR
    )

    estimate = await era.reading_effort_estimate_for_thread(
        async_db, thread, reference_year=REFERENCE_YEAR
    )
    assert estimate.source == era.ESTIMATE_SOURCE_ERA_PRIOR
    assert estimate.minutes == 13.0
    assert estimate.band == era.EFFORT_BAND_BALANCED
    assert estimate.confidence == era.CONFIDENCE_SERIES_LEVEL_YEAR


@pytest.mark.asyncio
async def test_observed_estimate_overrides_loaded_era_prior(
    async_db: AsyncSession,
) -> None:
    """Observed user-specific effort takes precedence over DB-derived era priors."""
    _user, thread, issues = await _thread_with_issues(async_db, username="era_observed_wins")
    await _confirm_issue_identity(
        async_db,
        issues[0],
        external_id="cv-era-observed",
        metadata_json={"cover_date": "June, 1987"},
    )
    thread.next_unread_issue_id = issues[0].id
    await async_db.flush()

    observed = _observed(era.ESTIMATE_SOURCE_OBSERVED_ISSUE, samples=5)
    estimate = await era.reading_effort_estimate_for_thread(
        async_db,
        thread,
        observed_issue_estimate=observed,
        reference_year=REFERENCE_YEAR,
    )

    assert estimate is observed


@pytest.mark.asyncio
async def test_reading_effort_estimate_for_thread_never_raises(
    async_db: AsyncSession,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Loader failures degrade to the neutral estimate instead of reaching the Roll path."""

    async def _explode(db: AsyncSession, thread: Thread, **kwargs: object) -> tuple[None, None]:
        raise RuntimeError("simulated loader outage")

    monkeypatch.setattr(era, "load_publication_evidence", _explode)

    _user, thread, _issues = await _thread_with_issues(async_db, username="era_failure_path")
    estimate = await era.reading_effort_estimate_for_thread(
        async_db, thread, reference_year=REFERENCE_YEAR
    )

    assert estimate is era.NEUTRAL_READING_EFFORT_ESTIMATE


@pytest.mark.asyncio
async def test_missing_metadata_yields_neutral_estimate(async_db: AsyncSession) -> None:
    """Threads without any confirmed external metadata resolve to neutral."""
    _user, thread, _issues = await _thread_with_issues(
        async_db, username="era_no_metadata"
    )

    estimate = await era.reading_effort_estimate_for_thread(
        async_db, thread, reference_year=REFERENCE_YEAR
    )

    assert estimate is era.NEUTRAL_READING_EFFORT_ESTIMATE
