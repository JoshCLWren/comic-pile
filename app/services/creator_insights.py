"""Evidence-backed creator highlights for the personal creator detail page (#3092).

This module answers "what is actually driving the headline average?" with a
small, bounded set of highlights: the strongest, weakest, and most-rated
series/run plus the highest/lowest rated individual issues.

Product contract:

- Series conclusions require a minimum rated-issue sample and complete creator
  metadata, so a single 5★ issue never outranks a long consistently loved run,
  and a series whose counts are lower bounds is never presented as exhaustive.
- Individual issue extremes are a separate category from the aggregate series
  conclusions; a one-off rating is labeled as an individual issue, not "best
  work".
- Every ordering is deterministic: a total order over stable identities means
  tied highlights never arbitrarily disappear between requests.
- Every highlight carries the stable ids needed to drill into the supporting
  series or issue.

The computation is pure in-memory work over the already-loaded, user-scoped
:class:`~app.repositories.creator_summary.CreatorSummaryInputs` and the series
aggregates from :mod:`app.services.creator_series`, so it adds no query and no
per-thread fan-out.
"""

from __future__ import annotations

from app.repositories.creator_summary import CreatorSummaryInputs
from app.schemas.creator_detail import (
    CreatorInsights,
    CreatorIssueInsight,
    CreatorSeriesInsight,
)
from app.services.creator_series import (
    SeriesAggregate,
    build_series_group,
    creator_roles_on_issue,
)

#: Rated issues a series needs before it can be ranked strongest/weakest.
MIN_SERIES_SAMPLE: int = 3

#: Maximum individual issue extremes listed per direction.
INDIVIDUAL_ISSUE_LIMIT: int = 3

#: Plain-language explanation shown when no series comparison is available yet.
INSUFFICIENT_SERIES_MESSAGE: str = (
    "Not enough rated issues in a single series yet. A series needs at least "
    f"{MIN_SERIES_SAMPLE} rated issues before it is compared as strongest or weakest."
)


def _series_sort_key(thread_id: int) -> str:
    """Build the deterministic series tie-breaker used by the insight ordering.

    Args:
        thread_id: Local ComicPile thread (series/run) id.

    Returns:
        The stable ``thread:<thread_id>`` key used as the final tie-breaker.
    """
    return f"thread:{thread_id}"


def build_series_insight(aggregate: SeriesAggregate) -> CreatorSeriesInsight:
    """Convert one qualifying series aggregate into a serializable highlight.

    Args:
        aggregate: Accumulators for one creator within one thread. Callers only
            pass aggregates that already satisfy the minimum sample and
            metadata-completeness contract, so the nullable aggregate fields are
            guaranteed present here.

    Returns:
        The serializable series highlight.

    Raises:
        ValueError: When the aggregate is missing a rated sample or average.
    """
    average = aggregate.average_rating
    lowest = aggregate.lowest_rating
    highest = aggregate.highest_rating
    if not aggregate.rated_issue_ids or average is None or lowest is None or highest is None:
        raise ValueError("Series insight requires a rated, complete aggregate")
    group = build_series_group(aggregate)
    return CreatorSeriesInsight(
        series_key=group.series_key,
        thread_id=group.thread_id,
        thread_title=group.thread_title,
        rated_issue_count=group.rated_issue_count,
        average_rating=average,
        lowest_rating=lowest,
        highest_rating=highest,
        roles=group.roles,
        metadata_complete=group.metadata_complete,
        sort_key=_series_sort_key(group.thread_id),
    )


def compute_creator_insights(
    inputs: CreatorSummaryInputs,
    *,
    creator_id: int,
    rated_issue_ids: frozenset[int],
    series_aggregates: list[SeriesAggregate],
) -> CreatorInsights | None:
    """Compute evidence-backed highlights for one creator.

    Args:
        inputs: User-scoped creator summary inputs.
        creator_id: Stable external provider person id for the creator.
        rated_issue_ids: Headline-eligible rated issues, one per issue.
        series_aggregates: Deterministically ordered series/run aggregates from
            :func:`app.services.creator_series.aggregate_creator_series_groups`.

    Returns:
        The highlights, or ``None`` when the creator has no rated issues.
    """
    if not rated_issue_ids:
        return None

    qualifying = [
        aggregate
        for aggregate in series_aggregates
        if aggregate.metadata_complete
        and len(set(aggregate.rated_issue_ids) & rated_issue_ids) >= MIN_SERIES_SAMPLE
    ]
    excluded_incomplete = sum(
        1
        for aggregate in series_aggregates
        if not aggregate.metadata_complete and aggregate.rated_issue_ids
    )

    strongest = min(
        qualifying,
        key=lambda aggregate: (-(aggregate.average_rating or 0.0), _series_sort_key(aggregate.thread_id)),
        default=None,
    )
    weakest = min(
        qualifying,
        key=lambda aggregate: (aggregate.average_rating or 0.0, _series_sort_key(aggregate.thread_id)),
        default=None,
    )
    most_rated = min(
        qualifying,
        key=lambda aggregate: (
            -aggregate.rated_issue_count,
            _series_sort_key(aggregate.thread_id),
        ),
        default=None,
    )

    issue_insights = [
        CreatorIssueInsight(
            issue_id=issue_id,
            issue_number=inputs.owned_issue_series[issue_id].issue_number,
            thread_id=inputs.owned_issue_series[issue_id].thread_id,
            thread_title=inputs.owned_issue_series[issue_id].thread_title,
            effective_rating=inputs.effective_ratings[issue_id],
            roles=creator_roles_on_issue(inputs, creator_id=creator_id, issue_id=issue_id),
            sort_key=str(issue_id),
        )
        for issue_id in sorted(rated_issue_ids)
        if issue_id in inputs.owned_issue_series
    ]
    highest_rated = sorted(
        issue_insights,
        key=lambda insight: (-insight.effective_rating, insight.thread_id, insight.issue_id),
    )[:INDIVIDUAL_ISSUE_LIMIT]
    lowest_rated = sorted(
        issue_insights,
        key=lambda insight: (insight.effective_rating, insight.thread_id, insight.issue_id),
    )[:INDIVIDUAL_ISSUE_LIMIT]

    return CreatorInsights(
        min_series_sample=MIN_SERIES_SAMPLE,
        series_sample_met=bool(qualifying),
        series_message=None if qualifying else INSUFFICIENT_SERIES_MESSAGE,
        excluded_incomplete_series_count=excluded_incomplete,
        individual_issue_limit=INDIVIDUAL_ISSUE_LIMIT,
        strongest_series=build_series_insight(strongest) if strongest is not None else None,
        weakest_series=build_series_insight(weakest) if weakest is not None else None,
        most_rated_series=build_series_insight(most_rated) if most_rated is not None else None,
        highest_rated_issues=highest_rated,
        lowest_rated_issues=lowest_rated,
    )


__all__ = [
    "INDIVIDUAL_ISSUE_LIMIT",
    "INSUFFICIENT_SERIES_MESSAGE",
    "MIN_SERIES_SAMPLE",
    "build_series_insight",
    "compute_creator_insights",
]
