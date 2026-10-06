"""Bounded personal creator discovery list (issues #2775, #3089).

This service reuses the rating, role, and coverage semantics from ``#2028``
and ``#2037`` rather than introducing a competing formula. Every aggregate is
scoped through the authenticated user's owned ComicPile issues and their
confirmed local issue metadata; no ComicVine call is made.

Default collection: creators with at least one rated issue for the current
user (headline-eligible rated issue so ``ratings_count > 0``). Each row
carries canonical key, display name, personal ``ratings_count`` and
``average_rating``, plus compact normalized roles cheaply available from the
same aggregation. A creator with multiple roles on the same issue contributes
that issue's rating at most once.

Sorting:
- ``name`` — alphabetical ascending, case-insensitive, tie-broken by
  ``canonical_creator_key``.
- ``ratings_count`` — most-rated descending, tie-broken by name then key.
- ``average_rating`` — personal average descending with explicit null handling
  (``null`` averages sort last), tie-broken by ratings_count desc, name, key.

Null handling is explicit even though the default collection is rated-only so
the contract remains deterministic if filtering expands later.

Filters (issue #3089) compose with search and sort before ordering, so
``total`` and every page reflect the filtered set:

- ``min_ratings`` — minimum headline rated-sample size.
- ``role`` — normalized role membership, matched case-insensitively against the
  same normalized roles the rows expose. No free-form client-only matching.
- ``min_rating`` / ``max_rating`` — personal average rating range on the 0-5
  personal scale.
- ``has_unread_work`` — restrict to creators with (or without) unread attributed
  work in the reader's own pile.

Boundedness: the whole request is served by the fixed small number of queries
in ``load_creator_summary_inputs`` regardless of library size. No per-creator
or per-issue N+1 fan-out. Filtering, search, and pagination happen server-side
over the user's creator result set.
"""

from __future__ import annotations

from collections import defaultdict

from sqlalchemy.ext.asyncio import AsyncSession

from app.repositories.creator_summary import load_creator_summary_inputs
from app.schemas.creator_list import CreatorListItem, CreatorListResponse
from app.schemas.creator_summary import CreatorSummaryCoverage
from app.services.creator_summary import HEADLINE_ROLES


def _build_coverage(
    rated_total: int,
    rated_with: int,
    read_unrated_total: int,
    read_unrated_with: int,
    unread_total: int,
    unread_with: int,
) -> CreatorSummaryCoverage:
    """Build explicit coverage block."""
    return CreatorSummaryCoverage(
        rated_issues_total=rated_total,
        rated_issues_with_creator_metadata=rated_with,
        ratings_complete=rated_with >= rated_total,
        read_unrated_issues_total=read_unrated_total,
        read_unrated_issues_with_creator_metadata=read_unrated_with,
        read_unrated_complete=read_unrated_with >= read_unrated_total,
        unread_issues_total=unread_total,
        unread_issues_with_creator_metadata=unread_with,
        upcoming_complete=unread_with >= unread_total,
    )


def _normalize_role_filter(role: str | None) -> str | None:
    """Normalize an incoming role filter to the row role vocabulary.

    Args:
        role: Raw role filter from the request; may be ``None`` or padded.

    Returns:
        Trimmed, casefolded role to match, or ``None`` when no role filter applies.
    """
    if role is None:
        return None
    normalized = role.strip().casefold()
    return normalized or None


async def get_creator_list(
    db: AsyncSession,
    user_id: int,
    *,
    search: str | None = None,
    sort: str = "name",
    limit: int = 20,
    offset: int = 0,
    min_ratings: int = 0,
    role: str | None = None,
    min_rating: float | None = None,
    max_rating: float | None = None,
    has_unread_work: bool | None = None,
) -> CreatorListResponse:
    """Compute bounded personal creator list for the authenticated user.

    Args:
        db: Async database session.
        user_id: Authenticated user owning the library.
        search: Optional bounded case-insensitive name substring.
        sort: Sort mode — ``name``, ``ratings_count``, or ``average_rating``.
        limit: Page size (bounded).
        offset: Page offset.
        min_ratings: Deterministic server-side minimum rated-sample filter
            (creators need at least this many headline-rated issues).
        role: Optional normalized role filter matched case-insensitively against
            the creator's normalized roles. Padded or differently cased values
            are normalized; an empty value applies no role filter.
        min_rating: Optional minimum personal average rating threshold (0-5).
        max_rating: Optional maximum personal average rating threshold (0-5).
        has_unread_work: Optional filter restricting results to creators with
            (or without) unread attributed work in the user's pile.

    Returns:
        Bounded, deterministically ordered creator list with coverage.
    """
    inputs = await load_creator_summary_inputs(db, user_id)

    # Coverage over owned library (same as #2028).
    rated_issue_ids = frozenset(inputs.effective_ratings)
    read_unrated_issue_ids = frozenset(
        issue_id
        for issue_id, status in inputs.owned_issues.items()
        if status == "read" and issue_id not in inputs.effective_ratings
    )
    unread_issue_ids = frozenset(
        issue_id for issue_id, status in inputs.owned_issues.items() if status == "unread"
    )

    def _with_metadata(issue_ids: frozenset[int]) -> int:
        return sum(1 for issue_id in issue_ids if issue_id in inputs.issues_with_creator_metadata)

    coverage = _build_coverage(
        rated_total=len(rated_issue_ids),
        rated_with=_with_metadata(rated_issue_ids),
        read_unrated_total=len(read_unrated_issue_ids),
        read_unrated_with=_with_metadata(read_unrated_issue_ids),
        unread_total=len(unread_issue_ids),
        unread_with=_with_metadata(unread_issue_ids),
    )

    # Aggregate per-creator headline stats (reuses #2028 semantics).
    creator_issues: dict[int, set[int]] = defaultdict(set)
    creator_headline_issues: dict[int, set[int]] = defaultdict(set)
    creator_roles: dict[int, set[str]] = defaultdict(set)
    creator_names: dict[int, str] = {}

    for issue_id, credits in inputs.issue_creator_credits.items():
        for credit in credits:
            creator_issues[credit.external_id].add(issue_id)
            creator_names.setdefault(credit.external_id, credit.display_name)
            for credit_role in credit.roles:
                creator_roles[credit.external_id].add(credit_role)
            if any(credit_role in HEADLINE_ROLES for credit_role in credit.roles):
                creator_headline_issues[credit.external_id].add(issue_id)

    normalized_role_filter = _normalize_role_filter(role)
    items: list[CreatorListItem] = []
    for creator_id, issue_ids in creator_issues.items():
        headline_rated = [
            inputs.effective_ratings[issue_id]
            for issue_id in issue_ids
            if issue_id in creator_headline_issues[creator_id]
            and issue_id in inputs.effective_ratings
        ]
        ratings_count = len(headline_rated)
        # Default collection: creators with at least one headline-rated issue.
        if ratings_count == 0:
            continue
        # Server-side deterministic minimum-sample filter.
        if ratings_count < min_ratings:
            continue
        average_rating: float | None = (
            round(sum(headline_rated) / ratings_count, 2) if ratings_count else None
        )
        canonical_key = f"creator:{creator_id}"
        display_name = creator_names[creator_id]
        normalized_roles = sorted(creator_roles[creator_id])

        # Bounded name search (user-scoped).
        if search:
            if search.lower() not in display_name.lower():
                continue

        # Role filtering reuses the normalized role vocabulary the rows expose,
        # matched case-insensitively so no client-only free-form role matching
        # is introduced.
        if normalized_role_filter is not None and not any(
            candidate.casefold() == normalized_role_filter for candidate in normalized_roles
        ):
            continue

        # Personal-average range filtering. The default collection is rated-only so
        # a null average cannot appear; it is still treated as not matching so the
        # contract stays deterministic if the collection ever widens.
        if min_rating is not None and (
            average_rating is None or average_rating < min_rating
        ):
            continue
        if max_rating is not None and (
            average_rating is None or average_rating > max_rating
        ):
            continue

        # Unread attributed work in the user's own pile.
        if has_unread_work is not None:
            has_unread = any(issue_id in unread_issue_ids for issue_id in issue_ids)
            if has_unread_work != has_unread:
                continue

        items.append(
            CreatorListItem(
                canonical_creator_key=canonical_key,
                display_name=display_name,
                normalized_roles=normalized_roles,
                average_rating=average_rating,
                ratings_count=ratings_count,
            )
        )

    # Deterministic ordering with stable canonical-key tie-breaker.
    if sort == "ratings_count":
        # Most-rated descending; tie by name asc then key.
        items.sort(
            key=lambda x: (
                -x.ratings_count,
                x.display_name.lower(),
                x.canonical_creator_key,
            )
        )
    elif sort == "average_rating":
        # Average descending, nulls last; tie by ratings_count desc, name, key.
        def _avg_key(item: CreatorListItem) -> tuple[int, float, int, str, str]:
            is_null = 0 if item.average_rating is not None else 1
            # Negate for descending; nulls use 0 placeholder.
            avg_desc = -(item.average_rating if item.average_rating is not None else 0.0)
            return (
                is_null,
                avg_desc,
                -item.ratings_count,
                item.display_name.lower(),
                item.canonical_creator_key,
            )

        items.sort(key=_avg_key)
    else:
        # Default alphabetical ascending.
        items.sort(key=lambda x: (x.display_name.lower(), x.canonical_creator_key))

    total = len(items)
    paged = items[offset : offset + limit]

    return CreatorListResponse(
        items=paged,
        total=total,
        limit=limit,
        offset=offset,
        coverage=coverage,
    )


__all__ = [
    "get_creator_list",
]
