"""Pydantic schemas for the bounded personal creator summary API (issue #2028).

The summary endpoint gives the Roll experience per-creator reading statistics
derived from the reader's own issues and the creator credits confirmed via
ComicVine identity metadata (issue #2036). The response holds one row per
requested canonical creator key plus a single library-wide coverage block so
callers can tell complete results from lower-bound ones.
"""

from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field

# Upper bound on canonical creator keys accepted by one batch request. A Roll
# card requests only the creators visible on the current issue, so the bound
# is generous while still preventing unbounded query-string abuse.
MAX_CREATOR_KEYS = 200


class CreatorSummaryOutput(BaseModel):
    """Personal reading summary for one canonical creator.

    Attributes:
        canonical_creator_key: Stable provider-identity key (``creator:<id>``)
            from issue #2036, shared across every role the creator has.
        display_name: Best-known provider display name for the creator.
        normalized_roles: Deduplicated, comma-split role list across all
            confirmed issues where the creator is credited.
        average_rating: Mean effective rating across headline-eligible rated
            reads, or ``None`` when there are none (never 0).
        ratings_count: Number of headline-eligible rated issues; the latest
            rate event per issue counts once.
        read_unrated_count: Read issues attributed to the creator with no
            effective rating.
        upcoming_count: Unread issues attributed to the creator that are
            already present in this user's ComicPile.
    """

    model_config = ConfigDict(frozen=True)

    canonical_creator_key: str = Field(min_length=1)
    display_name: str = ""
    normalized_roles: list[str] = Field(default_factory=list)
    average_rating: float | None = None
    ratings_count: int = Field(default=0, ge=0)
    read_unrated_count: int = Field(default=0, ge=0)
    upcoming_count: int = Field(default=0, ge=0)


class CreatorChapterCoverage(BaseModel):
    """Creator-metadata coverage for one issue universe.

    Attributes:
        total: Issues in the universe (rated, read-unrated, or upcoming).
        with_creator_metadata: Issues in the universe that carry confirmed,
            usable creator metadata.
        complete: Whether every issue in the universe has usable metadata.
    """

    model_config = ConfigDict(frozen=True)

    total: int = Field(ge=0)
    with_creator_metadata: int = Field(ge=0)
    complete: bool = False


class CreatorSummaryCoverage(BaseModel):
    """Library-wide creator-metadata coverage per issue universe.

    Coverage is computed once per request and applies to every requested
    creator: the universes are the reader's owned issues (rated, read-but-
    unrated, and unread). A universe is complete only when every issue in it
    carries usable creator metadata, making lower-bound results explicit
    rather than silently looking exact.
    """

    model_config = ConfigDict(frozen=True)

    rated: CreatorChapterCoverage
    read_unrated: CreatorChapterCoverage
    upcoming: CreatorChapterCoverage


class CreatorSummaryResponse(BaseModel):
    """Batch creator summaries plus one library-wide coverage block.

    Attributes:
        summaries: One row per requested key, in the requested order. Keys
            with no attributable inside this reader's own library return an
            empty row so no cross-user data is ever revealed.
        coverage: Global creator-metadata coverage across the reader's owned
            issue universes.
        generated_at: UTC generation time for the response.
    """

    model_config = ConfigDict(frozen=True)

    summaries: list[CreatorSummaryOutput]
    coverage: CreatorSummaryCoverage
    generated_at: datetime