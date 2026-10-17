"""Schemas for the bounded personal creator-team chemistry API (issue #3094).

Every metric here is descriptive personal-reading data derived from the
authenticated user's own rated issues and confirmed creator credits. The
payload shape carries sample counts and baselines next to every average so the
UI can never show an un-contextualized number, and no field exists to express
causation or statistical significance.
"""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field

from app.constants import MIN_SHARED_TEAM_SAMPLE

#: Maximum bounded issue drilldown references returned per team pair.
MAX_SHARED_ISSUE_REFS: int = 5

#: Maximum bounded series aggregates returned per team pair.
MAX_SHARED_SERIES: int = 5

#: Maximum number of ranked team pairs returned by the endpoint.
MAX_RANKED_TEAM_PAIRS: int = 10


class CreatorTeamCoverage(BaseModel):
    """Explicit metadata-coverage state for the team-chemistry aggregation."""

    model_config = ConfigDict(frozen=True)

    rated_issues_total: int = Field(ge=0, description="Rated issues in the library.")
    rated_issues_with_creator_metadata: int = Field(
        ge=0,
        description="Rated issues carrying at least one usable confirmed credit.",
    )
    ratings_complete: bool = Field(
        description=(
            "True when every rated issue carries confirmed creator metadata; "
            "otherwise pair results are lower bounds."
        )
    )


class CreatorTeamMember(BaseModel):
    """One canonical creator identity inside a ranked team pair."""

    model_config = ConfigDict(frozen=True)

    canonical_creator_key: str = Field(description="Stable ``creator:<id>`` key.")
    display_name: str = Field(description="Latest confirmed display name.")
    roles: list[str] = Field(description="Interior-storytelling roles on shared issues.")
    baseline_rated_count: int = Field(
        ge=0,
        description="Creator's personal headline-eligible rated sample size.",
    )
    baseline_average_rating: float | None = Field(
        default=None,
        description="Creator's personal baseline average, or null when unrated.",
    )
    difference_from_baseline: float | None = Field(
        default=None,
        description=(
            "Shared-pair average minus this creator's baseline average. "
            "Descriptive context only."
        ),
    )


class CreatorTeamIssueRef(BaseModel):
    """One bounded, navigable shared-issue drilldown reference."""

    model_config = ConfigDict(frozen=True)

    issue_id: int = Field(gt=0)
    thread_id: int = Field(gt=0, description="Owning local thread/series id.")
    thread_title: str = Field(description="Thread title, for display only.")
    issue_number: str = Field(description="Issue number within the thread.")
    effective_rating: float | None = Field(default=None)
    status: str = Field(description="Owned issue status (read/unread).")


class CreatorTeamSeriesRef(BaseModel):
    """Bounded shared-series context behind one team pair."""

    model_config = ConfigDict(frozen=True)

    thread_id: int = Field(gt=0)
    thread_title: str = Field(description="Thread title, for display only.")
    shared_issue_count: int = Field(ge=1, description="Pair issues from this thread.")


class CreatorTeamPair(BaseModel):
    """One ranked recurring creator pair with explainable shared metrics."""

    model_config = ConfigDict(frozen=True)

    pair_key: str = Field(description="Stable unordered pair key, ``a|b`` sorted.")
    creators: list[CreatorTeamMember] = Field(
        min_length=2,
        max_length=2,
        description="The two canonical creator identities of this team.",
    )
    shared_rated_issue_count: int = Field(
        ge=0,
        description="Shared rated issues carrying eligible interior credits for both members.",
    )
    shared_average_rating: float | None = Field(
        default=None,
        description="Average of the shared issues' effective ratings.",
    )
    shared_median_rating: float | None = Field(default=None)
    shared_rating_distribution: dict[str, int] = Field(default_factory=dict)
    shared_series: list[CreatorTeamSeriesRef] = Field(default_factory=list)
    shared_issue_refs: list[CreatorTeamIssueRef] = Field(default_factory=list)
    max_shared_issue_refs: int = Field(
        default=MAX_SHARED_ISSUE_REFS,
        ge=1,
        description="Bounding constant applied to the returned issue sample.",
    )


class CreatorTeamChemistryResponse(BaseModel):
    """Response payload for the creator team-chemistry endpoint."""

    model_config = ConfigDict(frozen=True)

    pairs: list[CreatorTeamPair] = Field(
        default_factory=list,
        description="Ranked recurring teams, strongest shared average first.",
    )
    pairs_total: int = Field(
        default=0,
        ge=0,
        description="Pairs meeting the minimum shared sample before ranking truncation.",
    )
    min_shared_team_sample: int = Field(
        default=MIN_SHARED_TEAM_SAMPLE,
        ge=1,
        description="Minimum shared sample required before a pair may rank.",
    )
    max_ranked_pairs: int = Field(
        ge=1,
        description="Bounding constant applied to the returned pair list.",
    )
    coverage: CreatorTeamCoverage | None = Field(default=None)


__all__ = [
    "CreatorTeamChemistryResponse",
    "CreatorTeamCoverage",
    "CreatorTeamIssueRef",
    "CreatorTeamMember",
    "CreatorTeamPair",
    "CreatorTeamSeriesRef",
    "MAX_RANKED_TEAM_PAIRS",
    "MAX_SHARED_ISSUE_REFS",
    "MAX_SHARED_SERIES",
]
