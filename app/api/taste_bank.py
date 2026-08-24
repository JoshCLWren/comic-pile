"""Taste Bank discovery and verdict API — Phase 7 (no ranking use)."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth import get_current_user
from app.database import get_db
from app.models.taste_signal import TasteSignal as TasteSignalModel
from app.models.user import User
from app.schemas.taste import SignalType, TasteSignal as TasteSignalSchema, Verdict
from app.schemas.taste_bank import (
    TasteDiscoveryResponse,
    TasteSignalResponse,
    TasteVerdictRequest,
)
from app.services.prompt_eligibility import evaluate_prompt_eligibility

router = APIRouter(tags=["taste-bank"])

VALID_VERDICTS = {"confirmed", "sometimes", "rejected"}


def _is_creator_role(signal: TasteSignalModel) -> bool:
    """Heuristic: a creator signal is role-specific when its key carries a role segment."""
    return signal.signal_type == SignalType.CREATOR.value and signal.external_key.count(":") >= 2


def _orm_to_response(signal: TasteSignalModel) -> TasteSignalResponse:
    """Map an ORM taste signal to its API response model."""
    return TasteSignalResponse(
        id=signal.id,
        user_id=signal.user_id,
        signal_type=signal.signal_type,
        external_key=signal.external_key,
        display_name=signal.display_name,
        affinity_estimate=signal.affinity_estimate,
        evidence_count=signal.evidence_count,
        distinct_thread_count=signal.distinct_thread_count,
        confidence=signal.confidence,
        user_verdict=signal.user_verdict,
        verdict_at=signal.verdict_at,
        first_observed_at=signal.first_observed_at,
        last_observed_at=signal.last_observed_at,
        last_prompted_at=signal.last_prompted_at,
        prompt_suppressed_until=signal.prompt_suppressed_until,
        created_at=signal.created_at,
        updated_at=signal.updated_at,
    )


def _orm_to_engine_signal(signal: TasteSignalModel) -> TasteSignalSchema:
    """Map an ORM taste signal to the prompt-eligibility engine schema."""
    confidence = 0.0 if signal.confidence is None else max(0.0, min(1.0, signal.confidence))
    verdict = Verdict(signal.user_verdict) if signal.user_verdict else None
    return TasteSignalSchema(
        user_id=signal.user_id,
        signal_type=SignalType(signal.signal_type),
        stable_key=signal.external_key,
        display_name=signal.display_name,
        affinity=signal.affinity_estimate or 0.0,
        confidence=confidence,
        evidence_count=signal.evidence_count,
        evidence_diversity=signal.distinct_thread_count,
        verdict=verdict,
        last_prompted_at=signal.last_prompted_at,
        last_rejected_at=signal.verdict_at if signal.user_verdict == Verdict.REJECTED.value else None,
        is_creator_role=_is_creator_role(signal),
    )


def _evidence_summary(signal: TasteSignalModel) -> str:
    """Human-readable concise evidence summary without exposing raw confidence math."""
    parts = [f"{signal.evidence_count} issues"]
    if signal.distinct_thread_count > 1:
        parts.append(f"across {signal.distinct_thread_count} threads")
    return " · ".join(parts)


@router.get("/signals", response_model=list[TasteSignalResponse])
async def list_taste_signals(
    current_user: Annotated[User, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> list[TasteSignalResponse]:
    """List all taste signals for the current user."""
    result = await db.execute(
        select(TasteSignalModel)
        .where(TasteSignalModel.user_id == current_user.id)
        .order_by(TasteSignalModel.confidence.desc())
    )
    return [_orm_to_response(s) for s in result.scalars().all()]


@router.get("/discoveries", response_model=list[TasteDiscoveryResponse])
async def list_discoveries(
    current_user: Annotated[User, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> list[TasteDiscoveryResponse]:
    """Return prompt-eligible discoveries respecting thresholds, cooldown, and rejection."""
    result = await db.execute(
        select(TasteSignalModel).where(
            TasteSignalModel.user_id == current_user.id,
            TasteSignalModel.user_verdict.is_(None),
        )
    )
    signals = result.scalars().all()
    if not signals:
        return []

    orm_by_key = {(s.signal_type, s.external_key): s for s in signals}
    engine_signals = [_orm_to_engine_signal(s) for s in signals]
    eligibility = evaluate_prompt_eligibility(engine_signals)

    out: list[TasteDiscoveryResponse] = []
    for candidate in eligibility.candidates:
        orm = orm_by_key[(candidate.signal.signal_type.value, candidate.signal.stable_key)]
        out.append(
            TasteDiscoveryResponse(
                signal=_orm_to_response(orm),
                evidence_summary=_evidence_summary(orm),
            )
        )
    return out


@router.post("/signals/{signal_id}/verdict", response_model=TasteSignalResponse)
async def update_verdict(
    signal_id: int,
    payload: TasteVerdictRequest,
    current_user: Annotated[User, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> TasteSignalResponse:
    """Confirm / qualify / reject a discovery. Explicit verdict survives later recomputation."""
    verdict = payload.verdict.strip().lower()
    if verdict not in VALID_VERDICTS:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="Verdict must be confirmed, sometimes, or rejected",
        )

    result = await db.execute(
        select(TasteSignalModel).where(TasteSignalModel.id == signal_id)
    )
    signal = result.scalar_one_or_none()
    if not signal or signal.user_id != current_user.id:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Taste signal {signal_id} not found",
        )

    now = datetime.now(UTC)
    signal.user_verdict = verdict
    signal.verdict_at = now
    signal.last_prompted_at = now

    await db.commit()
    await db.refresh(signal)
    return _orm_to_response(signal)
