"""Validation and responses for explicit user collection exclusions."""

from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field, model_validator


class CollectionExclusionCreate(BaseModel):
    """Exactly one target: external volume identity, Thread or Issue."""

    provider: str | None = Field(default=None, min_length=1, max_length=50)
    external_volume_id: str | None = Field(default=None, min_length=1, max_length=100)
    thread_id: int | None = Field(default=None, gt=0)
    issue_id: int | None = Field(default=None, gt=0)

    @model_validator(mode="after")
    def require_exact_target(self) -> CollectionExclusionCreate:
        """Require a paired external identity or one local target."""
        volume = self.external_volume_id is not None
        if sum((volume, self.thread_id is not None, self.issue_id is not None)) != 1:
            raise ValueError("Provide exactly one external volume, Thread or Issue target")
        if (self.provider is not None) != volume:
            raise ValueError("Provider and external_volume_id must be supplied together")
        if volume:
            if not self.provider or not self.provider.strip():
                raise ValueError("Provider cannot be blank")
            if not self.external_volume_id or not self.external_volume_id.strip():
                raise ValueError("External volume ID cannot be blank")
            self.provider = self.provider.strip().lower()
            self.external_volume_id = self.external_volume_id.strip()
        return self


class CollectionExclusionResponse(BaseModel):
    """Stored exclusion, with an ID for explicit removal."""

    model_config = ConfigDict(from_attributes=True)

    id: int
    user_id: int
    provider: str | None
    external_volume_id: str | None
    thread_id: int | None
    issue_id: int | None
    created_at: datetime
