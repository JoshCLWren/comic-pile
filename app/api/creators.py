"""Bounded personal creator summary API (issue #2028).

Exposes the personal creator analytics summary for the Roll experience: one
bounded batch request answers every creator on an issue card without per-
creator request fan-out. All statistics are derived from the authenticated
reader's own issues and the creator credits confirmed via ComicVine identity
metadata (issue #2036); requesting a key with no library evidence yields an
empty row so no cross-user data is ever revealed.
"""

from __future__ import annotations

import re
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth import get_current_user
from app.database import get_db
from app.models.user import User
from app.schemas.creator_summary import (
    MAX_CREATOR_KEYS,
    CreatorSummaryResponse,
)
from app.services.creator_summary import summarize_creators

router = APIRouter(prefix="/creators", tags=["creators"])

_CANONICAL_CREATOR_KEY_RE = re.compile(r"^creator:\d+$")


def _parse_creator_keys(raw_keys: str) -> list[str]:
    """Parse and validate the comma-separated canonical creator keys.

    Args:
        raw_keys: Raw ``keys`` query value.

    Returns:
        Deduplicated canonical creator keys preserving request order.

    Raises:
        HTTPException: 422 when the keys are malformed or exceed the bound.
    """
    keys: list[str] = []
    seen: set[str] = set()
    for part in raw_keys.split(","):
        candidate = part.strip()
        if not candidate:
            continue
        if candidate in seen:
            continue
        if not _CANONICAL_CREATOR_KEY_RE.fullmatch(candidate):
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail=f"Invalid creator key '{candidate}' (expected 'creator:<id>')",
            )
        seen.add(candidate)
        keys.append(candidate)
    if not keys:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="At least one creator key is required",
        )
    if len(keys) > MAX_CREATOR_KEYS:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=f"Too many creator keys; the bound is {MAX_CREATOR_KEYS}",
        )
    return keys


@router.get(
    "/summaries",
    response_model=CreatorSummaryResponse,
    summary="Return personal creator reading summaries.",
    description=(
        "One bounded batch request answers every creator on a Roll issue card "
        "without per-creator request fan-out. Statistics are computed from the "
        "authenticated reader's own issues and confirmed ComicVine creator "
        "credits. Keys with no library evidence return an empty row."
    ),
)
async def creator_summaries(
    current_user: Annotated[User, Depends(get_current_user)],
    db: AsyncSession = Depends(get_db),
    keys: Annotated[
        str,
        Query(
            description=(
                "Comma-separated canonical creator keys (for example "
                f"'creator:4064,creator:5327'), bounded to {MAX_CREATOR_KEYS}."
            ),
        ),
    ],
) -> CreatorSummaryResponse:
    """Return personal reading summaries for the requested creators.

    Args:
        current_user: The authenticated reader.
        db: Async database session.
        keys: Comma-separated canonical creator keys to summarize.

    Returns:
        Per-key summaries plus library-wide coverage.
    """
    creator_keys = _parse_creator_keys(keys)
    return await summarize_creators(
        db, user_id=current_user.id, keys=creator_keys
    )