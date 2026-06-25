"""Review API endpoints."""

import base64
import json
from datetime import datetime
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.responses import JSONResponse
from sqlalchemy import and_, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.auth import get_current_user
from app.database import get_db
from app.models import Issue, Review
from app.models.user import User
from app.schemas.review import ReviewCreate, ReviewListResponse, ReviewResponse, ReviewUpdate
from app.services.ownership import get_owned_review_or_404, get_owned_thread_or_404

router = APIRouter(tags=["reviews"])


def _encode_page_token(created_at: datetime, review_id: int) -> str:
    """Encode created_at and id into a page token."""
    payload = json.dumps({"ts": created_at.isoformat(), "id": review_id})
    return base64.urlsafe_b64encode(payload.encode()).decode()


def _decode_page_token(token: str) -> tuple[datetime, int]:
    """Decode page token into (created_at, id). Raises ValueError on invalid token."""
    payload = json.loads(base64.urlsafe_b64decode(token.encode()))
    return datetime.fromisoformat(payload["ts"]), payload["id"]


async def _find_existing_review(
    db: AsyncSession, user_id: int, thread_id: int, issue_id: int | None
) -> Review | None:
    """Find existing review for user/thread/issue combination."""
    # Build the base query conditions
    conditions = [
        Review.user_id == user_id,
        Review.thread_id == thread_id,
    ]

    # Add issue_id condition - handle NULL values properly
    if issue_id is None:
        conditions.append(Review.issue_id.is_(None))
    else:
        conditions.append(Review.issue_id == issue_id)

    query = (
        select(Review)
        .where(and_(*conditions))
        .options(selectinload(Review.thread), selectinload(Review.issue))
    )
    result = await db.execute(query)
    return result.scalar_one_or_none()


async def _get_issue_id(db: AsyncSession, thread_id: int, issue_number: str | None) -> int | None:
    """Get issue ID from thread and issue number."""
    if not issue_number:
        return None

    result = await db.execute(
        select(Issue.id).where(
            and_(
                Issue.thread_id == thread_id,
                Issue.issue_number == issue_number,
            )
        )
    )
    return result.scalar_one_or_none()


async def _create_or_update_review_response(review: Review, db: AsyncSession) -> ReviewResponse:
    """Create ReviewResponse from Review with thread details.

    Note: This function expects the review to have thread and issue relationships
    already loaded via selectinload. Callers must ensure these are loaded.
    """
    return ReviewResponse(
        id=review.id,
        user_id=review.user_id,
        thread_id=review.thread_id,
        rating=review.rating,
        review_text=review.review_text,
        issue_id=review.issue_id,
        issue_number=review.issue.issue_number if review.issue else None,
        thread_title=review.thread.title,
        thread_format=review.thread.format,
        created_at=review.created_at,
        updated_at=review.updated_at,
    )


@router.post("/", response_model=ReviewResponse)
async def create_review(
    review_data: ReviewCreate,
    current_user: Annotated[User, Depends(get_current_user)],
    db: AsyncSession = Depends(get_db),
) -> JSONResponse:
    """Create a new review or update existing review.

    Users can have one review per thread/issue combination.

    Args:
        review_data: Review creation data
        current_user: The authenticated user
        db: Database session

    Returns:
        Created or updated review

    Raises:
        HTTPException: If thread not found or issue not found for thread
    """
    user_id = current_user.id
    thread_id = review_data.thread_id

    # Verify thread exists and belongs to user
    await get_owned_thread_or_404(db, user_id, thread_id)

    # Get issue ID if issue number provided
    issue_id = await _get_issue_id(db, thread_id, review_data.issue_number)
    if review_data.issue_number and issue_id is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Issue {review_data.issue_number} not found for thread {thread_id}",
        )

    # Check for existing review
    existing_review = await _find_existing_review(db, user_id, thread_id, issue_id)
    if existing_review:
        # Update existing review
        existing_review.rating = review_data.rating
        existing_review.review_text = review_data.review_text
        await db.commit()
        response_data = await _create_or_update_review_response(existing_review, db)
        return JSONResponse(
            content=response_data.model_dump(mode="json"),
            status_code=status.HTTP_200_OK,
        )

    # Create new review
    review = Review(
        user_id=user_id,
        thread_id=thread_id,
        issue_id=issue_id,
        rating=review_data.rating,
        review_text=review_data.review_text,
    )
    db.add(review)

    try:
        await db.commit()
        result = await db.execute(
            select(Review)
            .where(Review.id == review.id)
            .options(selectinload(Review.thread), selectinload(Review.issue))
        )
        refreshed_review = result.scalar_one()
        response_data = await _create_or_update_review_response(refreshed_review, db)
        return JSONResponse(
            content=response_data.model_dump(mode="json"),
            status_code=status.HTTP_201_CREATED,
        )
    except IntegrityError:
        # Handle race condition - another review was created with the same user_id/thread_id/issue_id
        await db.rollback()
        # Re-query to find the existing review created by the other request
        existing_review = await _find_existing_review(db, user_id, thread_id, issue_id)
        if existing_review:
            # Update it with the current rating/review_text
            existing_review.rating = review_data.rating
            existing_review.review_text = review_data.review_text
            await db.commit()
            response_data = await _create_or_update_review_response(existing_review, db)
            return JSONResponse(
                content=response_data.model_dump(mode="json"),
                status_code=status.HTTP_200_OK,
            )
        else:
            # This shouldn't happen, but handle it gracefully
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail="Failed to create or find review after race condition",
            ) from None


@router.get("/", response_model=ReviewListResponse)
async def list_reviews(
    current_user: Annotated[User, Depends(get_current_user)],
    db: AsyncSession = Depends(get_db),
    page_size: int = 20,
    page_token: str | None = None,
) -> ReviewListResponse:
    """List reviews for current user with pagination.

    Args:
        current_user: The authenticated user
        db: Database session
        page_size: Number of reviews per page
        page_token: Pagination token

    Returns:
        Paginated list of reviews
    """
    user_id = current_user.id

    # Build base query
    base_query = (
        select(Review)
        .where(Review.user_id == user_id)
        .options(selectinload(Review.thread), selectinload(Review.issue))
        .order_by(Review.created_at.desc())
    )

    # Apply pagination
    if page_token:
        # Decode page_token to get (created_at, id) cursor
        try:
            last_created_at, last_id = _decode_page_token(page_token)
            # Use keyset pagination on (created_at, id) for stable ordering
            base_query = base_query.where(
                (Review.created_at < last_created_at)
                | ((Review.created_at == last_created_at) & (Review.id < last_id))
            )
        except ValueError:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Invalid page_token",
            ) from None

    # Get page of reviews
    reviews_query = base_query.limit(page_size + 1)  # +1 to check if more exist
    result = await db.execute(reviews_query)
    reviews = result.scalars().all()
    reviews_list = list(reviews)

    # Build response
    review_responses = []
    for review in reviews_list[:page_size]:
        response = await _create_or_update_review_response(review, db)
        review_responses.append(response)

    # Determine if there are more pages
    next_page_token = None
    if len(reviews_list) > page_size:
        last_review = reviews_list[page_size - 1]
        next_page_token = _encode_page_token(last_review.created_at, last_review.id)

    return ReviewListResponse(reviews=review_responses, next_page_token=next_page_token)


@router.get("/{review_id}", response_model=ReviewResponse)
async def get_review(
    review_id: int,
    current_user: Annotated[User, Depends(get_current_user)],
    db: AsyncSession = Depends(get_db),
) -> ReviewResponse:
    """Get a specific review.

    Args:
        review_id: ID of the review to retrieve
        current_user: The authenticated user
        db: Database session

    Returns:
        Review details

    Raises:
        HTTPException: If review not found or not owned by user
    """
    review = await get_owned_review_or_404(
        db,
        current_user.id,
        review_id,
        include_relations=True,
    )

    return await _create_or_update_review_response(review, db)


@router.put("/{review_id}", response_model=ReviewResponse)
async def update_review(
    review_id: int,
    update_data: ReviewUpdate,
    current_user: Annotated[User, Depends(get_current_user)],
    db: AsyncSession = Depends(get_db),
) -> ReviewResponse:
    """Update an existing review.

    Args:
        review_id: ID of the review to update
        update_data: Update data
        current_user: The authenticated user
        db: Database session

    Returns:
        Updated review

    Raises:
        HTTPException: If review not found or not owned by user
    """
    review = await get_owned_review_or_404(
        db,
        current_user.id,
        review_id,
        include_relations=True,
    )

    # Update fields if provided
    data = update_data.model_dump(exclude_unset=True)
    for key, value in data.items():
        setattr(review, key, value)

    await db.commit()
    return await _create_or_update_review_response(review, db)


@router.delete("/{review_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_review(
    review_id: int,
    current_user: Annotated[User, Depends(get_current_user)],
    db: AsyncSession = Depends(get_db),
) -> None:
    """Delete a review.

    Args:
        review_id: ID of the review to delete
        current_user: The authenticated user
        db: Database session

    Raises:
        HTTPException: If review not found or not owned by user
    """
    review = await get_owned_review_or_404(db, current_user.id, review_id)

    await db.delete(review)
    await db.commit()
