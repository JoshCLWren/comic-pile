"""Typed schemas for cross-repository factory delivery."""

from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field, field_validator


TargetRepository = Literal["JoshCLWren/comic-pile", "JoshCLWren/Latticery"]
DeliveryStatus = Literal["pending", "branch_created", "pr_opened", "merged", "failed", "released"]


class DeliveryRecordCreate(BaseModel):
    """Schema for creating a new delivery record."""

    source_repository: str = Field(..., min_length=1)
    target_repository: str = Field(..., min_length=1)
    target_branch: str = Field(..., min_length=1)
    issue_number: int | None = Field(default=None, ge=1)
    worker_id: str = Field(..., min_length=1)
    metadata_json: dict | None = Field(default_factory=dict)

    @field_validator("target_repository")
    @classmethod
    def validate_target_repo(cls, v: str) -> str:
        """Ensure target repository is allowlisted."""
        allowed = {"JoshCLWren/comic-pile", "JoshCLWren/Latticery"}
        if v not in allowed:
            raise ValueError(f"Target repository '{v}' is not allowlisted")
        return v


class DeliveryRecordResponse(BaseModel):
    """Schema for returning a delivery record."""

    id: int
    source_repository: str
    target_repository: str
    target_branch: str
    target_pr_number: int | None
    target_merge_sha: str | None
    issue_number: int | None
    status: str
    worker_id: str
    error_message: str | None
    metadata_json: dict
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}


class DeliveryRecordUpdate(BaseModel):
    """Schema for updating a delivery record."""

    target_pr_number: int | None = None
    target_merge_sha: str | None = None
    status: DeliveryStatus | None = None
    error_message: str | None = None


class TargetRepositoryValidation(BaseModel):
    """Schema for validating a target repository choice."""

    target_repository: str = Field(..., min_length=1)
    credential_source: str = Field(..., min_length=1)

    @field_validator("target_repository")
    @classmethod
    def validate_target(cls, v: str) -> str:
        """Ensure target repository is allowlisted."""
        allowed = {"JoshCLWren/comic-pile", "JoshCLWren/Latticery"}
        if v not in allowed:
            raise ValueError(f"Target repository '{v}' is not allowlisted")
        return v


class CrossRepoDeliveryRequest(BaseModel):
    """Schema for requesting a cross-repository delivery operation."""

    target_repository: str = Field(..., min_length=1)
    issue_number: int | None = Field(default=None, ge=1)
    branch_name: str = Field(..., min_length=1)
    worker_id: str = Field(..., min_length=1)
    title: str = Field(..., min_length=1)
    body: str | None = Field(default=None)
    base_branch: str = Field(default="main")

    @field_validator("target_repository")
    @classmethod
    def validate_target(cls, v: str) -> str:
        """Ensure target repository is allowlisted."""
        allowed = {"JoshCLWren/comic-pile", "JoshCLWren/Latticery"}
        if v not in allowed:
            raise ValueError(f"Target repository '{v}' is not allowlisted")
        return v

    @field_validator("branch_name")
    @classmethod
    def validate_branch_name(cls, v: str) -> str:
        """Ensure branch name follows factory naming convention."""
        if not v.startswith("factory/"):
            raise ValueError("Branch name must start with 'factory/'")
        return v


class DeliveryResult(BaseModel):
    """Schema for the result of a delivery operation."""

    success: bool
    target_repository: str
    target_branch: str
    target_pr_number: int | None = None
    target_merge_sha: str | None = None
    credential_source: str
    error_message: str | None = None
    delivery_key: str = Field(..., min_length=1)
