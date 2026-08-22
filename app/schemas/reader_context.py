"""Schemas for the bounded issue reader-context API."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field


class ReaderContextPreviousIssue(BaseModel):
    """The immediately preceding issue inside the requested issue's thread."""

    issue_id: int
    issue_number: str
    rating: float | None = None


class ReaderContextRecentRating(BaseModel):
    """One effective series rating ordered by its effective event timestamp."""

    issue_id: int
    issue_number: str
    rating: float


class ReaderContextSeries(BaseModel):
    """Canonical-series reading analytics for the requested issue."""

    identity_source: Literal["comicvine", "unavailable"]
    canonical_series_id: str | None = None
    series_name: str | None = None
    average_rating: float | None = None
    ratings_count: int = 0
    previous_issue: ReaderContextPreviousIssue | None = None
    recent_ratings: list[ReaderContextRecentRating] = Field(default_factory=list)
    highest_rating: float | None = None
    lowest_rating: float | None = None


class ReaderContextCrossoverNextMember(BaseModel):
    """The nearest future exact member of a crossover in the current thread."""

    issue_id: int
    issue_number: str


class ReaderContextCrossover(BaseModel):
    """One owned crossover relevant to the requested issue's thread."""

    id: int
    name: str
    applies_to_current_issue: bool
    next_member: ReaderContextCrossoverNextMember | None = None
    average_rating: float | None = None
    ratings_count: int = 0
    read_count: int = 0


class ReaderContextCrossoverMembership(BaseModel):
    """One exact crossover membership held by an owned issue."""

    id: int
    name: str


class ReaderContextLocalIssue(BaseModel):
    """One bounded local-chain issue centered on the requested issue."""

    issue_id: int
    issue_number: str
    position: int
    status: str
    relation: Literal["previous", "current", "next", "future"]
    rating: float | None = None
    crossover_memberships: list[ReaderContextCrossoverMembership] = Field(default_factory=list)


class ReaderContextEdge(BaseModel):
    """One persisted one-hop dependency or continuity edge."""

    id: int
    kind: Literal["dependency", "continuity"]
    source_issue_id: int
    target_issue_id: int
    source_label: str | None = None
        target_label: str | None = None
        source_issue_number: str | None = None
        target_issue_number: str | None = None
        source_thread_title: str | None = None
        target_thread_title: str | None = None
    note: str | None = None
    explanation: str | None = None


class ReaderContextLocalChain(BaseModel):
    """The bounded local reading neighborhood around the requested issue."""

    issues: list[ReaderContextLocalIssue] = Field(default_factory=list)
    edges: list[ReaderContextEdge] = Field(default_factory=list)


class ReaderContextResponse(BaseModel):
    """Bounded reader-context for one owned issue."""

    issue_id: int
    series: ReaderContextSeries
    crossovers: list[ReaderContextCrossover] = Field(default_factory=list)
    local_chain: ReaderContextLocalChain