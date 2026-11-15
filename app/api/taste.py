"""Taste Bank discovery card API (issue #1750).

Surfaces prompt-eligible inferred taste signals for the occasional
"ComicPile noticed something" card on Roll and records dismissals. Explicit
verdicts intentionally have no endpoint here: they belong to the canonical
Taste Bank verdict API (issue #1749). Discovery never blocks rolling and
rating.
"""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth import get_current_user
from app.database import get_db
from app.models.user import User
from app.schemas.taste_discovery import TasteDiscoveryListResponse
from app.services.taste_bank import (
    MAX_ACTIVE_DISCOVERIES,
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
