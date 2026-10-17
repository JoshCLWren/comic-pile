"""Service for the bounded personal creator-team chemistry API (issue #3094).

A "team" is a pair of stable canonical creator identities credited together on
eligible ComicPile issues. Pairing reuses the canonical creator identity and
rating semantics of #2028/#2037 rather than inventing a second identity or
rating system:

- creators are canonical identities (``creator:<external-id>``), so same-name
  creators always remain distinct;
- only interior-storytelling roles (:data:`TEAM_ELIGIBLE_ROLES`) may define a
  pair, so editorial, cover, and lettering credits do not explode the pairwise
  set into noise;
- a pair's shared sample is derived only from actual shared rated issues;
- every average carries its sample size and baseline context;
- incomplete creator metadata is reported as partial coverage, never as
  negative evidence.

All results are descriptive personal-reading data. Nothing in this service or
its response schema implies causation or statistical significance.
"""

from __future__ import annotations

from collections import defaultdict
from statistics import median

from sqlalchemy.ext.asyncio import AsyncSession

from app.constants import MIN_SHARED_TEAM_SAMPLE
from app.repositories.creator_team_chemistry import (
    CreatorTeamChemistryInputs,
    load_creator_team_chemistry_inputs,
)
from app.schemas.creator_team_chemistry import (
    MAX_RANKED_TEAM_PAIRS,
    MAX_SHARED_ISSUE_REFS,
    MAX_SHARED_SERIES,
    CreatorTeamChemistryResponse,
    CreatorTeamCoverage,
    CreatorTeamIssueRef,
    CreatorTeamMember,
    CreatorTeamPair,
    CreatorTeamSeriesRef,
)


def canonical_creator_key(creator_id: int) -> str:
    """Return the stable canonical creator key for one identity id.

    Args:
        creator_id: External person id (or reserved manual-band id).

    Returns:
        The shared ``creator:<id>`` canonical key format.
    """
    return f"creator:{creator_id}"


def _role_labels(
    inputs: CreatorTeamChemistryInputs,
    issue_ids: set[int],
    creator_id: int,
) -> list[str]:
    """Collect one creator's eligible interior roles across the pair's issues.

    Args:
        inputs: Loaded team-chemistry inputs.
        issue_ids: The pair's shared issue ids.
        creator_id: Creator whose roles are collected.

    Returns:
        Sorted distinct role labels.
    """
    roles: set[str] = set()
    for issue_id in issue_ids:
        members = inputs.eligible_issue_creators.get(issue_id)
        if members is None:
            continue
        roles |= members.get(creator_id, frozenset())
    return sorted(roles)


def _distribution(ratings: list[float]) -> dict[str, int]:
    """Bucket shared effective ratings into the display distribution.

    Args:
        ratings: Effective ratings of the pair's shared issues.

    Returns:
        Mapping of rating text to count, keyed exactly like the comparison API.
    """
    counts: dict[str, int] = defaultdict(int)
    for rating in ratings:
        counts[str(rating) if rating != int(rating) else str(int(rating))] += 1
    return dict(sorted(counts.items(), key=lambda item: float(item[0]), reverse=True))


def _round(value: float) -> float:
    """Round a personal aggregate to the shared two-decimal wire precision."""
    return round(value, 2)


def _build_shared_series(
    inputs: CreatorTeamChemistryInputs,
    shared_issue_ids: set[int],
) -> list[CreatorTeamSeriesRef]:
    """Build bounded shared-series aggregates for one pair.

    Aggregates are ordered by shared issue count, then title, then thread id,
    so the same library state always renders the same sample.
    """
    thread_counts: dict[int, int] = defaultdict(int)
    for issue_id in shared_issue_ids:
        series = inputs.series_by_issue.get(issue_id)
        if series is not None:
            thread_counts[series.thread_id] += 1

    titled: list[tuple[int, int, str]] = []
    for thread_id, count in thread_counts.items():
        title = next(
            (
                inputs.series_by_issue[issue_id].thread_title
                for issue_id in sorted(shared_issue_ids)
                if inputs.series_by_issue.get(issue_id) is not None
                and inputs.series_by_issue[issue_id].thread_id == thread_id
            ),
            "",
        )
        titled.append((thread_id, count, title))

    titled.sort(key=lambda item: (-item[1], item[2].casefold(), item[0]))
    return [
        CreatorTeamSeriesRef(thread_id=thread_id, thread_title=title, shared_issue_count=count)
        for thread_id, count, title in titled[:MAX_SHARED_SERIES]
    ]


def _build_shared_issue_refs(
    inputs: CreatorTeamChemistryInputs,
    shared_issue_ids: set[int],
) -> list[CreatorTeamIssueRef]:
    """Build bounded deterministic drilldown references for one pair.

    Ordering is by case-insensitive thread title, then title, thread id, and
    issue id so every page renders the same sample for the same library state.
    Issues missing local thread identity are omitted rather than manufactured.
    """
    def _ref_key(issue_id: int) -> tuple[bool, str, str, int, int]:
        series = inputs.series_by_issue.get(issue_id)
        if series is None:
            return (True, "", "", 0, issue_id)
        return (
            False,
            series.thread_title.casefold(),
            series.thread_title,
            series.thread_id,
            issue_id,
        )

    refs: list[CreatorTeamIssueRef] = []
    for issue_id in sorted(shared_issue_ids, key=_ref_key)[:MAX_SHARED_ISSUE_REFS]:
        series = inputs.series_by_issue.get(issue_id)
        if series is None:
            continue
        refs.append(
            CreatorTeamIssueRef(
                issue_id=issue_id,
                thread_id=series.thread_id,
                thread_title=series.thread_title,
                issue_number=series.issue_number,
                effective_rating=inputs.effective_ratings.get(issue_id),
                status="read" if inputs.effective_ratings.get(issue_id) is not None else "unread",
            )
        )
    return refs


async def get_creator_team_chemistry(
    db: AsyncSession,
    user_id: int,
) -> CreatorTeamChemistryResponse:
    """Compute ranked recurring creator teams for the authenticated user.

    Args:
        db: Async database session.
        user_id: Authenticated user owning the aggregated library.

    Returns:
        The bounded team-chemistry response. Pairs below
        :data:`MIN_SHARED_TEAM_SAMPLE` are never ranked.
    """
    inputs = await load_creator_team_chemistry_inputs(db, user_id)

    rated_issue_ids = set(inputs.effective_ratings)
    rated_with_metadata = rated_issue_ids & inputs.issues_with_creator_metadata
    coverage = CreatorTeamCoverage(
        rated_issues_total=len(rated_issue_ids),
        rated_issues_with_creator_metadata=len(rated_with_metadata),
        ratings_complete=len(rated_with_metadata) >= len(rated_issue_ids),
    )

    def _baseline(creator_id: int) -> tuple[int, float | None]:
        """Return one creator's personal headline-eligible baseline sample."""
        ratings = list(inputs.baseline_ratings.get(creator_id, {}).values())
        return (
            len(ratings),
            _round(sum(ratings) / len(ratings)) if ratings else None,
        )

    def _member(
        creator_id: int,
        issue_ids: set[int],
        shared_average: float | None,
    ) -> CreatorTeamMember:
        """Build one ranked member with its baseline context and visibility."""
        baseline_count, baseline_average = _baseline(creator_id)
        difference = (
            _round(shared_average - baseline_average)
            if shared_average is not None and baseline_average is not None
            else None
        )
        return CreatorTeamMember(
            canonical_creator_key=canonical_creator_key(creator_id),
            display_name=inputs.credit_display_names.get(creator_id, ""),
            roles=_role_labels(inputs, issue_ids, creator_id),
            baseline_rated_count=baseline_count,
            baseline_average_rating=baseline_average,
            difference_from_baseline=difference,
        )

    # 1. Shared issue sets per unordered creator-id pair. Eligible issues
    # always carry an effective rating, so direct rating indexing is safe.
    pair_issues: dict[tuple[int, int], set[int]] = defaultdict(set)
    for issue_id, members in inputs.eligible_issue_creators.items():
        creator_ids = sorted(members)
        for a in range(len(creator_ids)):
            for b in range(a + 1, len(creator_ids)):
                pair_issues[(creator_ids[a], creator_ids[b])].add(issue_id)

    qualifying = {
        pair: issues for pair, issues in pair_issues.items() if len(issues) >= MIN_SHARED_TEAM_SAMPLE
    }

    # 2. Rank by true shared average (never a baseline proxy), tiebreak extras.
    ranked: list[tuple[float, int, tuple[int, int], set[int]]] = []
    for pair, issues in qualifying.items():
        ratings = [inputs.effective_ratings[issue_id] for issue_id in issues]
        shared_average = _round(sum(ratings) / len(ratings))
        ranked.append((shared_average, len(issues), pair, issues))
    ranked.sort(key=lambda item: (-item[0], -item[1], item[2]))

    # 3. Project the bounded ranked sample into the response schema.
    pairs: list[CreatorTeamPair] = []
    for _shared_average, _count, pair, issues in ranked[:MAX_RANKED_TEAM_PAIRS]:
        ratings = [inputs.effective_ratings[issue_id] for issue_id in issues]
        shared_average = _round(sum(ratings) / len(ratings))
        pair_key = "|".join(canonical_creator_key(creator_id) for creator_id in sorted(pair))
        pairs.append(
            CreatorTeamPair(
                pair_key=pair_key,
                creators=[
                    _member(creator_id, issues, shared_average) for creator_id in sorted(pair)
                ],
                shared_rated_issue_count=len(issues),
                shared_average_rating=shared_average,
                shared_median_rating=_round(median(ratings)),
                shared_rating_distribution=_distribution(ratings),
                shared_series=_build_shared_series(inputs, issues),
                shared_issue_refs=_build_shared_issue_refs(inputs, issues),
                max_shared_issue_refs=MAX_SHARED_ISSUE_REFS,
            )
        )

    return CreatorTeamChemistryResponse(
        pairs=pairs,
        pairs_total=len(qualifying),
        min_shared_team_sample=MIN_SHARED_TEAM_SAMPLE,
        max_ranked_pairs=MAX_RANKED_TEAM_PAIRS,
        coverage=coverage,
    )


__all__ = [
    "canonical_creator_key",
    "get_creator_team_chemistry",
]
