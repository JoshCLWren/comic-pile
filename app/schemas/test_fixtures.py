"""Pydantic contracts for test-only fixture endpoints."""

from __future__ import annotations

from pydantic import BaseModel, Field


class TestCblSourceEntryCreate(BaseModel):
    """One CBL source entry seeded for browser golden-path coverage."""

    position: int | None = Field(default=None, ge=1)
    series_name: str | None = None
    issue_number: str | None = None
    volume_year: int | None = None
    issue_id: int | None = Field(default=None, gt=0)
    comicvine_issue_id: str | None = None


class TestCblSourceCreate(BaseModel):
    """Request body for seeding one discoverable CBL source list."""

    name: str | None = None
    source_path: str | None = None
    content_hash: str | None = None
    revision_sha: str | None = None
    repository: str | None = None
    entries: list[TestCblSourceEntryCreate] = Field(min_length=1)


class TestCblSourceEntryResponse(BaseModel):
    """Persisted fixture entry returned to Playwright/API tests."""

    position: int
    series_name: str
    issue_number: str
    comicvine_issue_id: str
    issue_id: int | None = None


class TestCblSourceResponse(BaseModel):
    """Persisted fixture source list returned to Playwright/API tests."""

    id: int
    name: str
    source_path: str
    content_hash: str
    revision_sha: str
    entries: list[TestCblSourceEntryResponse]
