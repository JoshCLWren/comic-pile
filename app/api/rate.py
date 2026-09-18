"""Rate API endpoint."""

from datetime import UTC, datetime
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Request, status

from sqlalchemy.ext.asyncio import AsyncSession

from app.auth import get_current_user
from app.database import get_db
from app.middleware import limiter
from app.models import Session as SessionModel
from app.schemas import RateRequest, ThreadResponse
from app.services.rate_service import rate_thread

router = APIRouter()


@router.post("/", response_model=ThreadResponse)
@limiter.limit("60/minute")
async def rate_thread(
    request: Request,
    rate_data: RateRequest,
    current_user: Annotated[User, Depends(get_current_user)],
    db: AsyncSession = Depends(get_db),
) -> ThreadResponse:
    """Delegate rating orchestration to the rate service."""
    return await rate_thread(rate_data=rate_data, current_user=current_user, db=db)