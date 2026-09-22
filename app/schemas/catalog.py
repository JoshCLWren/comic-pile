"""Pydantic schemas for catalog API operations."""

from __future__ import annotations


from pydantic import BaseModel, Field, field_validator


class ExternalIdentityUpsert(BaseModel):
    """Schema for upserting an external identity (series or issue)."""

    provider: str = Field(..., min_length=1, description="External provider name (e.g., comicvine, cbl)")
    entity_type: str = Field(..., min_length=1, description="Entity type: 'series' or 'issue'")
    external_id: str = Field(..., min_length=1, description="Provider-specific identifier")
    external_url: str | None = Field(default=None, description="Optional URL to the external resource")
    metadata_json: dict[str, object] = Field(
        default_factory=dict, description="Optional arbitrary metadata from the provider"
    )

    @field_validator("entity_type")
    @classmethod
    def validate_entity_type(cls, entity_type: str) -> str:
        """Validate that entity_type is either 'issue' or 'series'."""
        if entity_type not in {"issue", "series"}:
            raise ValueError(f"unsupported entity_type: {entity_type}")
        return entity_type


class ExternalIdentityResponse(BaseModel):
    """Schema for responding with external identity information."""

    id: int = Field(..., description="Database ID of the external identity")
    provider: str = Field(..., min_length=1, description="External provider name")
    entity_type: str = Field(..., min_length=1, description="Entity type: 'issue' or 'series'")
    external_id: str = Field(..., min_length=1, description="Provider-specific identifier")
    external_url: str | None = Field(default=None, description="Optional URL to the external resource")
    metadata_json: dict[str, object] = Field(
        default_factory=dict, description="Arbitrary metadata from the provider"
    )
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
    metadata_json: dict[str, object] = Field(
        default_factory=dict, description="Optional arbitrary metadata from the provider"
    )
    status: str = Field(..., min_length=1, description="Mapping status: unresolved, candidate, confirmed, rejected")
    evidence_source: str | None = Field(default=None, description="Optional source of the evidence")
    confidence: float | None = Field(default=None, ge=0, le=1, description="Optional confidence score (0-1)")

    @field_validator("entity_type")
    @classmethod
    def validate_entity_type(cls, entity_type: str) -> str:
        """Validate that entity_type is either 'issue' or 'series'."""
        if entity_type not in {"issue", "series"}:
            raise ValueError(f"unsupported entity_type: {entity_type}")
        return entity_type


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
    metadata_json: dict[str, object]
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
    metadata_json: dict[str, object]
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


class SeriesMappingPreviewRequest(BaseModel):
    """Schema for series mapping preview requests."""

    origin_issue_id: int = Field(..., ge=1, description="The anchor issue ID for the mapping preview")
    provider: str = Field(..., min_length=1, description="External provider name (e.g., comicvine)")
    provider_series_external_id: str = Field(..., min_length=1, description="Provider-specific series identifier")

    @field_validator("provider")
    @classmethod
    def validate_provider(cls, provider: str) -> str:
        """Validate that provider is supported."""
        supported_providers = {"comicvine"}
        if provider not in supported_providers:
            raise ValueError(f"unsupported provider: {provider}")
        return provider


class SeriesMappingPreviewScope(BaseModel):
    """Schema for the scope information in preview responses."""

    status: str = Field(..., description="Scope status: 'available' or 'unavailable'")
    scope_key: str | None = Field(default=None, description="Opaque scope key when available")
    origin_issue_id: int = Field(..., description="Origin issue ID")
    series_label: str | None = Field(default=None, description="Series label when available")
    basis: str | None = Field(default=None, description="Basis for scope determination")


class SeriesMappingPreviewCounts(BaseModel):
    """Schema for classification counts in preview responses."""

    already_confirmed: int = Field(..., ge=0, description="Number of already confirmed mappings")
    safe_exact_match: int = Field(..., ge=0, description="Number of safe exact matches")
    needs_review_ambiguous: int = Field(..., ge=0, description="Number of issues needing review due to ambiguity")
    needs_review_conflict: int = Field(..., ge=0, description="Number of issues needing review due to conflicts")
    unresolved: int = Field(..., ge=0, description="Number of unresolved issues")
    excluded_special: int = Field(..., ge=0, description="Number of excluded special/annual issues")


class SeriesMappingPreviewRow(BaseModel):
    """Schema for individual rows in preview responses."""

    issue_id: int = Field(..., description="Internal issue ID")
    issue_number: str = Field(..., description="Issue number")
    title: str | None = Field(default=None, description="Issue title")
    classification: str = Field(..., description="Classification: already_confirmed, safe_exact_match, needs_review_ambiguous, needs_review_conflict, unresolved, excluded_special")
    thread_id: int | None = Field(default=None, description="Thread ID if the issue belongs to a thread")
    thread_title: str | None = Field(default=None, description="Thread title if applicable")
    current_mapping_status: str | None = Field(default=None, description="Current mapping status if any")
    proposed_mapping: bool = Field(..., description="Whether this issue would be mapped in the proposed scope")
    default_selected: bool = Field(..., description="Whether this is a default selected row (only for safe_exact_match)")
    reason: str | None = Field(default=None, description="Explanation for the classification")


class SeriesMappingPreviewProviderSeries(BaseModel):
    """Schema for provider series information in preview responses."""

    id: str = Field(..., description="Provider series ID")
    name: str = Field(..., description="Series name")
    publisher: str | None = Field(default=None, description="Publisher name")
    start_year: int | None = Field(default=None, description="Start year")
    count_of_issues: int | None = Field(default=None, description="Total number of issues in the series")
    site_detail_url: str | None = Field(default=None, description="URL to the series on the provider site")
    image: dict[str, object] | None = Field(default=None, description="Image information")


class SeriesMappingPreviewResponse(BaseModel):
    """Schema for series mapping preview responses."""

    preview_token: str | None = Field(default=None, description="Preview token when scope is available")
    scope: SeriesMappingPreviewScope = Field(..., description="Scope information")
    provider_series: SeriesMappingPreviewProviderSeries | None = Field(default=None, description="Provider series information")
    counts: SeriesMappingPreviewCounts = Field(..., description="Classification counts")
    rows: list[SeriesMappingPreviewRow] = Field(default_factory=list, description="Individual issue mappings")
    issued_at: float = Field(..., description="Token issuance timestamp (Unix epoch)")
    expires_at: float | None = Field(default=None, description="Token expiration timestamp (Unix epoch)")
