"""CBL source discovery and canonical Reading Plan adoption endpoints."""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth import get_current_user
from app.database import get_db
from app.models.user import User
from app.repositories.cbl_source_repository import discover_cbl_source_lists as discover_source_rows
from app.services.cbl_plan_adoption import (
    CBLPlanAdoptionError,
    CBLPlanAdoptionStaleError,
    CBLReviewedSource,
    commit_existing_cbl_entries_to_reading_plan,
)

router = APIRouter(prefix="/issue-identity", tags=["issue-identity"])


class CBLSourceListDiscoveryItem(BaseModel):
    """One active persisted source list that may be previewed by Add material."""

    id: int
    name: str
    source_path: str
    source_repository: str
    declared_issue_count: int | None
    content_hash: str
    revision_sha: str


class CBLReviewedSourceRequest(BaseModel):
    """Source fingerprint the reader reviewed before committing."""

    source_list_id: int = Field(gt=0)
    source_repository: str = Field(min_length=1)
    source_path: str = Field(min_length=1)
    content_hash: str = Field(min_length=1)
    revision_sha: str = Field(min_length=1)


class CBLReadingPlanCommitRequest(BaseModel):
    """Exact reviewed CBL preview facts and decisions to commit."""

    source: CBLReviewedSourceRequest
    reviewed_entries: list[dict[str, object]]
    reviewed_final_positions: list[int]
    series_decisions: dict[str, bool] = Field(default_factory=dict)
    entry_decisions: dict[str, bool] = Field(default_factory=dict)


class CBLReadingPlanCommitResponse(BaseModel):
    """Machine-readable result of one canonical Reading Plan mutation."""

    plan_id: int
    source_list_id: int
    reused_issue_ids: list[int]
    added_issue_ids: list[int]
    excluded_source_positions: list[int]
    unresolved_source_positions: list[int]
    awaiting_opt_in_source_positions: list[int]
    final_adopted_source_positions: list[int]
    idempotent_replay: bool


@router.get("/cbl-sources", response_model=list[CBLSourceListDiscoveryItem])
async def discover_cbl_source_lists(
    current_user: Annotated[User, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
    q: Annotated[str | None, Query(max_length=200)] = None,
    limit: Annotated[int, Query(ge=1, le=100)] = 25,
) -> list[CBLSourceListDiscoveryItem]:
    """Return bounded active CBL lists for the Reading Plan Add-material flow."""
    del current_user
    rows = await discover_source_rows(db, query_text=q, limit=limit)
    return [
        CBLSourceListDiscoveryItem(
            id=source_list.id,
            name=source_list.name,
            source_path=source_list.source_path,
            source_repository=repository,
            declared_issue_count=source_list.declared_issue_count,
            content_hash=source_list.content_hash,
            revision_sha=source_list.revision_sha,
        )
        for source_list, repository in rows
    ]


@router.post(
    "/cbl-sources/{list_id}/reading-plans/{plan_id}/commit",
    response_model=CBLReadingPlanCommitResponse,
)
async def commit_cbl_source_to_reading_plan(
    list_id: int,
    plan_id: int,
    request: CBLReadingPlanCommitRequest,
    current_user: Annotated[User, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> CBLReadingPlanCommitResponse:
    """Commit an exact reviewed CBL selection into the same Reading Plan."""
    try:
        result = await commit_existing_cbl_entries_to_reading_plan(
            db,
            user_id=current_user.id,
            plan_id=plan_id,
            list_id=list_id,
            reviewed_source=CBLReviewedSource(
                source_list_id=request.source.source_list_id,
                source_repository=request.source.source_repository,
                source_path=request.source.source_path,
                content_hash=request.source.content_hash,
                revision_sha=request.source.revision_sha,
            ),
            reviewed_entries=request.reviewed_entries,
            reviewed_final_positions=request.reviewed_final_positions,
            series_decisions=request.series_decisions,
            entry_decisions=request.entry_decisions,
        )
    except CBLPlanAdoptionStaleError as exc:
        await db.rollback()
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={"code": exc.code, "message": str(exc)},
        ) from exc
    except CBLPlanAdoptionError as exc:
        await db.rollback()
        status_code = (
            status.HTTP_404_NOT_FOUND
            if exc.code == "reading_plan_not_found"
            else status.HTTP_422_UNPROCESSABLE_CONTENT
        )
        raise HTTPException(
            status_code=status_code,
            detail={"code": exc.code, "message": str(exc)},
        ) from exc

    return CBLReadingPlanCommitResponse(
        plan_id=result.plan_id,
        source_list_id=result.source_list_id,
        reused_issue_ids=list(result.reused_issue_ids),
        added_issue_ids=list(result.added_issue_ids),
        excluded_source_positions=list(result.excluded_source_positions),
        unresolved_source_positions=list(result.unresolved_source_positions),
        awaiting_opt_in_source_positions=list(result.awaiting_opt_in_source_positions),
        final_adopted_source_positions=list(result.final_adopted_source_positions),
        idempotent_replay=result.idempotent_replay,
    )
