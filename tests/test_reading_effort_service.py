"""Unit tests for the async reading-effort service layer (issue #1703).

Covers the centralized era-prior logic, publication-year extraction,
effort resolution precedence, band mapping, confidence calculation,
neutral estimate, and recommendation-context payload construction.

These are pure-function unit tests that do not require a database.
"""

from app.services.reading_effort import (
    ERA_PRIOR_CLASSIC_MINUTES,
    ERA_PRIOR_CONFIDENCE,
    ERA_PRIOR_MODERN_MINUTES,
    ERA_PRIOR_TRANSITION_MINUTES,
    MAX_OBSERVED_CONFIDENCE,
    MIN_OBSERVED_SAMPLES,
    UNKNOWN_CONFIDENCE,
    EffortAggregate,
    EffortEstimate,
    EstimateSource,
    build_recommendation_context,
    classify_observation,
    era_prior_minutes,
    neutral_estimate,
    observed_confidence,
    publication_year_from_metadata,
    resolve_effort_band,
    resolve_effort_estimate,
)


# ---------------------------------------------------------------------------
# publication_year_from_metadata
# ---------------------------------------------------------------------------


class TestPublicationYearFromMetadata:
    """Extract a publication year from ComicVine-style metadata JSON."""

    def test_cover_date_yyyy_mm_dd(self) -> None:
        """Full date string returns the year."""
        assert publication_year_from_metadata({"cover_date": "2021-06-01"}) == 2021

    def test_cover_date_yyyy_mm(self) -> None:
        """Year-month string returns the year."""
        assert publication_year_from_metadata({"cover_date": "1995-03"}) == 1995

    def test_cover_date_yyyy(self) -> None:
        """Year-only string returns the year."""
        assert publication_year_from_metadata({"cover_date": "1968"}) == 1968

    def test_store_date_fallback(self) -> None:
        """Store date is used when cover date is absent."""
        assert publication_year_from_metadata({"store_date": "2010-11-15"}) == 2010

    def test_cover_date_preferred_over_store_date(self) -> None:
        """Cover date takes priority over store date."""
        metadata = {"cover_date": "2005-01-01", "store_date": "2005-02-01"}
        assert publication_year_from_metadata(metadata) == 2005

    def test_none_metadata_returns_none(self) -> None:
        """None metadata returns None."""
        assert publication_year_from_metadata(None) is None

    def test_empty_metadata_returns_none(self) -> None:
        """Empty dict returns None."""
        assert publication_year_from_metadata({}) is None

    def test_missing_date_fields_returns_none(self) -> None:
        """Metadata without date fields returns None."""
        assert publication_year_from_metadata({"title": "Example"}) is None

    def test_non_string_value_ignored(self) -> None:
        """Non-string date values are ignored."""
        assert publication_year_from_metadata({"cover_date": 2021}) is None

    def test_invalid_date_format_returns_none(self) -> None:
        """Unparseable date strings return None."""
        assert publication_year_from_metadata({"cover_date": "not-a-date"}) is None

    def test_year_outside_plausible_range_ignored(self) -> None:
        """Years outside 1900-2099 range are ignored by the regex."""
        assert publication_year_from_metadata({"cover_date": "1800-01-01"}) is None

    def test_cover_date_with_extra_text(self) -> None:
        """Year is extracted from text containing a plausible year."""
        assert publication_year_from_metadata({"cover_date": "Published 2015"}) == 2015


# ---------------------------------------------------------------------------
# era_prior_minutes
# ---------------------------------------------------------------------------


class TestEraPriorMinutes:
    """Map a publication year to its coarse era prior in minutes."""

    def test_classic_era_pre_1970(self) -> None:
        """Years before 1970 map to the classic era."""
        assert era_prior_minutes(1969) == ERA_PRIOR_CLASSIC_MINUTES
        assert era_prior_minutes(1940) == ERA_PRIOR_CLASSIC_MINUTES
        assert era_prior_minutes(1) == ERA_PRIOR_CLASSIC_MINUTES

    def test_transition_era_1970_to_1999(self) -> None:
        """Years 1970-1999 map to the transition era."""
        assert era_prior_minutes(1970) == ERA_PRIOR_TRANSITION_MINUTES
        assert era_prior_minutes(1985) == ERA_PRIOR_TRANSITION_MINUTES
        assert era_prior_minutes(1999) == ERA_PRIOR_TRANSITION_MINUTES

    def test_modern_era_2000_and_later(self) -> None:
        """Years 2000 and later map to the modern era."""
        assert era_prior_minutes(2000) == ERA_PRIOR_MODERN_MINUTES
        assert era_prior_minutes(2021) == ERA_PRIOR_MODERN_MINUTES
        assert era_prior_minutes(2099) == ERA_PRIOR_MODERN_MINUTES

    def test_none_year_returns_none(self) -> None:
        """None year returns None (no era applicable)."""
        assert era_prior_minutes(None) is None

    def test_boundary_1969_is_classic(self) -> None:
        """1969 is the upper bound of the classic era."""
        assert era_prior_minutes(1969) == ERA_PRIOR_CLASSIC_MINUTES

    def test_boundary_1970_is_transition(self) -> None:
        """1970 is the lower bound of the transition era."""
        assert era_prior_minutes(1970) == ERA_PRIOR_TRANSITION_MINUTES

    def test_boundary_1999_is_transition(self) -> None:
        """1999 is the upper bound of the transition era."""
        assert era_prior_minutes(1999) == ERA_PRIOR_TRANSITION_MINUTES

    def test_boundary_2000_is_modern(self) -> None:
        """2000 is the lower bound of the modern era."""
        assert era_prior_minutes(2000) == ERA_PRIOR_MODERN_MINUTES


# ---------------------------------------------------------------------------
# resolve_effort_band
# ---------------------------------------------------------------------------


class TestResolveEffortBand:
    """Map effort minutes to the documented band vocabulary."""

    def test_light_band(self) -> None:
        """Minutes below LIGHT_MAX_MINUTES map to light."""
        assert resolve_effort_band(0.0) == "light"
        assert resolve_effort_band(6.0) == "light"
        assert resolve_effort_band(11.99) == "light"

    def test_balanced_band(self) -> None:
        """Minutes between LIGHT_MAX and DEEP_MIN map to balanced."""
        assert resolve_effort_band(12.0) == "balanced"
        assert resolve_effort_band(15.0) == "balanced"
        assert resolve_effort_band(17.99) == "balanced"

    def test_deep_band(self) -> None:
        """Minutes at or above DEEP_MIN map to deep."""
        assert resolve_effort_band(18.0) == "deep"
        assert resolve_effort_band(25.0) == "deep"
        assert resolve_effort_band(100.0) == "deep"

    def test_unknown_band_for_none(self) -> None:
        """None minutes map to unknown band."""
        assert resolve_effort_band(None) == "unknown"


# ---------------------------------------------------------------------------
# observed_confidence
# ---------------------------------------------------------------------------


class TestObservedConfidence:
    """Confidence grows with sample count, capped at MAX_OBSERVED_CONFIDENCE."""

    def test_zero_samples(self) -> None:
        """Zero samples yield zero confidence."""
        assert observed_confidence(0) == UNKNOWN_CONFIDENCE

    def test_one_sample_below_minimum(self) -> None:
        """One sample below MIN_OBSERVED_SAMPLES yields zero confidence."""
        assert observed_confidence(1) == UNKNOWN_CONFIDENCE

    def test_minimum_samples_gets_base_confidence(self) -> None:
        """Minimum sample count yields base observed confidence."""
        confidence = observed_confidence(MIN_OBSERVED_SAMPLES)
        assert confidence > UNKNOWN_CONFIDENCE
        assert confidence <= MAX_OBSERVED_CONFIDENCE

    def test_grows_with_more_samples(self) -> None:
        """Confidence grows monotonically with sample count."""
        c2 = observed_confidence(2)
        c5 = observed_confidence(5)
        c10 = observed_confidence(10)
        assert c2 < c5 < c10

    def test_capped_at_max(self) -> None:
        """Confidence never exceeds MAX_OBSERVED_CONFIDENCE."""
        assert observed_confidence(100) == MAX_OBSERVED_CONFIDENCE


# ---------------------------------------------------------------------------
# neutral_estimate
# ---------------------------------------------------------------------------


class TestNeutralEstimate:
    """The safe default when nothing can be derived."""

    def test_neutral_has_no_minutes(self) -> None:
        """Neutral estimate has no minutes value."""
        estimate = neutral_estimate()
        assert estimate.minutes is None

    def test_neutral_is_unknown_source(self) -> None:
        """Neutral estimate uses UNKNOWN source."""
        estimate = neutral_estimate()
        assert estimate.source == EstimateSource.UNKNOWN

    def test_neutral_has_zero_confidence(self) -> None:
        """Neutral estimate has zero confidence."""
        estimate = neutral_estimate()
        assert estimate.confidence == UNKNOWN_CONFIDENCE

    def test_neutral_has_zero_sample_count(self) -> None:
        """Neutral estimate has zero sample count."""
        estimate = neutral_estimate()
        assert estimate.sample_count == 0

    def test_neutral_band_is_unknown(self) -> None:
        """Neutral estimate uses unknown band."""
        estimate = neutral_estimate()
        assert estimate.band == "unknown"


# ---------------------------------------------------------------------------
# resolve_effort_estimate
# ---------------------------------------------------------------------------


class TestResolveEffortEstimate:
    """Precedence chain: issue >= samples > thread >= samples > era > unknown."""

    def test_sufficient_issue_data_wins(self) -> None:
        """Sufficient issue history beats thread and era."""
        issue = EffortAggregate(minutes=10.0, sample_count=5)
        thread = EffortAggregate(minutes=20.0, sample_count=5)
        era = 15.0

        result = resolve_effort_estimate(issue, thread, era)
        assert result.source == EstimateSource.OBSERVED_ISSUE
        assert result.minutes == 10.0
        assert result.sample_count == 5

    def test_sufficient_thread_wins_over_era(self) -> None:
        """Sufficient thread history beats era prior."""
        thread = EffortAggregate(minutes=8.0, sample_count=3)
        era = 17.0

        result = resolve_effort_estimate(None, thread, era)
        assert result.source == EstimateSource.OBSERVED_THREAD
        assert result.minutes == 8.0

    def test_era_wins_when_no_observed_data(self) -> None:
        """Era prior is used when no observed history exists."""
        result = resolve_effort_estimate(None, None, 14.0)
        assert result.source == EstimateSource.ERA_PRIOR
        assert result.minutes == 14.0
        assert result.confidence == ERA_PRIOR_CONFIDENCE
        assert result.sample_count == 0

    def test_unknown_when_nothing_available(self) -> None:
        """Unknown estimate returned when no data or era exists."""
        result = resolve_effort_estimate(None, None, None)
        assert result.source == EstimateSource.UNKNOWN
        assert result.minutes is None
        assert result.confidence == UNKNOWN_CONFIDENCE

    def test_sparse_issue_does_not_beat_sufficient_thread(self) -> None:
        """Sparse issue history defers to sufficient thread history."""
        issue = EffortAggregate(minutes=10.0, sample_count=1)
        thread = EffortAggregate(minutes=20.0, sample_count=5)

        result = resolve_effort_estimate(issue, thread, None)
        assert result.source == EstimateSource.OBSERVED_THREAD
        assert result.minutes == 20.0

    def test_sparse_thread_with_era_fallback(self) -> None:
        """When both pools are sparse, era prior is used as fallback."""
        issue = EffortAggregate(minutes=10.0, sample_count=1)
        thread = EffortAggregate(minutes=20.0, sample_count=1)
        era = 17.0

        result = resolve_effort_estimate(issue, thread, era)
        assert result.source == EstimateSource.ERA_PRIOR
        assert result.minutes == 17.0

    def test_era_prior_has_zero_sample_count(self) -> None:
        """Era prior estimate has zero sample count."""
        result = resolve_effort_estimate(None, None, 17.0)
        assert result.sample_count == 0

    def test_era_prior_band_is_resolved(self) -> None:
        """Era prior minutes are mapped to the correct band."""
        result = resolve_effort_estimate(None, None, 10.0)
        assert result.band == "light"

        result_deep = resolve_effort_estimate(None, None, 20.0)
        assert result_deep.band == "deep"


# ---------------------------------------------------------------------------
# classify_observation
# ---------------------------------------------------------------------------


class TestClassifyObservation:
    """Duration observation classification against documented bounds."""

    def test_none_duration_is_missing_link(self) -> None:
        """None duration indicates a missing link."""
        valid, reason = classify_observation(None)
        assert valid is False
        assert reason is not None
        assert reason.value == "unlinked"

    def test_zero_duration_is_non_positive(self) -> None:
        """Zero duration is classified as non-positive."""
        valid, reason = classify_observation(0.0)
        assert valid is False
        assert reason is not None
        assert reason.value == "non_positive"

    def test_negative_duration_is_non_positive(self) -> None:
        """Negative duration is classified as non-positive."""
        valid, reason = classify_observation(-10.0)
        assert valid is False
        assert reason is not None
        assert reason.value == "non_positive"

    def test_valid_duration(self) -> None:
        """A normal duration is classified as valid."""
        valid, reason = classify_observation(300.0)
        assert valid is True
        assert reason is None


# ---------------------------------------------------------------------------
# build_recommendation_context
# ---------------------------------------------------------------------------


class TestBuildRecommendationContext:
    """Versioned decision-time context payload construction."""

    def test_context_has_version(self) -> None:
        """Context payload includes the version number."""
        estimate = EffortEstimate(
            minutes=12.0,
            band="balanced",
            source=EstimateSource.ERA_PRIOR,
            confidence=0.25,
            sample_count=0,
        )
        context = build_recommendation_context(
            estimate, thread_id=1, issue_id=2, issue_number="3"
        )
        assert context["context_version"] == 1

    def test_candidate_payload_fields(self) -> None:
        """Candidate payload contains all expected fields."""
        estimate = EffortEstimate(
            minutes=10.0,
            band="light",
            source=EstimateSource.OBSERVED_ISSUE,
            confidence=0.6,
            sample_count=3,
        )
        context = build_recommendation_context(
            estimate, thread_id=7, issue_id=11, issue_number="42"
        )
        candidate = context["selected_candidate"]
        assert candidate["thread_id"] == 7
        assert candidate["issue_id"] == 11
        assert candidate["issue_number"] == "42"
        assert candidate["effort_minutes"] == 10.0
        assert candidate["effort_band"] == "light"
        assert candidate["effort_source"] == "observed_issue"
        assert candidate["effort_confidence"] == 0.6
        assert candidate["effort_sample_count"] == 3

    def test_none_minutes_rounded_to_none(self) -> None:
        """None minutes remain None in the context payload."""
        estimate = neutral_estimate()
        context = build_recommendation_context(
            estimate, thread_id=1, issue_id=None, issue_number=None
        )
        candidate = context["selected_candidate"]
        assert candidate["effort_minutes"] is None
        assert candidate["effort_source"] == "unknown"
