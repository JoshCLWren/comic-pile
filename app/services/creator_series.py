"""Series/run grouping contract for personal creator analytics (issue #3088).

This module answers "which books actually drive my opinion of this creator?"
by grouping a creator's attributed work into stable local series/run groups.

Identity rules (product contract):

- A group is one ComicPile thread. The thread id is the grouping identity; the
  thread title is display text only.
- Two distinct threads that happen to share a title stay in separate groups.
  Nothing is inferred from provider-wide "runs" beyond what ComicPile's own
  thread model supports.
- Creator roles are preserved per issue and aggregated truthfully per group.
- A group is seeded from the creator's attributed *rated* work, because the
  section answers which series drive the personal average. Unread and
  read-but-unrated attributed issues in the same thread are then counted into
  the seeded group instead of creating groups of their own.

Aggregation is pure in-memory work over the already-loaded, user-scoped
:class:`~app.repositories.creator_summary.CreatorSummaryInputs`. It adds no
query, no provider request, and no per-thread fan-out, and it is therefore
unaffected by library size.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from app.repositories.creator_summary import CreatorSummaryInputs
from app.schemas.creator_detail import CreatorSeriesGroup

#: Prefix for the stable local series identity key.
SERIES_KEY_PREFIX = "thread:"


def build_series_key(thread_id: int) -> str:
    """Build the stable local series identity key for a thread.

    Args:
        thread_id: Local ComicPile thread (series/run) id.

    Returns:
        The canonical ``thread:<thread_id>`` key.
    """
    return f"{SERIES_KEY_PREFIX}{thread_id}"


def parse_series_key(series_key: str) -> int | None:
    """Parse a canonical series identity key into its local thread id.

    Only the exact ``thread:<digits>`` shape is accepted. Anything else is
    rejected rather than guessed, so a caller can never address a series by
    display title text.

    Args:
        series_key: Raw series identity key from the request.

    Returns:
        The local thread id, or ``None`` when the key is not canonical.
    """
    prefix, separator, suffix = series_key.partition(":")
    if not separator or prefix != SERIES_KEY_PREFIX.rstrip(":"):
        return None
    if not suffix.isdigit():
        return None
    return int(suffix)


def creator_roles_on_issue(
    inputs: CreatorSummaryInputs,
    *,
    creator_id: int,
    issue_id: int,
) -> list[str]:
    """Return the sorted distinct roles one creator held on one issue.

    Args:
        inputs: User-scoped creator summary inputs.
        creator_id: Stable external provider person id for the creator.
        issue_id: Local ComicPile issue id.

    Returns:
        Sorted distinct role strings for this creator on this issue.
    """
    roles: set[str] = set()
    for credit in inputs.issue_creator_credits.get(issue_id, ()):
        if credit.external_id == creator_id:
            roles.update(credit.roles)
    return sorted(roles)


@dataclass
class SeriesAggregate:
    """Accumulators for one creator within one stable local thread group.

    Attributes:
        thread_id: Local ComicPile thread (series/run) id.
        thread_title: Current local thread title, display only.
        attributed_issue_count: Attributed issues of this creator in the thread.
        rated_issue_ids: Attributed issues in the thread with an effective rating.
        ratings: Effective ratings for :attr:`rated_issue_ids`, one per issue.
        roles: Distinct roles the creator held in the thread.
        unread_issue_count: Attributed unread issues still in the thread.
        read_unrated_issue_count: Attributed read issues without a rating.
        metadata_complete: False when some issue in the thread still lacks
            confirmed creator metadata, making the counts lower bounds.
    """

    thread_id: int
    thread_title: str
    attributed_issue_count: int = 0
    rated_issue_ids: list[int] = field(default_factory=list)
    ratings: list[float] = field(default_factory=list)
    roles: set[str] = field(default_factory=set)
    unread_issue_count: int = 0
    read_unrated_issue_count: int = 0
    metadata_complete: bool = True

    @property
    def rated_issue_count(self) -> int:
        """Number of attributed rated issues backing this group."""
        return len(self.rated_issue_ids)

    @property
    def average_rating(self) -> float | None:
        """Personal average over the group's rated issues, or None when unrated."""
        if not self.ratings:
            return None
        return round(sum(self.ratings) / len(self.ratings), 2)

    @property
    def lowest_rating(self) -> float | None:
        """Lowest effective rating in the group, or None when unrated."""
        return min(self.ratings) if self.ratings else None

    @property
    def highest_rating(self) -> float | None:
        """Highest effective rating in the group, or None when unrated."""
        return max(self.ratings) if self.ratings else None


def _thread_metadata_completeness(
    inputs: CreatorSummaryInputs,
) -> dict[int, bool]:
    """Compute per-thread creator-metadata completeness in one pass.

    A thread is complete only when every owned issue in it carries at least one
    usable confirmed creator credit. Otherwise an issue could silently belong
    to this creator and the derived counts are lower bounds.

    Args:
        inputs: User-scoped creator summary inputs.

    Returns:
        Mapping of thread id to whether its owned issues are fully covered.
    """
    completeness: dict[int, bool] = {}
    for issue_id, series in inputs.owned_issue_series.items():
        covered = issue_id in inputs.issues_with_creator_metadata
        completeness[series.thread_id] = completeness.get(series.thread_id, True) and covered
    return completeness


def aggregate_creator_series_groups(
    inputs: CreatorSummaryInputs,
    *,
    creator_id: int,
    creator_issue_ids: frozenset[int],
) -> list[SeriesAggregate]:
    """Group one creator's attributed work into stable series/run aggregates.

    Groups are seeded from attributed rated work and ordered deterministically:
    most-rated first, then case-insensitive title, then exact title, then the
    stable thread id.

    Args:
        inputs: User-scoped creator summary inputs.
        creator_id: Stable external provider person id for the creator.
        creator_issue_ids: Owned issue ids attributed to the creator.

    Returns:
        Deterministically ordered aggregates, one per distinct thread with
        attributed rated work.
    """
    completeness = _thread_metadata_completeness(inputs)
    aggregates: dict[int, SeriesAggregate] = {}
    for issue_id in sorted(creator_issue_ids):
        series = inputs.owned_issue_series.get(issue_id)
        if series is None:
            continue
        aggregate = aggregates.get(series.thread_id)
        if aggregate is None:
            aggregate = SeriesAggregate(
                thread_id=series.thread_id,
                thread_title=series.thread_title,
                metadata_complete=completeness.get(series.thread_id, True),
            )
            aggregates[series.thread_id] = aggregate
        aggregate.attributed_issue_count += 1
        aggregate.roles.update(
            creator_roles_on_issue(inputs, creator_id=creator_id, issue_id=issue_id)
        )
        status = inputs.owned_issues.get(issue_id)
        rating = inputs.effective_ratings.get(issue_id)
        if status == "unread":
            aggregate.unread_issue_count += 1
        if rating is not None:
            aggregate.rated_issue_ids.append(issue_id)
            aggregate.ratings.append(rating)
        elif status == "read":
            aggregate.read_unrated_issue_count += 1

    ordered = [aggregate for aggregate in aggregates.values() if aggregate.rated_issue_ids]
    ordered.sort(
        key=lambda aggregate: (
            -aggregate.rated_issue_count,
            aggregate.thread_title.casefold(),
            aggregate.thread_title,
            aggregate.thread_id,
        )
    )
    return ordered


def build_series_group(aggregate: SeriesAggregate) -> CreatorSeriesGroup:
    """Convert one internal aggregate into its serializable group contract.

    Args:
        aggregate: Accumulators for one creator within one thread.

    Returns:
        The serializable series/run group.
    """
    return CreatorSeriesGroup(
        series_key=build_series_key(aggregate.thread_id),
        thread_id=aggregate.thread_id,
        thread_title=aggregate.thread_title,
        rated_issue_count=aggregate.rated_issue_count,
        average_rating=aggregate.average_rating,
        lowest_rating=aggregate.lowest_rating,
        highest_rating=aggregate.highest_rating,
        roles=sorted(aggregate.roles),
        unread_issue_count=aggregate.unread_issue_count,
        read_unrated_issue_count=aggregate.read_unrated_issue_count,
        metadata_complete=aggregate.metadata_complete,
        sort_key=f"{aggregate.thread_id:012d}",
    )


def select_series_group(
    aggregates: list[SeriesAggregate],
    *,
    thread_id: int,
) -> SeriesAggregate | None:
    """Return the aggregate for one stable thread id, if the creator has one.

    Args:
        aggregates: Deterministically ordered creator series aggregates.
        thread_id: Local ComicPile thread id requested by the caller.

    Returns:
        The matching aggregate, or ``None`` when the creator has no attributed
        rated work in that thread.
    """
    for aggregate in aggregates:
        if aggregate.thread_id == thread_id:
            return aggregate
    return None


__all__ = [
    "SERIES_KEY_PREFIX",
    "SeriesAggregate",
    "aggregate_creator_series_groups",
    "build_series_group",
    "build_series_key",
    "creator_roles_on_issue",
    "parse_series_key",
    "select_series_group",
]
