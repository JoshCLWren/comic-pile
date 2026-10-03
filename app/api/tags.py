"""Tag API routes.

Thin routing layer: authentication, request/response schema validation, HTTP
status mapping, and exactly one service call. Business logic lives in
``app/services/tag_service.py``; persistence lives in
``app/repositories/tag_repository.py``.
"""

from collections.abc import Annotated

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth import get_current_user
from app.database import get_db
from app.models import Tag, TagAssignment
from app.models.user import User
from app.schemas import tags as tag_schemas
from app.services.errors import ConflictError, ForbiddenError, InvalidRequestError, NotFoundError
from app.services.tag_service import TagService

router = APIRouter(prefix="/api/tags", tags=["tags"])

_ERROR_STATUS: dict[type[Exception], int] = {
    NotFoundError: status.HTTP_404_NOT_FOUND,
    ForbiddenError: status.HTTP_403_FORBIDDEN,
    InvalidRequestError: status.HTTP_400_BAD_REQUEST,
    ConflictError: status.HTTP_409_CONFLICT,
}


def _map_error(exc: Exception) -> HTTPException:
    """Translate a service error into its HTTP equivalent."""
    status_code = _ERROR_STATUS.get(type(exc), status.HTTP_500_INTERNAL_SERVER_ERROR)
    return HTTPException(status_code=status_code, detail=str(exc))


@router.get("/", response_model=tag_schemas.TagListResponse)
async def list_tags(
    current_user: Annotated[User, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> tag_schemas.TagListResponse:
    """Return all tags visible to the current user.

    Global tags are visible to everyone; the user also sees their own private
    tags.

    Args:
        current_user: The authenticated user.
        db: Database session.

    Returns:
        List of visible tags.
    """
    service = TagService(db)
    tags = await service.list_tags(current_user)
    return tag_schemas.TagListResponse(tags=[tag_to_response(tag) for tag in tags])


@router.get("/{tag_id}/", response_model=tag_schemas.TagResponse)
async def get_tag(
    tag_id: int,
    current_user: Annotated[User, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> tag_schemas.TagResponse:
    """Return a single tag, enforcing visibility.

    Global tags are visible to any authenticated user; private tags are visible
    only to their owner.

    Args:
        tag_id: Primary key of the tag.
        current_user: The authenticated user.
        db: Database session.

    Returns:
        The visible tag.

    Raises:
        HTTPException 404: When the tag does not exist or is not visible.
    """
    service = TagService(db)
    tag = await service.get_tag(current_user, tag_id)
    return tag_to_response(tag)


@router.post("/", response_model=tag_schemas.TagCreateResponse)
async def create_tag(
    request: tag_schemas.TagCreate,
    current_user: Annotated[User, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> tag_schemas.TagCreateResponse:
    """Create a tag or return an existing global tag.

    Non-admin users can only create private tags. When the normalized name
    matches an existing global tag, the global tag is returned instead of
    creating a duplicate.

    Args:
        request: The creation request.
        current_user: The authenticated user.
        db: Database session.

    Returns:
        The resulting tag and creation metadata.

    Raises:
        HTTPException 403: When a non-admin requests a global tag.
        HTTPException 400: When the color is invalid or the name is empty.
        HTTPException 409: When a requested name collides with an existing global.
    """
    service = TagService(db)
    result = await service.create_tag(
        current_user,
        name=request.name,
        color=request.color,
        scope=request.scope.value if hasattr(request.scope, "value") else request.scope,
        include_near_matches=request.include_near_matches,
    )
    response = tag_schemas.TagCreateResponse(
        tag=tag_to_response(result.tag),
        redirected_to_global=result.redirected_to_global,
        near_matches=[near_match_to_response(tag) for tag in result.near_matches],
    )
    return response


@router.put("/{tag_id}/", response_model=tag_schemas.TagResponse)
async def update_tag(
    tag_id: int,
    request: tag_schemas.TagUpdate,
    current_user: Annotated[User, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> tag_schemas.TagResponse:
    """Update an existing tag.

    Global tags require admin access; private tags require ownership or admin
    access. Renaming a private tag to a global name is refused.

    Args:
        tag_id: Primary key of the tag.
        request: The update request.
        current_user: The authenticated user.
        db: Database session.

    Returns:
        The updated tag.

    Raises:
        HTTPException 403: When the user lacks permission.
        HTTPException 400: When the color is invalid.
        HTTPException 409: When the new name collides with a global tag.
    """
    service = TagService(db)
    tag = await service.update_tag(
        current_user,
        tag_id,
        name=request.name,
        color=request.color,
    )
    return tag_to_response(tag)


@router.delete("/{tag_id}/", response_model=tag_schemas.TagDeleteResponse)
async def delete_tag(
    tag_id: int,
    current_user: Annotated[User, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> tag_schemas.TagDeleteResponse:
    """Delete a tag and cascade its assignments.

    Global tags require admin access; private tags require ownership or admin
    access. Deletion removes all assignments and runs registered deletion hook
    consumers.

    Args:
        tag_id: Primary key of the tag.
        current_user: The authenticated user.
        db: Database session.

    Returns:
        Deletion statistics.

    Raises:
        HTTPException 403: When the user lacks permission.
    """
    service = TagService(db)
    result = await service.delete_tag(current_user, tag_id)
    return tag_schemas.TagDeleteResponse(
        tag_id=result.tag.id,
        assignments_removed=result.assignments_removed,
        references_removed_by_consumers=result.references_removed_by_consumers,
    )


@router.post("/{tag_id}/assign/", response_model=tag_schemas.TagAssignmentResponse)
async def assign_tag(
    tag_id: int,
    request: tag_schemas.TagAssignmentRequest,
    current_user: Annotated[User, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> tag_schemas.TagAssignmentResponse:
    """Attach a tag to a target.

    Global tags require admin access to assign. Private tags require ownership
    of the tag and of the target (or admin access). Assignment is idempotent.

    Args:
        tag_id: Primary key of the tag.
        request: The assignment request.
        current_user: The authenticated user.
        db: Database session.

    Returns:
        The assignment.

    Raises:
        HTTPException 403: When the user lacks permission.
        HTTPException 404: When the tag or target does not exist.
    """
    service = TagService(db)
    assignment = await service.assign_tag(
        current_user,
        tag_id,
        request.target_type.value if hasattr(request.target_type, "value") else request.target_type,
        request.target_id,
    )
    return tag_assignment_to_response(assignment)


@router.delete("/{tag_id}/unassign/", response_model=tag_schemas.TagAssignmentResponse)
async def unassign_tag(
    tag_id: int,
    request: tag_schemas.TagAssignmentRequest,
    current_user: Annotated[User, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> tag_schemas.TagAssignmentResponse:
    """Remove an assignment from a target.

    Global tags can be unassigned only by admins; private tags by their owner
    or an admin.

    Args:
        tag_id: Primary key of the tag.
        request: The unassignment request.
        current_user: The authenticated user.
        db: Database session.

    Returns:
        The removed assignment.

    Raises:
        HTTPException 403: When the user lacks permission.
        HTTPException 404: When the tag or assignment does not exist.
    """
    service = TagService(db)
    assignment = await service.unassign_tag(
        current_user,
        tag_id,
        request.target_type.value if hasattr(request.target_type, "value") else request.target_type,
        request.target_id,
    )
    return tag_assignment_to_response(assignment)


@router.get("/{tag_id}/usage/", response_model=tag_schemas.TagUsageResponse)
async def get_tag_usage(
    tag_id: int,
    current_user: Annotated[User, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> tag_schemas.TagUsageResponse:
    """Return assignment usage information for a tag.

    Useful before deleting a private tag so the UI can confirm how many
    objects reference it.

    Args:
        tag_id: Primary key of the tag.
        current_user: The authenticated user.
        db: Database session.

    Returns:
        Assignment counts by target type and total.
    """
    service = TagService(db)
    _ = await service.get_tag(current_user, tag_id)
    total = await service.count_assignments(tag_id)
    by_type = await service.count_assignments_by_target_type(tag_id)
    return tag_schemas.TagUsageResponse(
        tag_id=tag_id,
        total_assignments=total,
        assignments_by_target_type=by_type,
        references_removed_by_consumers={},
    )


def tag_to_response(tag: Tag) -> tag_schemas.TagResponse:
    """Convert an ORM tag to its API response model."""
    return tag_schemas.TagResponse(
        id=tag.id,
        name=tag.name,
        normalized_name=tag.normalized_name,
        scope=tag.scope,
        owner_user_id=tag.owner_user_id,
        color=tag.color,
        created_at=tag.created_at,
        updated_at=tag.updated_at,
    )


def near_match_to_response(tag: Tag) -> tag_schemas.NearMatchResponse:
    """Convert a near-match ORM tag to its API response model."""
    return tag_schemas.NearMatchResponse(
        id=tag.id,
        name=tag.name,
        color=tag.color,
        normalized_name=tag.normalized_name,
        scope=tag.scope,
    )


def tag_assignment_to_response(assignment: TagAssignment) -> tag_schemas.TagAssignmentResponse:
    """Convert an ORM assignment to its API response model."""
    return tag_schemas.TagAssignmentResponse(
        id=assignment.id,
        tag_id=assignment.tag_id,
        target_type=assignment.target_type,
        target_id=assignment.target_id,
        created_at=assignment.created_at,
    )
