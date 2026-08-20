"""Pydantic schemas for catalog API operations."""

from __future__ import annotations


from pydantic import Field, root_validator

from app.schemas import BaseModel


class ExternalIdentityUpsert(BaseModel):
    """Schema for upserting an external identity (series or issue)."""

    provider: str = Field(..., min_length=1, description="External provider name (e.g., comicvine, cbl)")
    entity_type: str = Field(..., min_length=1, description="Entity type: 'series' or 'issue'")
    external_id: str = Field(..., min_length=1, description="Provider-specific identifier")
    external_url: str | None = Field(default=None, description="Optional URL to the external resource")
    metadata_json: dict = Field(default=dict, description="Optional arbitrary metadata from the provider")

    @root_validator
    def validate_entity_type(self, values: dict) -> dict:
        """Validate that entity_type is either 'issue' or 'series'."""
        entity_type = values.get("entity_type", "")
        if entity_type not in {"issue", "series"}:
            raise ValueError(f"unsupported entity_type: {entity_type}")
        return values


class ExternalIdentityResponse(BaseModel):
    """Schema for responding with external identity information."""

    id: int = Field(..., description="Database ID of the external identity")
    provider: str = Field(..., min_length=1, description="External provider name")
    entity_type: str = Field(..., min_length=1, description="Entity type: 'issue' or 'series'")
    external_id: str = Field(..., min_length=1, description="Provider-specific identifier")
    external_url: str | None = Field(default=None, description="Optional URL to the external resource")
    metadata_json: dict = Field(default_factory=dict, description="Arbitrary metadata from the provider")
    provider_updated_at: float | None = Field(default=None, description="Timestamp of last provider update")
    created_at: float = Field(..., description="Creation timestamp (Unix epoch)")
    updated_at: float = Field(..., description="Last update timestamp (Unix epoch)")


class ThreadSeriesAttachRequest(BaseModel):
    """Schema for attaching a series to a thread."""

    status: str = Field(..., min_length=1, description="Mapping status: unresolved, candidate, confirmed, rejected")
    evidence_source: str | None = Field(default=None, description="Optional source of the evidence")
    confidence: float | None = Field(default=None, ge=0, le=1, description="Optional confidence score (0-1)")


class ThreadSeriesAttachResponse(BaseModel):
    """Schema for the series-attach response."""

    id: int = Field(..., description="Mapping database ID")
    thread_id: int = Field(..., description="Thread ID")
    external_identity_id: int = Field(..., description="External identity ID")
    status: str = Field(..., min_length=1, description="Mapping status")
    evidence_source: str | None = Field(default=None, description="Evidence source")
    confidence: float | None = Field(default=None, ge=0, le=1, description="Confidence score")
    created_at: float = Field(..., description="Creation timestamp (Unix epoch)")
    updated_at: float = Field(..., description="Last update timestamp (Unix epoch)")


class IssueAttachRequest(BaseModel):
    """Schema for attaching an issue to a thread."""

    issue_id: int = Field(..., description="Internal ComicPile issue ID to attach the external identity to")
    provider: str = Field(..., min_length=1, description="External provider name (e.g., comicvine, cbl)")
    entity_type: str = Field(..., min_length=1, description="Entity type: 'series' or 'issue'")
    external_id: str = Field(..., min_length=1, description="Provider-specific identifier")
    external_url: str | None = Field(default=None, description="Optional URL to the external resource")
    metadata_json: dict = Field(default=dict, description="Optional arbitrary metadata from the provider")
    status: str = Field(..., min_length=1, description="Mapping status: unresolved, candidate, confirmed, rejected")
    evidence_source: str | None = Field(default=None, description="Optional source of the evidence")
    confidence: float | None = Field(default=None, ge=0, le=1, description="Optional confidence score (0-1)")

    @root_validator
    def validate_entity_type(self, values: dict) -> dict:
        """Validate that entity_type is either 'issue' or 'series'."""
        entity_type = values.get("entity_type", "")
        if entity_type not in {"issue", "series"}:
            raise ValueError(f"unsupported entity_type: {entity_type}")
        return values


class IssueAttachResponse(BaseModel):
    """Schema for the issue-attach response."""

    id: int = Field(..., description="Mapping database ID")
    issue_id: int = Field(..., description="Issue database ID")
    external_identity_id: int = Field(..., description="External identity ID")
    status: str = Field(..., min_length=1, description="Mapping status")
    evidence_source: str | None = Field(default=None, description="Evidence source")
    confidence: float | None = Field(default=None, ge=0, le=1, description="Confidence score")
    rejection_reason: str | None = Field(default=None, description="Optional rejection reason")
    created_at: float = Field(..., description="Creation timestamp (Unix epoch)")
    updated_at: float = Field(..., description="Last update timestamp (Unix epoch)")


class CatalogSeriesSearchResponse(BaseModel):
    """Schema for series search results."""

    id: int
    provider: str
    entity_type: str
    external_id: str
    external_url: str | None = None
    metadata_json: dict
    provider_updated_at: float | None = None
    created_at: float
    updated_at: float


class CatalogIssueSearchResponse(BaseModel):
    """Schema for issue search results."""

    id: int
    provider: str
    entity_type: str
    external_id: str
    external_url: str | None = None
    metadata_json: dict
    provider_updated_at: float | None = None
    created_at: float
    updated_at: float


class ThreadExternalSeriesMappingResponse(BaseModel):
    """Schema for thread-series mapping responses."""

    id: int
    thread_id: int
    external_identity_id: int
    status: str
    evidence_source: str | None = None
    confidence: float | None = None
    created_at: float
    updated_at: float


class IssueExternalIdentityMappingResponse(BaseModel):
    """Schema for issue-external identity mapping responses."""

    id: int
    issue_id: int
    external_identity_id: int
    status: str
    evidence_source: str | None = None
    confidence: float | None = None
    rejection_reason: str | None = None
    created_at: float
    updated_at: float