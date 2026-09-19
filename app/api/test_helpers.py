"""Test-only API endpoints for E2E browser fixtures."""

from typing import Annotated

from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth import get_current_user
from app.database import get_db
from app.models import User
from app.schemas.test_fixtures import TestCblSourceCreate, TestCblSourceResponse
from app.services.test_helpers import (
    create_test_cbl_source as seed_test_cbl_source,
    create_test_issue_identity as seed_test_issue_identity,
    create_test_reading_order as seed_test_reading_order,
    expire_current_session as expire_test_session,
)

router = APIRouter(prefix="/test", tags=["test"])


@router.post("/reading-orders")
async def create_test_reading_order(
    payload: dict[str, object],
    current_user: Annotated[User, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> dict[str, object]:
    """Create a reading order (with optional items) for E2E tests.

    Only available in test environments. Accepts a name and a list of
    thread_id/position items so browser tests can seed projection targets.
    """
    return await seed_test_reading_order(
        db,
        user_id=current_user.id,
        payload=payload,
    )


@router.post("/issue-identity")
async def create_test_issue_identity(
    payload: dict[str, object],
    current_user: Annotated[User, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> dict[str, object]:
    """Confirm a synthetic ComicVine identity with rich metadata for owned issues.

    Browser fixtures need deterministic cover/series rendering without the
    upstream ComicVine provider. This test-only helper persists a confirmed
    identity (with a complete provider payload so inline hydration is never
    triggered) for one issue or every issue of one owned thread.

    Args:
        payload: ``issue_id`` or ``thread_id``, plus optional ``series_name``,
            ``series_id`` and ``image_url``.
        current_user: Owner of the issues being re-identified.
        db: Database session.

    Returns:
        Affected issue ids plus the resolved series name and id.

    Raises:
        HTTPException: Outside test environments, or when the referenced
            issue/thread does not exist or is not owned by the caller.
    """
    return await seed_test_issue_identity(
        db,
        user_id=current_user.id,
        payload=payload,
    )


@router.post("/cbl-source", response_model=TestCblSourceResponse)
async def create_test_cbl_source(
    payload: TestCblSourceCreate,
    current_user: Annotated[User, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> TestCblSourceResponse:
    """Seed one discoverable CBL source list for browser golden-path coverage.

    Entries may reference owned issues (existing) or ComicVine identities that are
    not mapped to any owned issue (missing_importable). This endpoint never creates
    production migration state.
    """
    return await seed_test_cbl_source(db, user_id=current_user.id, payload=payload)


@router.post("/sessions/expire")
async def expire_current_session(
    current_user: Annotated[User, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> dict[str, str]:
    """Expire the current active session by setting started_at to an old timestamp.

    This endpoint is only available in test environment and is used for E2E testing
    of session expiry notifications.

    Args:
        current_user: The authenticated user making the request.
        db: SQLAlchemy session for database operations.

    Returns:
        Dictionary with success message.

    Raises:
        HTTPException: If not in test environment or no active session found.
    """
    return await expire_test_session(db, user_id=current_user.id)
