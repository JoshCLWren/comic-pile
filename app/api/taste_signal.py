"""Authenticated Taste Bank verdict API (issue #1749).

Exposes endpoints for turning an inferred Taste Bank discovery into an
explicit user verdict (``confirmed``, ``sometimes``, or ``rejected``).
Every route is scoped to the authenticated principal, verdict writes are
idempotent, and inferred evidence columns are never modified by verdict
writes so later inference refreshes cannot clobber explicit user state.
"""

from datetime import UTC, datetime
from typing import Annotated

from fastapi import APIRouter, Depends, Path
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth import get_current_user
from app.database import get_db
from app.models.user import User
from app.repositories.taste_signal import get_user_signals, upsert_signal
from app.schemas.taste_verdict import (
    TasteSignalListResponse,
    TasteSignalResponse,
    TasteSignalType,
    TasteVerdictRequest,
)

router = APIRouter(prefix="/users/me/taste-signals", tags=["taste-signals"])


@router.get(
    "",
    response_model=TasteSignalListResponse,
    summary="List the authenticated user's Taste Bank signals.",
    description=(
        "Return every persisted Taste Bank signal owned by the authenticated "
        "user, ordered by signal type then external key. The list is empty "
        "before any discovery or verdict exists."
    ),
)
async def list_taste_signals(
    current_user: Annotated[User, Depends(get_current_user)],
    db: AsyncSession = Depends(get_db),
) -> TasteSignalListResponse:
    """List every Taste Bank signal owned by the authenticated user.

    Args:
        current_user: The authenticated user making the request.
        db: Async database session.

    Returns:
        All canonical signals for the caller, sorted deterministically.
    """
    signals = await get_user_signals(db, current_user.id)
    return TasteSignalListResponse(
        signals=[TasteSignalResponse.model_validate(signal) for signal in signals]
    )


@router.put(
    "/{signal_type}/{external_key}/verdict",
    response_model=TasteSignalResponse,
    summary="Record an explicit verdict for one Taste Bank signal.",
    description=(
        "Confirm, qualify, or reject a single Taste Bank discovery for the "
        "authenticated user. Only the targeted user 's matching "
        "(signal_type, external_key) row is written. Inferred evidence "
        "columns are preserved untouched and the response time is recorded. "
        "Repeated responses are idempotent; a missing row is created so "
        "direct user assertions work without prior inference."
    ),
)
async def set_taste_signal_verdict(
    payload: TasteVerdictRequest,
    current_user: Annotated[User, Depends(get_current_user)],
    db: AsyncSession = Depends(get_db),
    signal_type: TasteSignalType = Path(...),
    external_key: str = Path(..., min_length=1, max_length=255),
) -> TasteSignalResponse:
    """Record an explicit verdict on one of the caller's Taste Bank signals.

    Args:
        payload: Validated request containing the stable verdict.
        current_user: The authenticated user making the request.
        db: Async database session.
        signal_type: Category of the targeted signal.
        external_key: Stable normalized key of the targeted feature.

    Returns:
        The canonical updated signal after the verdict is persisted.
    """
    now = datetime.now(UTC)
    display_name = external_key.rsplit(":", 1)[-1] or external_key

    signal = await upsert_signal(
        db,
        current_user.id,
        signal_type,
        external_key,
        display_name[:200],
        payload.verdict,
        now,
    )

    # Snapshot before commit: ORM attribute access after commit would expire
    # the instance (MissingGreenlet) and the snapshot is the canonical return.
    updated = TasteSignalResponse.model_validate(signal)

    await db.commit()
    return updated