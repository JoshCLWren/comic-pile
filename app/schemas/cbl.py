from typing import List

from pydantic import BaseModel


class CBLSourceResponse(BaseModel):
    id: int
    name: str


class CBLAdoptionEntryResponse(BaseModel):
    id: int
    title: str
    seriesId: int


class CBLAdoptionSeriesResponse(BaseModel):
    id: int
    name: str


class CBLAdoptionPlanResponse(BaseModel):
    entries: List[CBLAdoptionEntryResponse]
    series: List[CBLAdoptionSeriesResponse]
    existingCount: int
    missingCount: int
    excludedCount: int
    unresolvedCount: int