"""Reader context response schemas."""

from typing import Literal

from pydantic import BaseModel, Field


class SeriesInfo(BaseModel):
    """Series identity and aggregate rating information."""

    identity_source: Literal["comicvine", "unavailable"]
    canonical_series_id: str | None = None
    series_name: str | None = None
    average_rating: float | None = None
    ratings_count: int
    previous_issue: "LocalChainIssue | None" = None
    recent_ratings: list["LocalChainIssue"] = Field(default_factory=list)
    highest_rating: float | None = None
    lowest_rating: float | None = None


class CrossoverMemberInfo(BaseModel):
    """Information about a crossover member issue."""

    issue_id: int
    issue_number: str
    rating: float | None = None
    status: Literal["read", "unread"]


class CrossoverInfo(BaseModel):
    """Exact crossover context for the current issue."""

    id: int
    name: str
    applies_to_current_issue: bool
    next_member: "LocalChainIssue | None" = None
    average_rating: float | None = None
    ratings_count: int
    read_count: int


class LocalChainIssue(BaseModel):
    """One issue in the local same-thread neighborhood."""

    issue_id: int
    issue_number: str
    position: int
    status: Literal["read", "unread"]
    relation: Literal["previous", "current", "next", "future"]
    rating: float | None = None
    crossover_memberships: list[CrossoverMemberInfo] = Field(default_factory=list)


class LocalChainEdge(BaseModel):
    """One persisted one-hop dependency/continuity edge touching the neighborhood."""

    dependency_id: int
    source_issue_id: int
    target_issue_id: int
    source_issue_number: str
    target_issue_number: str
    source_thread_id: int
    target_thread_id: int
    source_thread_title: str
    target_thread_title: str
    note: str | None = None


class LocalChainResponse(BaseModel):
    """Bounded local reading chain around the current issue."""

    issues: list[LocalChainIssue] = Field(default_factory=list, max_length=5)
    edges: list[LocalChainEdge] = Field(default_factory=list, max_length=20)


class ReaderContextResponse(BaseModel):
    """Complete reader context for the active roll issue."""

    issue_id: int
    series: SeriesInfo
    crossovers: list[CrossoverInfo] = Field(default_factory=list)
    local_chain: LocalChainResponse