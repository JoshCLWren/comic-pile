"""Taste Bank API endpoints.

Provides authenticated access to a user's inferred taste signals and
endpoints to trigger taste-bank rebuilds.

State changes are restricted to test environments for rebuild endpoints.
"""

from __future__ import annotations

import os
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth import get_current_user
from app.database import get_db
from app.models.taste_bank import TasteEvidence, TasteSignal
from app.models.user import User
from app.schemas.taste_bank import (
    TasteBankRebuildResponse,
    TasteBankSignalResponse,
    TasteBankSummaryResponse,
    TasteSignalVerdictUpdate,
)
from app.services.taste_bank import rebuild_user_taste_bank

router = APIRouter()


def _require_test_environment() -> None:
    """Reject test-only endpoints outside the E2E environment."""
    if os.getenv("TEST_ENVIRONMENT") != "true":
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="This endpoint is only available in test environment",
        )


@router.get(
    "/user/{user_id}",
    response_model=TasteBankSummaryResponse,
    tags=["taste-bank"],
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

    high_confidence = sum(1 for s in signals if s.confidence >= 0.7)
    explicit_verdict = sum(1 for s in signals if s.user_verdict is not None)

    response_signals = [
        TasteBankSignalResponse(
            id=s.id,
            user_id=s.user_id,
            signal_type=s.signal_type,  # type: ignore[arg-type]
            stable_key=s.stable_key,
            display_name=s.display_name,
            inferred_affinity=s.inferred_affinity,
            evidence_count=s.evidence_count,
            distinct_threads_count=s.distinct_threads_count,
            distinct_runs_count=s.distinct_runs_count,
            confidence=s.confidence,
            user_verdict=s.user_verdict,  # type: ignore[arg-type]
            last_observed_at=s.last_observed_at.isoformat() if s.last_observed_at else None,
            prompt_suppressed=bool(s.prompt_suppressed),
        )
        for s in signals
    ]

    return TasteBankSummaryResponse(
        signals=response_signals,
        total_signals=len(response_signals),
        high_confidence_count=high_confidence,
        explicit_verdict_count=explicit_verdict,
    )


@router.post(
    "/user/{user_id}/rebuild",
    response_model=TasteBankRebuildResponse,
    tags=["taste-bank"],
)
async def rebuild_user_taste_bank_endpoint(
    user_id: int,
    current_user: Annotated[User, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> TasteBankRebuildResponse:
    """Trigger a full taste-bank rebuild from the user's reading history.

    Available only in test and development environments.

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
    tags=["taste-bank"],
)
async def update_signal_verdict(
    signal_id: int,
    verdict_update: TasteSignalVerdictUpdate,
    current_user: Annotated[User, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> TasteBankSignalResponse:
    """Apply or update an explicit user verdict on a taste signal.

    Args:
        signal_id: ID of the taste signal to update.
        verdict_update: Request body with verdict type.
        current_user: Authenticated user from the access token.
        db: Async database session.

    Returns:
        Updated taste signal.
    """
    result = await db.execute(
        select(TasteSignal).where(TasteSignal.id == signal_id)
    )
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

    if verdict_update.verdict == "suppress":
        signal.prompt_suppressed = 1
    else:
        signal.user_verdict = verdict_update.verdict
        signal.confidence = max(signal.confidence, 0.8)

    await db.commit()
    await db.refresh(signal)

    return TasteBankSignalResponse(
        id=signal.id,
        user_id=signal.user_id,
        signal_type=signal.signal_type,  # type: ignore[arg-type]
        stable_key=signal.stable_key,
        display_name=signal.display_name,
        inferred_affinity=signal.inferred_affinity,
        evidence_count=signal.evidence_count,
        distinct_threads_count=signal.distinct_threads_count,
        distinct_runs_count=signal.distinct_runs_count,
        confidence=signal.confidence,
        user_verdict=signal.user_verdict,  # type: ignore[arg-type]
        last_observed_at=signal.last_observed_at.isoformat() if signal.last_observed_at else None,
        prompt_suppressed=bool(signal.prompt_suppressed),
    )