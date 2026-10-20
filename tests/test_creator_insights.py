"""Focused unit coverage for the pure creator insight computation (issue #3092).

These tests exercise the highlight ordering, minimum-sample gate, incomplete
metadata exclusion, individual-issue separation, and deterministic tie-breaking
without a database, so they run in every environment.
"""

from __future__ import annotations

from app.repositories.creator_summary import (
    CreatorCredit,
    CreatorSummaryInputs,
    OwnedIssueSeries,
)
from app.schemas.creator_detail import CreatorInsights
from app.services.creator_insights import (
    INDIVIDUAL_ISSUE_LIMIT,
    INSUFFICIENT_SERIES_MESSAGE,
    MIN_SERIES_SAMPLE,
    compute_creator_insights,
)
from app.services.creator_series import aggregate_creator_series_groups


def _build_inputs(
    *,
    creator_id: int,
    rated: dict[int, float],
    series: dict[int, tuple[int, str]],
    credited: frozenset[int] | None = None,
    complete: frozenset[int] | None = None,
    roles: dict[int, tuple[str, ...]] | None = None,
) -> CreatorSummaryInputs:
    """Build summary inputs from simple issue/thread/rating maps.

    Args:
        creator_id: Stable external creator id credited on every issue.
        rated: Mapping of issue id to effective rating.
        series: Mapping of issue id to ``(thread_id, thread_title)``.
        credited: Issue ids credited to the creator; defaults to every issue.
        complete: Issue ids with confirmed creator metadata; defaults to every issue.
        roles: Mapping of issue id to the creator's roles on that issue;
            defaults to a single ``writer`` credit per credited issue.

    Returns:
        User-scoped inputs suitable for the series aggregator.
    """
    credited_ids = credited if credited is not None else frozenset(series)
    complete_ids = complete if complete is not None else frozenset(series)
    issue_roles = roles or {}
    return CreatorSummaryInputs(
        owned_issues=dict.fromkeys(series, "read"),
        owned_issue_series={
            issue_id: OwnedIssueSeries(
                thread_id=thread_id,
                thread_title=thread_title,
                issue_number=str(issue_id),
            )
            for issue_id, (thread_id, thread_title) in series.items()
        },
        issue_creator_credits={
            issue_id: (
                CreatorCredit(
                    external_id=creator_id,
                    roles=issue_roles.get(issue_id, ("writer",)),
                    display_name="Insight Ivy",
                ),
            )
            for issue_id in credited_ids
        },
        issues_with_creator_metadata=frozenset(complete_ids),
        effective_ratings=dict(rated),
        effective_rating_timestamps={},
    )


def _insights(
    *,
    creator_id: int,
    rated: dict[int, float],
    series: dict[int, tuple[int, str]],
    credited: frozenset[int] | None = None,
    complete: frozenset[int] | None = None,
    roles: dict[int, tuple[str, ...]] | None = None,
    headline: frozenset[int] | None = None,
) -> CreatorInsights | None:
    """Compute insights for one synthetic creator library.

    ``rated`` holds every effective rating, while ``headline`` holds the
    headline-eligible subset (issues the creator holds a headline role on).
    It defaults to every rated issue, which is the all-writer case.
    """
    inputs = _build_inputs(
        creator_id=creator_id,
        rated=rated,
        series=series,
        credited=credited,
        complete=complete,
        roles=roles,
    )
    aggregates = aggregate_creator_series_groups(
        inputs,
        creator_id=creator_id,
        creator_issue_ids=frozenset(series),
    )
    return compute_creator_insights(
        inputs,
        creator_id=creator_id,
        rated_issue_ids=frozenset(rated) if headline is None else headline,
        series_aggregates=aggregates,
    )


def test_no_rated_issues_returns_no_insights() -> None:
    """A creator with no eligible ratings has no highlights section at all."""
    insights = _insights(creator_id=1, rated={}, series={})
    assert insights is None


def test_series_highlights_rank_and_require_minimum_sample() -> None:
    """Strongest, weakest, and most-rated use only series clearing the sample gate."""
    series = {
        11: (1, "Strong"),
        12: (1, "Strong"),
        13: (1, "Strong"),
        21: (2, "Weak"),
        22: (2, "Weak"),
        23: (2, "Weak"),
        31: (3, "Long"),
        32: (3, "Long"),
        33: (3, "Long"),
        34: (3, "Long"),
        41: (4, "Thin"),
        42: (4, "Thin"),
    }
    rated = {
        11: 5.0,
        12: 5.0,
        13: 5.0,
        21: 1.0,
        22: 1.0,
        23: 1.0,
        31: 3.0,
        32: 3.0,
        33: 3.0,
        34: 3.0,
        41: 5.0,
        42: 5.0,
    }

    insights = _insights(creator_id=9, rated=rated, series=series)

    assert insights is not None
    assert insights.min_series_sample == MIN_SERIES_SAMPLE == 3
    assert insights.series_sample_met is True
    assert insights.series_message is None
    assert insights.strongest_series is not None
    assert insights.strongest_series.thread_title == "Strong"
    assert insights.strongest_series.average_rating == 5.0
    assert insights.weakest_series is not None
    assert insights.weakest_series.thread_title == "Weak"
    assert insights.most_rated_series is not None
    assert insights.most_rated_series.thread_title == "Long"
    assert insights.most_rated_series.rated_issue_count == 4


def test_series_ties_break_deterministically_by_series_key() -> None:
    """Equal series resolve to the smallest stable series key, stably."""
    series = {11: (1, "Tie A"), 12: (1, "Tie A"), 13: (1, "Tie A"),
              21: (2, "Tie B"), 22: (2, "Tie B"), 23: (2, "Tie B")}
    rated = {11: 4.0, 12: 4.0, 13: 4.0, 21: 4.0, 22: 4.0, 23: 4.0}

    first = _insights(creator_id=9, rated=rated, series=series)
    second = _insights(creator_id=9, rated=rated, series=series)

    assert first is not None and second is not None
    assert first.strongest_series is not None
    assert first.strongest_series.series_key == "thread:1"
    assert first.weakest_series is not None
    assert first.weakest_series.series_key == "thread:1"
    assert first.most_rated_series is not None
    assert first.most_rated_series.series_key == "thread:1"
    assert second.strongest_series is not None
    assert first.strongest_series.series_key == second.strongest_series.series_key


def test_incomplete_metadata_series_is_excluded_and_flagged() -> None:
    """A series whose counts are lower bounds is never ranked as strongest."""
    series = {
        11: (1, "Patchy"),
        12: (1, "Patchy"),
        13: (1, "Patchy"),
        14: (1, "Patchy"),
    }
    rated = {11: 5.0, 12: 5.0, 13: 5.0}

    insights = _insights(
        creator_id=9,
        rated=rated,
        series=series,
        credited=frozenset({11, 12, 13}),
        complete=frozenset({11, 12, 13}),
    )

    assert insights is not None
    assert insights.series_sample_met is False
    assert insights.excluded_incomplete_series_count == 1
    assert insights.strongest_series is None
    assert insights.series_message == INSUFFICIENT_SERIES_MESSAGE


def test_thin_series_sample_explains_instead_of_ranking() -> None:
    """A two-issue series cannot define strongest/weakest; the message explains why."""
    series = {11: (1, "Thin"), 12: (1, "Thin")}
    rated = {11: 5.0, 12: 5.0}

    insights = _insights(creator_id=9, rated=rated, series=series)

    assert insights is not None
    assert insights.series_sample_met is False
    assert insights.series_message == INSUFFICIENT_SERIES_MESSAGE
    assert insights.highest_rated_issues
    assert insights.lowest_rated_issues


def test_individual_issue_extremes_are_sorted_capped_and_distinct() -> None:
    """Issue extremes are ordered, capped, and separate from series conclusions."""
    series = {11: (1, "Run"), 12: (1, "Run"), 13: (1, "Run"), 14: (1, "Run"), 15: (1, "Run")}
    rated = {11: 5.0, 12: 4.0, 13: 3.0, 14: 2.0, 15: 1.0}

    insights = _insights(creator_id=9, rated=rated, series=series)

    assert insights is not None
    assert len(insights.highest_rated_issues) == INDIVIDUAL_ISSUE_LIMIT == 3
    assert [row.effective_rating for row in insights.highest_rated_issues] == [5.0, 4.0, 3.0]
    assert [row.effective_rating for row in insights.lowest_rated_issues] == [1.0, 2.0, 3.0]
    assert insights.highest_rated_issues[0].thread_title == "Run"
    assert insights.highest_rated_issues[0].roles == ["writer"]


def test_mixed_role_series_ignores_cover_only_ratings() -> None:
    """A cover-only rating never enters the series count, average, or extremes.

    Regression coverage for the mixed-role fix: the creator writes three
    issues and only drew the cover of a fourth, so the series highlight must
    describe the three headline-eligible issues, not all four rated ones.
    """
    series = {
        11: (1, "Mixed Roles"),
        12: (1, "Mixed Roles"),
        13: (1, "Mixed Roles"),
        14: (1, "Mixed Roles"),
    }
    rated = {11: 5.0, 12: 4.0, 13: 3.0, 14: 1.0}
    roles = {11: ("writer",), 12: ("writer",), 13: ("writer",), 14: ("cover",)}

    insights = _insights(
        creator_id=9,
        rated=rated,
        series=series,
        roles=roles,
        headline=frozenset({11, 12, 13}),
    )

    assert insights is not None
    assert insights.series_sample_met is True
    assert insights.series_message is None
    assert insights.strongest_series is not None
    assert insights.strongest_series.thread_title == "Mixed Roles"
    assert insights.strongest_series.rated_issue_count == 3
    assert insights.strongest_series.average_rating == 4.0
    assert insights.strongest_series.lowest_rating == 3.0
    assert insights.strongest_series.highest_rating == 5.0
    assert insights.weakest_series is not None
    assert insights.weakest_series.rated_issue_count == 3
    assert insights.weakest_series.average_rating == 4.0
    assert insights.weakest_series.lowest_rating == 3.0
    assert insights.weakest_series.highest_rating == 5.0
    assert insights.most_rated_series is not None
    assert insights.most_rated_series.rated_issue_count == 3
    # The roles the creator held in the series stay truthful even though the
    # cover-only rating is excluded from the numbers.
    assert insights.strongest_series.roles == ["cover", "writer"]
    # The cover-only issue is not part of the individual issue evidence either.
    assert [row.issue_id for row in insights.highest_rated_issues] == [11, 12, 13]
    assert [row.issue_id for row in insights.lowest_rated_issues] == [13, 12, 11]


def test_cover_only_ratings_cannot_reach_the_series_sample_gate() -> None:
    """Cover-only ratings never push a series over the minimum sample gate.

    Regression coverage for the mixed-role fix: two headline-eligible issues
    plus two cover-only ones are four rated issues, but only two of them may
    count toward the series comparison, so the series stays unranked.
    """
    series = {
        11: (1, "Patchy Roles"),
        12: (1, "Patchy Roles"),
        13: (1, "Patchy Roles"),
        14: (1, "Patchy Roles"),
    }
    rated = {11: 5.0, 12: 4.0, 13: 1.0, 14: 1.0}
    roles = {11: ("writer",), 12: ("writer",), 13: ("cover",), 14: ("cover",)}

    insights = _insights(
        creator_id=9,
        rated=rated,
        series=series,
        roles=roles,
        headline=frozenset({11, 12}),
    )

    assert insights is not None
    assert insights.series_sample_met is False
    assert insights.series_message == INSUFFICIENT_SERIES_MESSAGE
    assert insights.strongest_series is None
    assert insights.weakest_series is None
    assert insights.most_rated_series is None
    assert [row.issue_id for row in insights.highest_rated_issues] == [11, 12]
    assert [row.issue_id for row in insights.lowest_rated_issues] == [12, 11]
