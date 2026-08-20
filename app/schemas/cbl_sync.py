"""Schemas for service-authorized CBL synchronization."""

from pydantic import BaseModel, Field


class CBLBookPayload(BaseModel):
    """One normalized CBL book entry."""

    position: int = Field(ge=1)
    series: str = Field(min_length=1, max_length=500)
    issue_number: str = Field(min_length=1, max_length=100)
    volume_year: int | None = None
    publication_year: int | None = None
    comicvine_series_id: str | None = None
    comicvine_issue_id: str | None = None


class CBLListPayload(BaseModel):
    """One normalized CBL list and its ordered books."""

    source_path: str = Field(min_length=1, max_length=1000)
    content_hash: str = Field(min_length=1, max_length=64)
    name: str = Field(min_length=1, max_length=500)
    declared_issue_count: int | None = Field(default=None, ge=0)
    books: list[CBLBookPayload]


class CBLBatchRequest(BaseModel):
    """A bounded batch belonging to one mirror revision."""

    repository: str = Field(min_length=1, max_length=255)
    revision_sha: str = Field(min_length=7, max_length=56)
    lists: list[CBLListPayload] = Field(min_length=1, max_length=25)


class CBLFinalizeRequest(BaseModel):
    """Finalize one mirror revision after all batches succeed."""

    repository: str = Field(min_length=1, max_length=255)
    revision_sha: str = Field(min_length=7, max_length=56)
    active_paths: list[str]
    protected_paths: list[str] = Field(default_factory=list)


class CBLSourceStatusResponse(BaseModel):
    """Last fully synchronized revision for one source."""

    repository: str
    revision_sha: str | None


class CBLBatchResponse(BaseModel):
    """Machine-readable synchronization counters."""

    source_created: bool
    inserted_lists: int
    updated_lists: int
    deactivated_lists: int
    unchanged_lists: int
    entries_written: int
    dry_run: bool
