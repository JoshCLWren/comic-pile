"""Rate API endpoint."""

from typing import Annotated

from fastapi import APIRouter, Depends, Request

from sqlalchemy.ext.asyncio import AsyncSession

from app.auth import get_current_user
from app.database import get_db
from app.middleware import limiter
from app.models.user import User
from app.schemas import RateRequest
from app.schemas.roll_v2 import RateResponse
from app.services.rate_service import rate_thread

router = APIRouter()


@router.post("/", response_model=RateResponse)
@limiter.limit("60/minute")
async def post_rate(
    request: Request,
    rate_data: RateRequest,
    current_user: Annotated[User, Depends(get_current_user)],
    db: AsyncSession = Depends(get_db),
) -> RateResponse:
    """Delegate rating orchestration to the rate service."""
    return await rate_thread(rate_data=rate_data, current_user=current_user, db=db)
