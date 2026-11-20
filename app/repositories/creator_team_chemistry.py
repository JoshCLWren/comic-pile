"""Bounded repository data access for recurring creator-team chemistry (#3094).

This module owns every input query the team-chemistry analytics need. It does
not reimplement creator identity, credit extraction, or rating semantics: it
reuses the canonical :func:`load_creator_summary_inputs` pipeline (issue
#2028/#3244), so team analytics always agree with creator detail on what a
creator identity is, which credits are confirmed, and which rating counts.

Inherited bounded-cost guarantees, verified by
``tests/test_creator_team_chemistry_api.py``:

- every query is scoped to the authenticated user by ``threads.user_id``;
- the whole aggregation is served by the pipeline's fixed five queries no
  matter how large the library or a page's creator set grows;
- no per-issue or per-creator follow-up queries are issued.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from sqlalchemy.ext.asyncio import AsyncSession

from app.repositories.creator_summary import (
    CreatorSummaryInputs,
    OwnedIssueSeries,
    load_creator_summary_inputs,
)

#: Headline-eligible roles for personal baseline statistics, mirroring the
#: classification used by creator detail and comparison (issues #2028, #3091).
#: Defined locally as a plain set to avoid importing service-layer constants
#: from the repository layer.
_HEADLINE_ROLES: frozenset[str] = frozenset(
    {"writer", "artist", "penciler", "inker", "colorist", "letterer"}
)

#: Interior-storytelling roles that may define a recurring team pair.
#:
#: Deliberately narrower than :data:`HEADLINE_ROLES`: letterer, cover-only, and
#: editorial credits credit almost every issue and explode the pairwise set
#: into page noise (issue #3094 semantics). Any credit with none of these
#: roles never forms a pair, while an eligible creator may still carry a
#: headline role for its baseline statistics.
TEAM_ELIGIBLE_ROLES: frozenset[str] = frozenset(
    {"writer", "artist", "penciler", "inker", "colorist"}
)


@dataclass(frozen=True)
class CreatorTeamMemberCredits:
    """One canonical creator identity as credited on rated issues.

    Attributes:
        creator_id: Stable external person id; manual creators carry their
            reserved-band synthetic id, so same-name creators always stay
            distinct (issue #2036).
        display_name: Most recent provider/manual display name seen.
        shared_roles: Interior-storytelling roles observed on the eligible
            shared issues, uppercase-normalized by the extractor.
    """

    creator_id: int
    display_name: str = ""
    shared_roles: frozenset[str] = field(default_factory=frozenset)


@dataclass(frozen=True)
class CreatorTeamChemistryInputs:
    """Plain user-scoped inputs for the team-chemistry aggregation.

    Attributes:
        eligible_issue_creators: Mapping of rated issue id to the interior
            eligible ``(creator_id, roles-on-issue)`` memberships credited on
            it. Issues without at least two eligible identities are omitted.
        credit_display_names: Mapping of creator id to latest display name.
        baseline_ratings: Mapping of creator id to its personal baseline rated
            sample (effective ratings of issues carrying any headline role).
        series_by_issue: Stable local series/thread identity per rated issue.
        effective_ratings: Latest effective ``rate`` rating per rated issue.
        issues_with_creator_metadata: Rated issues carrying at least one
            usable confirmed creator credit (partial-coverage truthfulness).
    """

    eligible_issue_creators: dict[int, dict[int, frozenset[str]]] = field(
        default_factory=dict
    )
    credit_display_names: dict[int, str] = field(default_factory=dict)
    baseline_ratings: dict[int, dict[int, float]] = field(default_factory=dict)
    series_by_issue: dict[int, OwnedIssueSeries] = field(default_factory=dict)
    effective_ratings: dict[int, float] = field(default_factory=dict)
    issues_with_creator_metadata: frozenset[int] = field(default_factory=frozenset)


async def load_creator_team_chemistry_inputs(
    db: AsyncSession,
    user_id: int,
) -> CreatorTeamChemistryInputs:
    """Load every user-scoped input needed for the team-chemistry aggregation.

    Args:
        db: Async database session.
        user_id: Authenticated user whose library is aggregated.

    Returns:
        User-scoped :class:`CreatorTeamChemistryInputs`.
    """
    summary_inputs: CreatorSummaryInputs = await load_creator_summary_inputs(db, user_id)

    eligible_issue_creators: dict[int, dict[int, frozenset[str]]] = {}
    credit_display_names: dict[int, str] = {}
    baseline_ratings: dict[int, dict[int, float]] = {}

    for issue_id, credits in summary_inputs.issue_creator_credits.items():
        rating = summary_inputs.effective_ratings.get(issue_id)
        eligible_members: dict[int, frozenset[str]] = {}
        for credit in credits:
            credit_display_names.setdefault(credit.external_id, credit.display_name)
            eligible_roles = frozenset(credit.roles) & TEAM_ELIGIBLE_ROLES
            headline_ratings = baseline_ratings.setdefault(credit.external_id, {})
            if any(role in _HEADLINE_ROLES for role in credit.roles) and rating is not None:
                headline_ratings.setdefault(issue_id, rating)
            if eligible_roles:
                existing = eligible_members.get(credit.external_id, frozenset())
                eligible_members[credit.external_id] = existing | eligible_roles
        if len(eligible_members) >= 2 and rating is not None:
            eligible_issue_creators[issue_id] = eligible_members

    return CreatorTeamChemistryInputs(
        eligible_issue_creators=eligible_issue_creators,
        credit_display_names=credit_display_names,
        baseline_ratings=baseline_ratings,
        series_by_issue=summary_inputs.owned_issue_series,
        effective_ratings=summary_inputs.effective_ratings,
        issues_with_creator_metadata=summary_inputs.issues_with_creator_metadata,
    )


__all__ = [
    "CreatorTeamChemistryInputs",
    "CreatorTeamMemberCredits",
    "TEAM_ELIGIBLE_ROLES",
    "load_creator_team_chemistry_inputs",
]
