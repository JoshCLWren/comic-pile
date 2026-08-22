"""Taste Bank discovery API (issue #1750).

Surfaces prompt-eligible inferred taste signals and records explicit reader
responses. Discovery never blocks or alters rolling and rating; it is a
read-only side panel plus two small mutation endpoints.
"""

from datetime import UTC, datetime
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth import get_current_user
from app.database import get_db
from app.models.taste_signal import TasteSignal
from app.models.user import User
from app.schemas.taste import (
    TasteDiscoveryListResponse,
    TasteSignalResponse,
    TasteVerdictRequest,
)
from app.services.taste_bank import (
    MAX_ACTIVE_DISCOVERIES,
    build_discovery_prompt,
    rank_prompt_eligible,
)

router = APIRouter(prefix="/taste", tags=["taste"])


async def _get_owned_signal_or_404(
    signal_id: int, user_id: int, db: AsyncSession
) -> TasteSignal:
    """Load one taste signal owned by the authenticated user.

    Args:
        signal_id: Primary key of the taste signal.
        user_id: Authenticated user id used for ownership scoping.
        db: Async database session.

    Returns:
        The owned signal.

    Raises:
        HTTPException: 404 when the signal does not exist for this user.
    """
    result = await db.execute(
        select(TasteSignal)
        .where(TasteSignal.id == signal_id)
        .where(TasteSignal.user_id == user_id)
    )
    signal = result.scalar_one_or_none()
    if signal is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Taste discovery {signal_id} not found",
        )
    return signal


@router.get("/discoveries", response_model=TasteDiscoveryListResponse)
async def list_taste_discoveries(
    current_user: Annotated[User, Depends(get_current_user)],
    db: AsyncSession = Depends(get_db),
    limit: Annotated[
        int,
        Query(ge=1, le=MAX_ACTIVE_DISCOVERIES, description="Maximum discoveries to return."),
    ] = MAX_ACTIVE_DISCOVERIES,
) -> TasteDiscoveryListResponse:
    """Return ranked prompt-eligible discoveries for the reader.

    Surfacing counts as prompting: returned signals record ``prompted_at`` so
    the centralized cooldown suppresses immediate re-prompting. Signals with
    any explicit verdict are never included.

    Args:
        current_user: The authenticated reader.
        db: Async database session.
        limit: Bounded maximum number of discoveries to return.

    Returns:
        Ranked eligible discoveries with concise evidence context.
    """
    now = datetime.now(UTC)
    result = await db.execute(
        select(TasteSignal).where(TasteSignal.user_id == current_user.id)
    )
    signals = result.scalars().all()

    eligible = rank_prompt_eligible(signals, now=now)[:limit]

    discovered: list[TasteDiscovery] = []
    prompted_ids: list[int] = []
    for signal in eligible:
        discovered.append(
            TasteDiscovery(
                id=signal.id,
                feature_type=signal.feature_type,
                creator_role=signal.creator_role,
                label=signal.label,
                prompt=build_discovery_prompt(signal),
                evidence_count=signal.evidence_count,
                distinct_threads=signal.distinct_threads,
            )
        )
        signal.prompted_at = now
        signal.prompt_count += 1
        prompted_ids.append(signal.id)

    if prompted_ids:
        await db.commit()

    return TasteDiscoveryListResponse(discoveries=discovered, generated_at=now)


@router.post("/discoveries/{signal_id}/verdict", response_model=TasteSignalResponse)
async def submit_taste_verdict(
    signal_id: int,
    payload: TasteVerdictRequest,
    current_user: Annotated[User, Depends(get_current_user)],
    db: AsyncSession = Depends(get_db),
) -> TasteSignalResponse:
    """Record an explicit confirm/sometimes/reject verdict on one discovery.

    Any explicit verdict permanently removes the signal from future prompts.
    Repeated identical submissions are idempotent.

    Args:
        signal_id: Target taste signal id.
        payload: Validated verdict.
        current_user: The authenticated reader.
        db: Async database session.

    Returns:
        The canonical updated signal state.

    Raises:
        HTTPException: 404 when the signal is missing or not owned by the user.
    """
    signal = await _get_owned_signal_or_404(signal_id, current_user.id, db)

    now = datetime.now(UTC)
    signal.verdict = payload.verdict
    signal.verdict_at = now
    # A definitive answer also ends any dismissal suppression bookkeeping.
    signal.dismissed_at = None

    # Extract scalars before commit to avoid MissingGreenlet re-reads.
    response = TasteSignalResponse.model_validate(signal)
    await db.commit()
    return response


@router.post("/discoveries/{signal_id}/dismiss", response_model=TasteSignalResponse)
async def dismiss_taste_discovery(
    signal_id: int,
    current_user: Annotated[User, Depends(get_current_user)],
    db: AsyncSession = Depends(get_db),
) -> TasteSignalResponse:
    """Dismiss a discovery card without giving a verdict.

    Dismissal only starts the temporary dismissal suppression window; it never
    sets a verdict, so it can never count as confirmation.

    Args:
        signal_id: Target taste signal id.
        current_user: The authenticated reader.
        db: Async database session.

    Returns:
        The canonical updated signal state.

    Raises:
        HTTPException: 404 when the signal is missing or not owned by the user.
    """
    signal = await _get_owned_signal_or_404(signal_id, current_user.id, db)

    now = datetime.now(UTC)
    signal.dismissed_at = now

    response = TasteSignalResponse.model_validate(signal)
    await db.commit()
    return response
