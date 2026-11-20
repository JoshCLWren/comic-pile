"""Legacy Python catalog series-mapping preview handler (retired in favor of native Rust same-path)."""

from typing import Annotated

from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.auth import get_current_user
from app.models.user import User
from app.schemas.catalog import (
    SeriesMappingPreviewRequest,
    SeriesMappingPreviewResponse,
)
from app.services.catalog import (
    preview_series_mapping as preview_series_mapping_svc,
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
