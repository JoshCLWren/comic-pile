"""Taste Bank discovery and verdict API — Phase 7 (no ranking)."""

from __future__ import annotations

from datetime import UTC, datetime

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from typing import Annotated

from app.auth import get_current_user
from app.database import get_db
from app.models.taste_signal import TasteSignal
from app.models.user import User
from app.schemas.taste_bank import TasteDiscoveryResponse, TasteSignalResponse, TasteVerdictRequest
from app.taste_bank import is_prompt_eligible, rank_prompt_candidates

router = APIRouter(tags=["taste-bank"])

VALID_VERDICTS = {"confirmed", "sometimes", "rejected"}


def _evidence_summary(signal: TasteSignal) -> str:
    """Human-readable concise evidence summary without exposing raw confidence math."""
    parts = [f"{signal.evidence_count} issues"]
    if signal.distinct_thread_count > 1:
        parts.append(f"across {signal.distinct_thread_count} threads")
    if signal.role:
        parts.append(f"as {signal.role}")
    return " · ".join(parts)


@router.get("/signals", response_model=list[TasteSignalResponse])
async def list_taste_signals(
    current_user: Annotated[User, Depends(get_current_user)],
    db: AsyncSession = Depends(get_db),
) -> list[TasteSignalResponse]:
    """List all taste signals for the current user."""
    result = await db.execute(select(TasteSignal).where(TasteSignal.user_id == current_user.id).order_by(TasteSignal.confidence.desc()))
    signals = result.scalars().all()
    return [TasteSignalResponse.model_validate(s) for s in signals]


@router.get("/discoveries", response_model=list[TasteDiscoveryResponse])
async def list_discoveries(
    current_user: Annotated[User, Depends(get_current_user)],
    db: AsyncSession = Depends(get_db),
) -> list[TasteDiscoveryResponse]:
    """Return prompt-eligible discoveries respecting thresholds, cooldown, and rejection."""
    result = await db.execute(select(TasteSignal).where(TasteSignal.user_id == current_user.id))
    signals = result.scalars().all()
    now = datetime.now(UTC)
    eligible: list[dict[str, object]] = []
    signal_by_id: dict[int, TasteSignal] = {}
    for s in signals:
        if is_prompt_eligible(
            evidence_count=s.evidence_count,
            distinct_issue_count=s.distinct_issue_count,
            confidence=s.confidence,
            verdict=s.verdict,
            last_prompted_at=s.last_prompted_at,
            now=now,
        ):
            payload: dict[str, object] = {
                "id": s.id,
                "confidence": s.confidence,
                "evidence_count": s.evidence_count,
                "feature_type": s.feature_type,
            }
            eligible.append(payload)
            signal_by_id[s.id] = s

    ranked = rank_prompt_candidates(eligible)
    # Diversity: cap to one per feature_type for prompt variety
    seen_types: set[str] = set()
    out: list[TasteDiscoveryResponse] = []
    for cand in ranked:
        sid = int(cand["id"])  # type: ignore[arg-type]
        sig = signal_by_id[sid]
        ft = sig.feature_type
        if ft in seen_types:
            continue
        seen_types.add(ft)
        out.append(
            TasteDiscoveryResponse(
                signal=TasteSignalResponse.model_validate(sig),
                evidence_summary=_evidence_summary(sig),
            )
        )
    # Hard cap to avoid overwhelming UI
    return out[:3]


@router.post("/signals/{signal_id}/verdict", response_model=TasteSignalResponse)
async def update_verdict(
    signal_id: int,
    payload: TasteVerdictRequest,
    current_user: Annotated[User, Depends(get_current_user)],
    db: AsyncSession = Depends(get_db),
) -> TasteSignalResponse:
    """Confirm / qualify / reject a discovery. Explicit verdict survives later recomputation."""
    verdict = payload.verdict.strip().lower()
    if verdict not in VALID_VERDICTS:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail="Verdict must be confirmed, sometimes, or rejected")
    # Map "sometimes" canonical; keep as stored.
    result = await db.execute(select(TasteSignal).where(TasteSignal.id == signal_id))
    signal = result.scalar_one_or_none()
    if not signal or signal.user_id != current_user.id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=f"Taste signal {signal_id} not found")

    # Idempotent: repeated same verdict is ok
    signal.verdict = verdict
    signal.last_prompted_at = datetime.now(UTC)
    # updated_at handled by SQLAlchemy onupdate; set explicitly for test determinism
    signal.updated_at = datetime.now(UTC)  # type: ignore[attr-defined]

    await db.commit()
    await db.refresh(signal)
    return TasteSignalResponse.model_validate(signal)
