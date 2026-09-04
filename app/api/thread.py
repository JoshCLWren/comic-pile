"""Thread CRUD API endpoints.

Thin routing layer: authentication, request/response schema validation,
HTTP status mapping, and rate limiting/caching decorators. Business logic
lives in ``app/services/thread_service.py``; query construction lives in
``app/repositories/``.
"""

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from fastapi.responses import HTMLResponse
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth import get_current_user
from app.cache import TTL, cached
from app.database import get_db
from app.middleware import limiter
from app.models.user import User
from app.schemas import (
    MigrateToIssuesRequest,
    QueueThreadListResponse,
    ReactivateRequest,
    RollResponse,
    SetCurrentIssueRequest,
    SetCurrentIssueResponse,
    ThreadCreate,
    ThreadDetail,
    ThreadResponse,
    ThreadUpdate,
)
from app.schemas.migration import MigrateToIssuesSimpleRequest
from app.repositories.session_repository import fetch_active_session
from app.services import thread_service
from app.services.errors import (
    ConflictError,
    ForbiddenError,
    InvalidRequestError,
    NotFoundError,
    ServiceError,
)

router = APIRouter(tags=["threads"])

_ERROR_STATUS: dict[type[ServiceError], int] = {
    NotFoundError: status.HTTP_404_NOT_FOUND,
    InvalidRequestError: status.HTTP_400_BAD_REQUEST,
    ConflictError: status.HTTP_409_CONFLICT,
    ForbiddenError: status.HTTP_403_FORBIDDEN,
}


def _map_service_error(exc: ServiceError) -> HTTPException:
    """Translate a domain error into its HTTP equivalent.

    Args:
        exc: Domain error raised by a service function.

    Returns:
        HTTPException carrying the mapped status code and client-safe detail.
    """
    return HTTPException(status_code=_ERROR_STATUS[type(exc)], detail=exc.detail)


@router.get("/stale", response_model=list[ThreadResponse])
async def list_stale_threads(
    current_user: Annotated[User, Depends(get_current_user)],
    db: AsyncSession = Depends(get_db),
    days: int = 30,
) -> list[ThreadResponse]:
    """List the authenticated user's threads not read in ``days`` (default 30)."""
    try:
        session = await fetch_active_session(db, current_user.id)
        snoozed = session.snoozed_thread_ids if session else None
        snoozed_ids = list(snoozed) if snoozed else None
        return await thread_service.list_stale_thread_responses(
            db, current_user.id, days, snoozed_ids=snoozed_ids
        )
    except ServiceError as exc:
        raise _map_service_error(exc) from exc


@router.get("/", response_model=QueueThreadListResponse)
@limiter.limit("100/minute")
@cached(ttl=TTL.SHORT)
async def list_threads(
    request: Request,
    current_user: Annotated[User, Depends(get_current_user)],
    db: AsyncSession = Depends(get_db),
    search: str | None = Query(default=None, min_length=1),
    sort: str = Query(
        default="position",
        description="Sort order: position, title, or created",
    ),
    page_size: int = Query(
        default=50,
        ge=1,
        le=200,
        description="Number of threads to return per page (default 50, max 200)",
    ),
    page_token: str | None = Query(
        default=None, description="Opaque cursor token for pagination continuation"
    ),
) -> QueueThreadListResponse:
    """List threads with deterministic cursor-based pagination.

    Every retained sort has a deterministic cursor contract with stable
    tie-breakers so that search results remain correct across multiple pages.
    Changing ``search`` or ``sort`` invalidates any prior cursor.

    Args:
        request: FastAPI request object for rate limiting.
        search: Optional case-insensitive title search filter.
        sort: Sort order – ``position`` (default), ``title``, or ``created``.
        page_size: Threads per page (default 50, max 200).
        page_token: Opaque cursor token for pagination continuation.
        current_user: The authenticated user making the request.
        db: SQLAlchemy session for database operations.

    Returns:
        Paginated queue items plus ``next_page_token`` when more pages exist.

    Raises:
        HTTPException: If a retired ``collection_id`` query parameter is present,
            the sort value is unsupported, or the page token is stale/malformed.
    """
    if "collection_id" in request.query_params:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="collection_id is retired",
        )

    if sort not in {"position", "title", "created"}:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="sort must be one of: position, title, created",
        )

    try:
        return await thread_service.list_queue_threads(
            db,
            current_user.id,
            search=search,
            sort=sort,
            page_size=page_size,
            page_token=page_token,
        )
    except ServiceError as exc:
        raise _map_service_error(exc) from exc


@router.get("/completed", response_class=HTMLResponse)
async def list_completed_threads(
    request: Request,
    current_user: Annotated[User, Depends(get_current_user)],
    db: AsyncSession = Depends(get_db),
) -> str:
    """Render completed threads as options for the reactivation modal."""
    return await thread_service.completed_threads_html(db, current_user.id)


@router.get("/active", response_class=HTMLResponse)
async def list_active_threads(
    request: Request,
    current_user: Annotated[User, Depends(get_current_user)],
    db: AsyncSession = Depends(get_db),
) -> str:
    """Render active threads as radio buttons for the override modal."""
    return await thread_service.active_threads_html(db, current_user.id)


@router.post("/", response_model=ThreadResponse, status_code=status.HTTP_201_CREATED)
@limiter.limit("30/minute")
async def create_thread(
    request: Request,
    thread_data: ThreadCreate,
    current_user: Annotated[User, Depends(get_current_user)],
    db: AsyncSession = Depends(get_db),
) -> ThreadResponse:
    """Create a new thread at the end of the user's queue.

    Args:
        request: FastAPI request object for rate limiting.
        thread_data: Thread creation data.
        current_user: The authenticated user making the request.
        db: SQLAlchemy session for database operations.

    Returns:
        ThreadResponse with created thread details.
    """
    return await thread_service.create_thread_with_retry(db, current_user.id, thread_data)


@router.get("/{thread_id}", response_model=ThreadDetail)
@cached(ttl=TTL.MEDIUM)
async def get_thread(
    thread_id: int,
    current_user: Annotated[User, Depends(get_current_user)],
    db: AsyncSession = Depends(get_db),
) -> ThreadDetail:
    """Get a single owned thread by ID.

    Raises:
        HTTPException: 404 when the thread does not exist for this user.
    """
    try:
        return await thread_service.get_thread_detail(db, current_user.id, thread_id)
    except ServiceError as exc:
        raise _map_service_error(exc) from exc


@router.put("/{thread_id}", response_model=ThreadResponse)
async def update_thread(
    thread_id: int,
    thread_data: ThreadUpdate,
    current_user: Annotated[User, Depends(get_current_user)],
    db: AsyncSession = Depends(get_db),
) -> ThreadResponse:
    """Update an owned thread.

    Args:
        thread_id: The thread ID to update.
        thread_data: Thread update data.
        current_user: The authenticated user making the request.
        db: SQLAlchemy session for database operations.

    Returns:
        ThreadResponse with updated thread details.
    """
    try:
        return await thread_service.update_thread(db, current_user.id, thread_id, thread_data)
    except ServiceError as exc:
        raise _map_service_error(exc) from exc


@router.delete("/{thread_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_thread(
    thread_id: int,
    current_user: Annotated[User, Depends(get_current_user)],
    db: AsyncSession = Depends(get_db),
) -> None:
    """Delete a thread and prune dependent session/continuity state.

    Raises:
        HTTPException: 404 when not found; 400 when deletion is refused.
    """
    try:
        await thread_service.delete_thread(db, current_user.id, thread_id)
    except ServiceError as exc:
        raise _map_service_error(exc) from exc


@router.post("/reactivate", response_model=ThreadResponse)
async def reactivate_thread(
    request: ReactivateRequest,
    current_user: Annotated[User, Depends(get_current_user)],
    db: AsyncSession = Depends(get_db),
) -> ThreadResponse:
    """Reactivate a completed thread by adding more issues.

    Raises:
        HTTPException: 404 when not found; 400 when not completed or the issue
            count is invalid.
    """
    try:
        return await thread_service.reactivate_completed_thread(db, current_user.id, request)
    except ServiceError as exc:
        raise _map_service_error(exc) from exc


@router.post("/{thread_id}/set-pending", response_model=RollResponse)
async def set_pending_thread(
    thread_id: int,
    current_user: Annotated[User, Depends(get_current_user)],
    db: AsyncSession = Depends(get_db),
) -> RollResponse:
    """Set a thread as pending for rating (manual selection).

    Raises:
        HTTPException: 404 when not found; 400 when inactive, blocked, or out of issues.
    """
    try:
        return await thread_service.set_pending_thread(db, current_user.id, thread_id)
    except ServiceError as exc:
        raise _map_service_error(exc) from exc


@router.put("/{thread_id}/test-backdate", response_model=ThreadResponse)
async def backdate_thread_for_testing(
    thread_id: int,
    current_user: Annotated[User, Depends(get_current_user)],
    db: AsyncSession = Depends(get_db),
    days_ago: int = Query(..., ge=1, le=3650, description="Number of days to backdate the thread"),
) -> ThreadResponse:
    """Backdate a thread's last_activity_at (test environments only).

    Args:
        thread_id: The thread ID to backdate.
        current_user: The authenticated user making the request.
        db: SQLAlchemy session for database operations.
        days_ago: Number of days to backdate last_activity_at (1-3650).

    Returns:
        ThreadResponse with updated thread details.
    """
    try:
        return await thread_service.backdate_thread_for_testing(
            db, current_user.id, thread_id, days_ago
        )
    except ServiceError as exc:
        raise _map_service_error(exc) from exc


@router.post("/{thread_id}:migrateToIssues", response_model=ThreadResponse)
async def migrate_thread_to_issues(
    thread_id: int,
    request: MigrateToIssuesRequest,
    current_user: Annotated[User, Depends(get_current_user)],
    db: AsyncSession = Depends(get_db),
) -> ThreadResponse:
    """Migrate an old-style thread to issue tracking (#1..total_issues).

    Marks #1 through ``last_issue_read`` as read and updates the thread's
    issue-tracking fields.

    Raises:
        HTTPException: 404 if thread not found, 400 if validation fails.
    """
    try:
        return await thread_service.migrate_thread_to_issues(
            db,
            current_user.id,
            thread_id,
            last_issue_read=request.last_issue_read,
            total_issues=request.total_issues,
        )
    except ServiceError as exc:
        raise _map_service_error(exc) from exc


@router.post("/{thread_id}:migrateToIssuesSimple", response_model=ThreadResponse)
async def migrate_thread_to_issues_simple(
    thread_id: int,
    request: MigrateToIssuesSimpleRequest,
    current_user: Annotated[User, Depends(get_current_user)],
    db: AsyncSession = Depends(get_db),
) -> ThreadResponse:
    """Simplified migration inferred from the issue just rated.

    Marks earlier issues read, keeps the rated issue unread so the rating
    flow can mark it read, and points ``next_unread_issue_id`` at it.

    Raises:
        HTTPException: 404 if thread not found, 400 if validation fails.
    """
    try:
        return await thread_service.migrate_thread_to_issues_simple(
            db,
            current_user.id,
            thread_id,
            issue_number=request.issue_number,
        )
    except ServiceError as exc:
        raise _map_service_error(exc) from exc


@router.post("/{thread_id}:setCurrentIssue", response_model=SetCurrentIssueResponse)
async def set_current_issue(
    thread_id: int,
    request: SetCurrentIssueRequest,
    current_user: Annotated[User, Depends(get_current_user)],
    db: AsyncSession = Depends(get_db),
) -> SetCurrentIssueResponse:
    """Atomically correct the current issue for an active thread.

    Marks every earlier issue read, ensures the target is unread, updates
    ``thread.next_unread_issue_id``, and pins ``session.pending_issue_id``.

    Raises:
        HTTPException: 404 if thread or issue not found, 400 for validation errors.
    """
    try:
        return await thread_service.set_current_issue(
            db,
            current_user.id,
            thread_id,
            issue_number=request.issue_number,
        )
    except ServiceError as exc:
        raise _map_service_error(exc) from exc


@router.get("/cbls", response_model=list[CBLSourceResponse])
async def list_cbls(
    current_user: Annotated[User, Depends(get_current_user)],
    db: AsyncSession = Depends(get_db),
) -> list[CBLSourceResponse]:
    """List available CBL (Comic Book List) sources for the authenticated user."""
    try:
        return await thread_service.list_cbl_sources(db, current_user.id)
    except ServiceError as exc:
        raise _map_service_error(exc) from exc


@router.post("/previewAdoption", response_model=CBLadoptionPlanResponse)
async def preview_cbl_adoption(
    request: dict[str, Any],
    current_user: Annotated[User, Depends(get_current_user)],
    db: AsyncSession = Depends(get_db),
) -> CBLadoptionPlanResponse:
    """Preview the adoption of a CBL (Comic Book List) for the authenticated user."""
    try:
        cbl_id = request.get("cbl_id")
        if cbl_id is None:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Missing cbl_id parameter"
            )
        return await thread_service.preview_cbl_adoption(db, current_user.id, cbl_id)
    except ServiceError as exc:
        raise _map_service_error(exc) from exc
    except Exception as exc:
        # Re-raise HTTPException to let FastAPI handle it
        if isinstance(exc, HTTPException):
            raise exc
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=str(exc)
        )


@router.post("/adoptCBL", status_code=status.HTTP_201_CREATED)
async def adopt_cbl(
    request: Dict[str, Any],
    current_user: Annotated[User, Depends(get_current_user)],
    db: AsyncSession = Depends(get_db),
):
    """Adopt a CBL (Comic Book List) for the authenticated user."""
    try:
        cbl_id = request.get("cbl_id")
        selections = request.get("selections", {})
        if cbl_id is None:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Missing cbl_id parameter"
            )
        await thread_service.adopt_cbl(db, current_user.id, cbl_id, selections)
        return None
    except ServiceError as exc:
        raise _map_service_error(exc) from exc
    except Exception as exc:
        # Re-raise HTTPException to let FastAPI handle it
        if isinstance(exc, HTTPException):
            raise exc
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=str(exc)
        )
