"""Catalog API endpoints for series-mapping preview and commit.

Only the two operations the browser calls remain
(``POST /catalog/series-mappings/preview`` and
``POST /catalog/series-mappings/commit``); the unused search, upsert,
attach, and mapping-list handlers were pruned as zero-browser dead code.
"""

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.auth import get_current_user
from app.models.user import User
from app.schemas.catalog import (
    SeriesMappingPreviewRequest,
    SeriesMappingPreviewResponse,
    SeriesMappingCommitRequest,
    SeriesMappingCommitResponse,
)
from app.services.catalog import (
    preview_series_mapping as preview_series_mapping_svc,
)
from app.services.catalog_series_commit import (
    SeriesMappingCommitConflictError,
    commit_series_mapping as commit_series_mapping_svc,
)

router = APIRouter(prefix="/api/v1", tags=["catalog"])


@router.post(
    "/catalog/series-mappings/preview",
    response_model=SeriesMappingPreviewResponse,
)
async def preview_series_mapping(
    request: SeriesMappingPreviewRequest,
    current_user: Annotated[User, Depends(get_current_user)],
    db: AsyncSession = Depends(get_db),
) -> SeriesMappingPreviewResponse:
    """Preview a series mapping with safe scoping and classification.

    This endpoint provides a read-only preview of what issues would be mapped
    to a selected ComicVine series, with safe scoping rules and classification
    of each issue mapping status.

    Args:
        request: Preview request with origin issue, provider, and series ID.
        current_user: Authenticated user for authorization.
        db: Database session.

    Returns:
        Preview response with scope information, counts, and classified rows.
    """
    preview_data = await preview_series_mapping_svc(
        db,
        user_id=current_user.id,
        origin_issue_id=request.origin_issue_id,
        provider=request.provider,
        provider_series_external_id=request.provider_series_external_id,
        scope_mode=request.scope_mode,
    )

    # Convert the service response to the schema response format. Pydantic
    # validates the service's documented dict contract instead of relying on
    # the router to restate every nested field type.
    return SeriesMappingPreviewResponse.model_validate(preview_data)


@router.post(
    "/catalog/series-mappings/commit",
    response_model=SeriesMappingCommitResponse,
)
async def commit_series_mapping(
    request: SeriesMappingCommitRequest,
    current_user: Annotated[User, Depends(get_current_user)],
    db: AsyncSession = Depends(get_db),
) -> SeriesMappingCommitResponse:
    """Commit user-approved safe series mappings transactionally and idempotently.

    Only rows the referenced preview classified ``safe_exact_match`` may be approved. The
    preview token signature, user binding, and TTL are verified, current database state is
    revalidated, and every identity write commits in one transaction. Metadata hydration is
    handed off only after that commit.

    Args:
        request: Commit request with preview token, idempotency key, and approved row ids.
        current_user: Authenticated user for authorization.
        db: Database session.

    Returns:
        The confirmed, already-confirmed, needs-review, and hydration-queued issue ids plus
        the established series evidence.

    Raises:
        HTTPException: 409 ``preview_stale``/``preview_expired``/``confirmed_mapping_conflict``/
            ``idempotency_conflict`` or 422 ``invalid_approved_row``. No identity write has
            been committed in any of those cases.
    """
    try:
        commit_data = await commit_series_mapping_svc(
            db,
            user_id=current_user.id,
            preview_token=request.preview_token,
            idempotency_key=request.idempotency_key,
            approved_row_ids=request.approved_row_ids,
        )
    except SeriesMappingCommitConflictError as exc:
        raise HTTPException(status_code=exc.status_code, detail=exc.code) from exc

    return SeriesMappingCommitResponse.model_validate(commit_data)
