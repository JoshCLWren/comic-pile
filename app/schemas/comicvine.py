"""Application-facing schemas for ComicVine issue intelligence."""

from pydantic import BaseModel, Field


class ComicVineCreator(BaseModel):
    """One credited creator and their provider-supplied roles."""

    name: str
    roles: list[str] = Field(default_factory=list)


class ComicVineComicPileMatch(BaseModel):
    """One user-owned ComicPile representation of an external issue."""

    issue_id: int
    thread_id: int
    thread_title: str
    issue_number: str
    status: str


class ComicVineRelatedIssue(BaseModel):
    """One external issue related through explicit story-arc membership."""

    comicvine_issue_id: str
    series_name: str | None = None
    issue_number: str | None = None
    name: str | None = None
    cover_date: str | None = None
    comicvine_url: str | None = None
    comicpile_matches: list[ComicVineComicPileMatch] = Field(default_factory=list)


class ComicVineStoryArc(BaseModel):
    """An explicit ComicVine story arc and its unordered issue membership."""

    comicvine_arc_id: int
    name: str
    comicvine_url: str | None = None
    related_issues: list[ComicVineRelatedIssue] = Field(default_factory=list)


class ComicVineIssueIntelligence(BaseModel):
    """Curated ComicVine metadata for one confirmed ComicPile issue mapping."""

    comicvine_issue_id: str
    comicvine_url: str | None = None
    series_name: str | None = None
    series_id: int | None = None
    issue_number: str | None = None
    name: str | None = None
    description: str | None = None
    image_url: str | None = None
    cover_date: str | None = None
    store_date: str | None = None
    creators: list[ComicVineCreator] = Field(default_factory=list)
    story_arcs: list[ComicVineStoryArc] = Field(default_factory=list)
