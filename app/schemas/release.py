"""Typed API schemas for the durable release ledger."""

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

ReleaseVisibility = Literal["public", "internal"]
ReleaseStatus = Literal["draft", "published", "retracted"]


class ReleaseResponse(BaseModel):
    """One release ledger record returned by the API."""

    model_config = ConfigDict(from_attributes=True)

    id: int
    source_repository: str
    source_pr_number: int | None
    source_merge_sha: str | None
    merged_at: datetime | None
    released_at: datetime
    category: str
    title: str
    summary: str
    body: str | None
    visibility: ReleaseVisibility
    status: ReleaseStatus
    sort_order: int
    provenance_json: dict[str, object]
    created_at: datetime
    updated_at: datetime


class ReleaseListResponse(BaseModel):
    """Paginated published releases for What's New."""

    releases: list[ReleaseResponse]
    total: int
    limit: int
    offset: int


class ReleaseUpsertRequest(BaseModel):
    """Idempotent release publication payload from trusted automation."""

    source_repository: str = Field(min_length=1, max_length=255)
    source_pr_number: int | None = Field(default=None, ge=1)
    source_merge_sha: str | None = Field(default=None, min_length=7, max_length=64)
    merged_at: datetime | None = None
    released_at: datetime
    category: str = Field(min_length=1, max_length=100)
    title: str = Field(min_length=1, max_length=255)
    summary: str = Field(min_length=1)
    body: str | None = None
    visibility: ReleaseVisibility = "public"
    status: ReleaseStatus = "published"
    sort_order: int = 0
    provenance_json: dict[str, object] = Field(default_factory=dict)

    @model_validator(mode="after")
    def require_github_identity(self) -> ReleaseUpsertRequest:
        """Require at least one stable source identity for retry-safe publication."""
        if self.source_pr_number is None and self.source_merge_sha is None:
            raise ValueError("source_pr_number or source_merge_sha is required")
        return self


class ReleaseSourceResponse(BaseModel):
    """Result of reconciling a GitHub source identity with the ledger."""

    exists: bool
    release: ReleaseResponse | None = None
