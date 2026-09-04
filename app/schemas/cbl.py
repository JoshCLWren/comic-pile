"""Pydantic schemas for CBL (Comic Book List) functionality."""

from pydantic import BaseModel


class CBLSourceResponse(BaseModel):
    """Response schema for a CBL source.

    Attributes:
        id: The unique identifier for the CBL source.
        name: The display name of the CBL source.
    """

    id: int
    name: str


class CBLAdoptionEntryResponse(BaseModel):
    """Response schema for a single entry in a CBL adoption plan.

    Attributes:
        id: The unique identifier for the entry.
        title: The title of the comic issue.
        series_id: The ID of the series this entry belongs to.
    """

    id: int
    title: str
    series_id: int


class CBLAdoptionSeriesResponse(BaseModel):
    """Response schema for a series in a CBL adoption plan.

    Attributes:
        id: The unique identifier for the series.
        name: The display name of the series.
    """

    id: int
    name: str


class CBLadoptionPlanResponse(BaseModel):
    """Response schema for a CBL adoption plan preview.

    Attributes:
        entries: List of comic entries that would be adopted.
        series: List of series that would be adopted.
        existing_count: Number of comics the user already has.
        missing_count: Number of new comics that would be created.
        excluded_count: Number of entries excluded from adoption.
        unresolved_count: Number of entries with unresolved conflicts.
    """

    entries: list[CBLAdoptionEntryResponse]
    series: list[CBLAdoptionSeriesResponse]
    existing_count: int
    missing_count: int
    excluded_count: int
    unresolved_count: int
