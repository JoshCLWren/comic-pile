"""Taste Bank API endpoints.

Provides authenticated access to a user's inferred taste signals and
endpoints to trigger taste-bank rebuilds.

Rebuild endpoints are restricted to test environments; reading and verdict
endpoints are available everywhere.
"""

from __future__ import annotations

import os
from datetime import UTC, datetime
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth import get_current_user
from app.database import get_db
from app.models.taste_signal import TasteSignal
from app.models.user import User
from app.schemas.taste_bank import (
    TasteBankRebuildResponse,
    TasteBankSignalResponse,
    TasteBankSummaryResponse,
    TasteSignalVerdictUpdate,
)
from app.services.taste_bank_inference import rebuild_user_taste_bank

router = APIRouter(prefix="/api/v1/taste-bank", tags=["taste-bank"])


def _require_test_environment() -> None:
    """Reject test-only endpoints outside the E2E environment."""
    if os.getenv("TEST_ENVIRONMENT") != "true":
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="This endpoint is only available in test environment",
        )


def _signal_to_response(signal: TasteSignal) -> TasteBankSignalResponse:
    """Map a persisted :class:`TasteSignal` row onto its API response.

    Args:
        signal: Persisted taste-signal row from the database.

    Returns:
        API response carrying the signal's inferred state and verdict.
    """
    return TasteBankSignalResponse(
        id=signal.id,
        user_id=signal.user_id,
        signal_type=signal.signal_type,
        stable_key=signal.external_key,
        display_name=signal.display_name,
        inferred_affinity=(
            signal.affinity_estimate if signal.affinity_estimate is not None else 0.0
        ),
        evidence_count=signal.evidence_count,
        distinct_threads_count=signal.distinct_thread_count,
        confidence=signal.confidence if signal.confidence is not None else 0.0,
        user_verdict=signal.user_verdict,
        last_observed_at=(
            signal.last_observed_at.isoformat() if signal.last_observed_at else None
        ),
        prompt_suppressed=(
            signal.prompt_suppressed_until is not None
            and signal.prompt_suppressed_until > datetime.now(UTC)
        ),
    )


@router.get(
    "/user/{user_id}",
    response_model=TasteBankSummaryResponse,
)
async def get_user_taste_bank(
    user_id: int,
    current_user: Annotated[User, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> TasteBankSummaryResponse:
    """Return the inferred Taste Bank for the requesting user.

    Only the authenticated user's own taste bank is accessible.

    Args:
        user_id: Target user ID (must match authenticated user).
        current_user: Authenticated user from the access token.
        db: Async database session.

    Returns:
        Summary of inferred taste signals with confidence and verdict.
    """
    if current_user.id != user_id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="You can only access your own taste bank",
        )

    result = await db.execute(
        select(TasteSignal)
        .where(TasteSignal.user_id == user_id)
        .order_by(TasteSignal.confidence.desc())
    )
    signals = result.scalars().all()

    high_confidence = sum(1 for s in signals if (s.confidence or 0.0) >= 0.7)
    explicit_verdict = sum(1 for s in signals if s.user_verdict is not None)

    return TasteBankSummaryResponse(
        signals=[_signal_to_response(s) for s in signals],
        total_signals=len(signals),
        high_confidence_count=high_confidence,
        explicit_verdict_count=explicit_verdict,
    )


@router.post(
    "/user/{user_id}/rebuild",
    response_model=TasteBankRebuildResponse,
)
async def rebuild_user_taste_bank_endpoint(
    user_id: int,
    current_user: Annotated[User, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> TasteBankRebuildResponse:
    """Trigger a full taste-bank rebuild from the user's reading history.

    Available only in test environments.

    Args:
        user_id: Target user ID (must match authenticated user).
        current_user: Authenticated user from the access token.
        db: Async database session.

    Returns:
        Summary of the rebuild result.
    """
    _require_test_environment()

    if current_user.id != user_id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="You can only rebuild your own taste bank",
        )

    signals = await rebuild_user_taste_bank(db, user_id)

    return TasteBankRebuildResponse(
        signals_rebuilt=len(signals),
        signals_count=len(signals),
    )


@router.post(
    "/signals/{signal_id}/verdict",
    response_model=TasteBankSignalResponse,
)
async def update_signal_verdict(
    signal_id: int,
    verdict_update: TasteSignalVerdictUpdate,
    current_user: Annotated[User, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> TasteBankSignalResponse:
    """Apply or update an explicit user verdict on a taste signal.

    Explicit verdicts are authoritative: later inference recalculations never
    overwrite them.

    Args:
        signal_id: ID of the taste signal to update.
        verdict_update: Request body with verdict type.
        current_user: Authenticated user from the access token.
        db: Async database session.

    Returns:
        Updated taste signal.
    """
    result = await db.execute(select(TasteSignal).where(TasteSignal.id == signal_id))
    signal = result.scalar_one_or_none()
    if signal is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Taste signal {signal_id} not found",
        )

    if signal.user_id != current_user.id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="You can only update your own taste signals",
        )

    signal.user_verdict = verdict_update.verdict
    signal.verdict_at = datetime.now(UTC)
    # A user verdict is authoritative evidence; floor confidence accordingly.
    signal.confidence = max(signal.confidence or 0.0, 0.8)

    await db.commit()
    await db.refresh(signal)

    return _signal_to_response(signal)
