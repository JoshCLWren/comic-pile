"""Issue identity reconciliation diagnostics and canonical repair endpoints."""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth import get_current_user
from app.database import get_db
from app.models.user import User
from app.services.cbl_reconciliation import reconcile_cbl_source_list
from app.services.issue_identity_reconciliation import (
    consolidate_duplicate_issues,
    find_conflicting_provider_identities,
    find_duplicate_physical_issues,
    get_identity_report,
    preview_consolidation,
    resolve_canonical_issue,
)

router = APIRouter(prefix="/api/v1/issue-identity", tags=["issue-identity"])


class DuplicateAnomalyResponse(BaseModel):
    """One duplicated ComicVine physical identity across user issues."""

    comicvine_issue_id: str
    external_identity_id: int
    issue_ids: list[int]
    thread_ids: list[int]
    statuses: list[str]
    has_read: bool
    has_unread: bool
    issue_details: list[dict[str, object]]


class IdentityReportResponse(BaseModel):
    """Focused report of identity anomalies for the authenticated user."""

    total_duplicate_groups: int
    total_affected_issues: int
    anomalies: list[DuplicateAnomalyResponse]
    conflicting_provider_ids: list[dict[str, object]]


class CanonicalResolutionResponse(BaseModel):
    """Canonical physical-issue resolution for a ComicVine identity."""

    comicvine_issue_id: str
    external_identity_id: int
    canonical_issue_id: int | None
    all_issue_ids: list[int]
    is_duplicate: bool
    is_ambiguous: bool
    reason: str


class ConsolidationPreviewResponse(BaseModel):
    """Dry-run or applied consolidation result."""

    comicvine_issue_id: str
    canonical_issue_id: int
    source_issue_ids: list[int]
    read_state_to_preserve: bool
    read_at_to_preserve: str | None
    events_to_move: int
    ratings_to_preserve: bool
    is_ambiguous: bool
    reason: str


class ConsolidationRequest(BaseModel):
    """Request to consolidate duplicate physical-issue rows."""

    comicvine_issue_id: str = Field(..., min_length=1)
    keep_issue_id: int | None = None


@router.get("/report", response_model=IdentityReportResponse)
async def api_identity_report(
    current_user: Annotated[User, Depends(get_current_user)],
    db: AsyncSession = Depends(get_db),
) -> IdentityReportResponse:
    """Report existing duplicate physical-issue rows before mutation.

    Surfaces groups where one confirmed ComicVine identity maps to multiple
    user-owned Issue rows, plus any conflicting provider identity cases.

    Args:
        current_user: Authenticated owner.
        db: Async database session.

    Returns:
        Structured anomaly report for the authenticated user.
    """
    report = await get_identity_report(db, user_id=current_user.id)
    return IdentityReportResponse(
        total_duplicate_groups=report.total_duplicate_groups,
        total_affected_issues=report.total_affected_issues,
        anomalies=[
            DuplicateAnomalyResponse(
                comicvine_issue_id=a.comicvine_issue_id,
                external_identity_id=a.external_identity_id,
                issue_ids=list(a.issue_ids),
                thread_ids=list(a.thread_ids),
                statuses=list(a.statuses),
                has_read=a.has_read,
                has_unread=a.has_unread,
                issue_details=list(a.issue_details),
            )
            for a in report.anomalies
        ],
        conflicting_provider_ids=list(report.conflicting_provider_ids),
    )


@router.get("/anomalies", response_model=list[DuplicateAnomalyResponse])
async def api_list_anomalies(
    current_user: Annotated[User, Depends(get_current_user)],
    db: AsyncSession = Depends(get_db),
) -> list[DuplicateAnomalyResponse]:
    """List duplicate physical-issue anomalies for the authenticated user.

    Args:
        current_user: Authenticated owner.
        db: Async database session.

    Returns:
        One entry per duplicated ComicVine identity.
    """
    anomalies = await find_duplicate_physical_issues(db, user_id=current_user.id)
    return [
        DuplicateAnomalyResponse(
            comicvine_issue_id=a.comicvine_issue_id,
            external_identity_id=a.external_identity_id,
            issue_ids=list(a.issue_ids),
            thread_ids=list(a.thread_ids),
            statuses=list(a.statuses),
            has_read=a.has_read,
            has_unread=a.has_unread,
            issue_details=list(a.issue_details),
        )
        for a in anomalies
    ]


@router.get("/conflicts", response_model=list[dict[str, object]])
async def api_list_conflicts(
    current_user: Annotated[User, Depends(get_current_user)],
    db: AsyncSession = Depends(get_db),
) -> list[dict[str, object]]:
    """List ambiguous conflicting provider identities for the user.

    Args:
        current_user: Authenticated owner.
        db: Async database session.

    Returns:
        One entry per Issue with multiple confirmed ComicVine IDs.
    """
    return await find_conflicting_provider_identities(db, user_id=current_user.id)


@router.get("/canonical/{comicvine_issue_id}", response_model=CanonicalResolutionResponse)
async def api_canonical_resolution(
    comicvine_issue_id: str,
    current_user: Annotated[User, Depends(get_current_user)],
    db: AsyncSession = Depends(get_db),
) -> CanonicalResolutionResponse:
    """Resolve the canonical Issue for one ComicVine physical-issue identity.

    CBL reconciliation uses this same path so external CBL entries that carry
    the same ComicVine issue ID resolve to the canonical read/history holder,
    not whichever duplicate happens to be queried first.

    Args:
        comicvine_issue_id: ComicVine external_id string.
        current_user: Authenticated owner.
        db: Async database session.
    """
    result = await resolve_canonical_issue(
        db, user_id=current_user.id, comicvine_issue_id=comicvine_issue_id
    )
    return CanonicalResolutionResponse(
        comicvine_issue_id=result.comicvine_issue_id,
        external_identity_id=result.external_identity_id,
        canonical_issue_id=result.canonical_issue_id,
        all_issue_ids=list(result.all_issue_ids),
        is_duplicate=result.is_duplicate,
        is_ambiguous=result.is_ambiguous,
        reason=result.reason,
    )


@router.post("/preview-consolidation", response_model=ConsolidationPreviewResponse)
async def api_preview_consolidation(
    request: ConsolidationRequest,
    current_user: Annotated[User, Depends(get_current_user)],
    db: AsyncSession = Depends(get_db),
) -> ConsolidationPreviewResponse:
    """Preview a history-preserving consolidation without mutating rows.

    Args:
        request: ComicVine identity and optional explicit keeper issue.
        current_user: Authenticated owner.
        db: Async database session.
    """
    preview = await preview_consolidation(
        db,
        user_id=current_user.id,
        comicvine_issue_id=request.comicvine_issue_id,
        keep_issue_id=request.keep_issue_id,
    )
    if preview is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="No duplicated identity found for that ComicVine ID")
    return ConsolidationPreviewResponse(
        comicvine_issue_id=preview.comicvine_issue_id,
        canonical_issue_id=preview.canonical_issue_id,
        source_issue_ids=list(preview.source_issue_ids),
        read_state_to_preserve=preview.read_state_to_preserve,
        read_at_to_preserve=preview.read_at_to_preserve.isoformat() if preview.read_at_to_preserve else None,
        events_to_move=preview.events_to_move,
        ratings_to_preserve=preview.ratings_to_preserve,
        is_ambiguous=preview.is_ambiguous,
        reason=preview.reason,
    )


@router.post("/consolidate", response_model=ConsolidationPreviewResponse)
async def api_consolidate(
    request: ConsolidationRequest,
    current_user: Annotated[User, Depends(get_current_user)],
    db: AsyncSession = Depends(get_db),
) -> ConsolidationPreviewResponse:
    """Consolidate duplicate Issue rows for one physical comic without losing history.

    Read state, earliest read_at, and event/rating facts are preserved on the
    canonical row. Ambiguous read/unread divergence requires explicit
    keep_issue_id rather than destructive automatic merge.

    Args:
        request: ComicVine identity and optional explicit keeper.
        current_user: Authenticated owner.
        db: Async database session.
    """
    preview = await preview_consolidation(
        db,
        user_id=current_user.id,
        comicvine_issue_id=request.comicvine_issue_id,
        keep_issue_id=request.keep_issue_id,
    )
    if preview is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="No duplicated identity found for that ComicVine ID")
    if preview.is_ambiguous and request.keep_issue_id is None:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={
                "code": "ambiguous_consolidation",
                "comicvine_issue_id": request.comicvine_issue_id,
                "reason": preview.reason,
                "all_issue_ids": list((await resolve_canonical_issue(db, user_id=current_user.id, comicvine_issue_id=request.comicvine_issue_id)).all_issue_ids),
                "message": "Ambiguous read/unread divergence for same physical issue. Specify keep_issue_id to choose the canonical.",
            },
        )
    if preview.reason == "keep_issue_not_in_duplicate_set":
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="keep_issue_id is not part of the duplicated identity set")
    result = await consolidate_duplicate_issues(
        db,
        user_id=current_user.id,
        comicvine_issue_id=request.comicvine_issue_id,
        keep_issue_id=request.keep_issue_id,
    )
    if result is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="No duplicated identity found")
    await db.commit()
    return ConsolidationPreviewResponse(
        comicvine_issue_id=result.comicvine_issue_id,
        canonical_issue_id=result.canonical_issue_id,
        source_issue_ids=list(result.source_issue_ids),
        read_state_to_preserve=result.read_state_to_preserve,
        read_at_to_preserve=result.read_at_to_preserve.isoformat() if result.read_at_to_preserve else None,
        events_to_move=result.events_to_move,
        ratings_to_preserve=result.ratings_to_preserve,
        is_ambiguous=result.is_ambiguous,
        reason=result.reason,
    )


@router.get("/cbl/{list_id}/reconciliation")
async def api_cbl_reconciliation(
    list_id: int,
    current_user: Annotated[User, Depends(get_current_user)],
    db: AsyncSession = Depends(get_db),
) -> dict[str, object]:
    """Reconcile one CBL source list to canonical physical-issue identities.

    For every source position the response reports the ComicVine issue ID,
    resolved canonical Issue, read state, and whether the entry is affected
    by a duplicate identity. This is the same report the repair workflow uses
    to verify that CBL adoption uses canonical identity.

    Args:
        list_id: CBLSourceList identifier.
        current_user: Authenticated owner whose issues are eligible.
        db: Async database session.
    """
    report = await reconcile_cbl_source_list(db, user_id=current_user.id, list_id=list_id)
    return {
        "list_id": list_id,
        "total_positions": report.total_positions,
        "resolved_count": report.resolved_count,
        "unresolved_count": report.unresolved_count,
        "duplicate_identity_groups": report.duplicate_identity_groups,
        "ambiguous_count": report.ambiguous_count,
        "entries": list(report.entries),
        "first_unread_position": report.first_unread_position,
        "first_unread_entry": report.first_unread_entry,
    }
