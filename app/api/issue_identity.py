"""CBL adoption preview and dry-run plan endpoints."""

from __future__ import annotations

from datetime import datetime
from typing import Annotated, Literal

from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth import get_current_user
from app.database import get_db
from app.models.user import User
from app.services.cbl_reconciliation import (
    CBLAdoptionPlan,
    CBLReconciliationReport,
    preview_cbl_adoption,
)
from app.services.cbl_source_public import public_cbl_repository

router = APIRouter(prefix="/api/v1/issue-identity", tags=["issue-identity"])


class CBLAdoptionPlanRequest(BaseModel):
    """Optional per-series and per-entry choices for a read-only CBL plan."""

    series_decisions: dict[str, bool] = Field(default_factory=dict)
    entry_decisions: dict[str, bool] = Field(default_factory=dict)


class CBLSourceFingerprintResponse(BaseModel):
    """Immutable source evidence needed to review and later accept a plan."""

    source_list_id: int
    source_repository: str
    source_path: str
    content_hash: str
    revision_sha: str


class CBLAdoptionEntryResponse(BaseModel):
    """Typed reconciliation and adoption state for one source position."""

    collection_excluded: bool = False
    collection_exclusion_reason: str | None = None
    collection_exclusion_ids: list[int] = Field(default_factory=list)

    cbl_position: int
    cbl_entry_id: int
    series_name: str
    issue_number: str
    series_group_id: str
    volume_year: int | None = None
    publication_year: int | None = None
    adoption_class: Literal["existing", "missing_importable", "ambiguous_unresolved"]
    adoption_decision: Literal[
        "included_existing",
        "would_create_missing",
        "awaiting_opt_in",
        "excluded",
        "unresolved",
    ]
    adopted: bool
    comicvine_issue_id: str | None
    comicvine_series_id: str | None
    series_provider: str | None
    series_external_id: str | None
    resolved_issue_id: int | None
    canonical_issue_id: int | None
    read_status: str | None
    read_at: datetime | None
    resolution_status: str
    is_duplicate_identity: bool


class CBLAdoptionSummaryResponse(BaseModel):
    """Dry-run counts and source-position order for an adoption plan."""

    reused_existing_count: int
    missing_would_create_count: int
    excluded_count: int
    unresolved_count: int
    awaiting_opt_in_count: int
    final_adopted_count: int
    final_adopted_order: list[int]
    reused_existing_positions: list[int]
    missing_would_create_positions: list[int]
    excluded_positions: list[int]
    unresolved_positions: list[int]
    awaiting_opt_in_positions: list[int]


class CBLAdoptionPreviewResponse(BaseModel):
    """Complete typed, read-only CBL adoption preview contract."""

    source: CBLSourceFingerprintResponse
    total_positions: int
    entries: list[CBLAdoptionEntryResponse]
    summary: CBLAdoptionSummaryResponse
def _cbl_position(entry: dict[str, object]) -> int:
    """Return a validated CBL source position from one adoption-plan entry."""
    position = entry.get("cbl_position")
    if isinstance(position, bool) or not isinstance(position, int):
        raise ValueError("CBL adoption entry is missing an integer cbl_position")
    return position


def _adoption_payload(
    report: CBLReconciliationReport,
    plan: CBLAdoptionPlan,
) -> CBLAdoptionPreviewResponse:
    """Serialize the read-only CBL adoption preview and dry-run summary."""
    # The concrete dataclasses are intentionally kept in the service layer;
    # this adapter contains no query or adoption logic.
    adoption_entries = list(plan.entries)
    positions_by_decision = {
        decision: [
            _cbl_position(entry)
            for entry in adoption_entries
            if entry.get("adoption_decision") == decision
        ]
        for decision in (
            "included_existing",
            "would_create_missing",
            "excluded",
            "unresolved",
            "awaiting_opt_in",
        )
    }
    if (
        report.source_list_id is None
        or report.source_repository is None
        or report.source_path is None
    ):
        raise ValueError("CBL adoption preview requires source list provenance")
    if report.content_hash is None or report.revision_sha is None:
        raise ValueError("CBL adoption preview requires source fingerprint")
    return CBLAdoptionPreviewResponse(
        source=CBLSourceFingerprintResponse(
            source_list_id=report.source_list_id,
            source_repository=public_cbl_repository(report.source_repository),
            source_path=report.source_path,
            content_hash=report.content_hash,
            revision_sha=report.revision_sha,
        ),
        total_positions=report.total_positions,
        entries=[CBLAdoptionEntryResponse.model_validate(entry) for entry in adoption_entries],
        summary=CBLAdoptionSummaryResponse(
            reused_existing_count=plan.reused_existing_count,
            missing_would_create_count=plan.missing_would_create_count,
            excluded_count=plan.excluded_count,
            unresolved_count=plan.unresolved_count,
            awaiting_opt_in_count=len(positions_by_decision["awaiting_opt_in"]),
            final_adopted_count=plan.final_adopted_count,
            final_adopted_order=list(plan.final_adopted_order),
            reused_existing_positions=positions_by_decision["included_existing"],
            missing_would_create_positions=positions_by_decision["would_create_missing"],
            excluded_positions=positions_by_decision["excluded"],
            unresolved_positions=positions_by_decision["unresolved"],
            awaiting_opt_in_positions=positions_by_decision["awaiting_opt_in"],
        ),
    )


@router.get("/cbl/{list_id}/adoption-preview", response_model=CBLAdoptionPreviewResponse)
async def api_cbl_adoption_preview(
    list_id: int,
    current_user: Annotated[User, Depends(get_current_user)],
    db: AsyncSession = Depends(get_db),
) -> CBLAdoptionPreviewResponse:
    """Preview all CBL positions and their default read-only adoption choices."""
    report, plan = await preview_cbl_adoption(db, user_id=current_user.id, list_id=list_id)
    return _adoption_payload(report, plan)


@router.post("/cbl/{list_id}/adoption-plan", response_model=CBLAdoptionPreviewResponse)
async def api_cbl_adoption_plan(
    list_id: int,
    request: CBLAdoptionPlanRequest,
    current_user: Annotated[User, Depends(get_current_user)],
    db: AsyncSession = Depends(get_db),
) -> CBLAdoptionPreviewResponse:
    """Calculate a dry-run CBL adoption plan with explicit selection overrides."""
    report, plan = await preview_cbl_adoption(
        db,
        user_id=current_user.id,
        list_id=list_id,
        series_decisions=request.series_decisions,
        entry_decisions=request.entry_decisions,
    )
    return _adoption_payload(report, plan)
