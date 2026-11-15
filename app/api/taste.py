"""Taste Bank discovery card API (issue #1750).

Surfaces prompt-eligible inferred taste signals for the occasional
"ComicPile noticed something" card on Roll and records dismissals. Explicit
verdicts intentionally have no endpoint here: they belong to the canonical
Taste Bank verdict API (issue #1749). Discovery never blocks rolling and
rating.
"""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth import get_current_user
from app.database import get_db
from app.models.user import User
from app.schemas.taste_discovery import TasteDiscoveryListResponse
from app.services.taste_bank import (
    MAX_ACTIVE_DISCOVERIES,
    dismiss_discovery,
    list_discoveries,
)

router = APIRouter(prefix="/taste", tags=["taste"])


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

    Surfacing counts as prompting: returned signals record ``last_prompted_at``
    so the canonical cooldown suppresses immediate re-prompting. Signals with
    any explicit verdict are never included.

    Args:
        current_user: The authenticated reader.
        db: Async database session.
        limit: Bounded maximum number of discoveries to return.

    Returns:
        Ranked eligible discoveries with concise evidence context.
    """
    return await list_discoveries(db, user_id=current_user.id, limit=limit)


@router.post("/discoveries/{signal_id}/dismiss")
async def dismiss_taste_discovery(
    signal_id: int,
    current_user: Annotated[User, Depends(get_current_user)],
    db: AsyncSession = Depends(get_db),
) -> dict[str, bool]:
    """Dismiss a discovery card without giving a verdict.

    Dismissal only starts a temporary suppression window; it never sets a
    verdict, so it can never count as confirmation.

    Args:
        signal_id: Target taste signal id.
        current_user: The authenticated reader.
        db: Async database session.

    Returns:
        A small acknowledgement payload.

    Raises:
        HTTPException: 404 when the signal is missing or not owned by the user.
    """
    signal = await dismiss_discovery(db, signal_id=signal_id, user_id=current_user.id)
    if signal is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Taste discovery {signal_id} not found",
        )
    return {"dismissed": True}
