"""Authenticated Taste Bank API for managing user signals.

Exposes endpoints to confirm, qualify, or reject Taste Bank discoveries for the authenticated user.
"""

from typing import Annotated

from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth import get_current_user
from app.database import get_db
from app.models import TasteBankSignal
from app.schemas import taste_bank
from app.models.user import User


router = APIRouter(prefix="/users/me/taste-bank", tags=["taste-bank"])


@router.get(
    "/signals",
    response_model=taste_bank.TasteBankSignalResponse,
    summary="Read the authenticated user's Taste Bank signal.",
    description=(
        "Return the authenticated user's persisted Taste Bank signal. "
        "When no signal exists yet, defaults to a neutral state."
    ),
)
async def get_user_taste_bank_signal(
    current_user: Annotated[User, Depends(get_current_user)],
    db: AsyncSession = Depends(get_db),
) -> taste_bank.TasteBankSignalResponse:
    """Read the authenticated user's Taste Bank signal."""
    result = await db.execute(
        select(TasteBankSignal).where(TasteBankSignal.user_id == current_user.id)
    )
    signal = result.scalar_one_or_none()
    
    if signal is None:
        # Return a default/neutral signal
        return taste_bank.TasteBankSignalResponse(
            signal_type="recommendation",
            verdict="confirmed",
            evidence=None,
            recorded_at="",
            user_id=current_user.id,
        )
    
    return taste_bank.TasteBankSignalResponse(
        signal_type=signal.signal_type,
        verdict=signal.verdict,
        evidence=signal.evidence,
        recorded_at=signal.recorded_at.isoformat(),
        user_id=current_user.id,
    )


@router.patch(
    "/signals",
    response_model=taste_bank.TasteBankSignalResponse,
    summary="Update the authenticated user's Taste Bank signal.",
    description=(
        "Update the authenticated user's Taste Bank signal. "
        "Only the specified signal_type is updated; other signals remain unchanged."
    ),
)
async def update_user_taste_bank_signal(
    payload: taste_bank.TasteBankSignalRequest,
    current_user: Annotated[User, Depends(get_current_user)],
    db: AsyncSession = Depends(get_db),
) -> taste_bank.TasteBankSignalResponse:
    """Update the authenticated user's Taste Bank signal."""
    # Check if signal already exists
    result = await db.execute(
        select(TasteBankSignal).where(
            TasteBankSignal.user_id == current_user.id,
            TasteBankSignal.signal_type == payload.signal_type
        )
    )
    signal = result.scalar_one_or_none()
    
    if signal is None:
        # Create new signal
        signal = TasteBankSignal(
            user_id=current_user.id,
            signal_type=payload.signal_type,
            verdict=payload.verdict,
            evidence=payload.evidence,
            recorded_at=datetime.now(UTC),
        )
        db.add(signal)
    else:
        # Update existing signal
        signal.verdict = payload.verdict
        signal.evidence = payload.evidence
        signal.updated_at = datetime.now(UTC)
    
    await db.commit()
    await db.refresh(signal)
    
    return taste_bank.TasteBankSignalResponse(
        signal_type=signal.signal_type,
        verdict=signal.verdict,
        evidence=signal.evidence,
        recorded_at=signal.recorded_at.isoformat(),
        user_id=current_user.id,
    )