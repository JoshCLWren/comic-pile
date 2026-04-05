"""Review API endpoints."""

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import and_, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload
from typing_extensions import TypedDict

from app.auth import get_current_user
from app.database import get_db
from app.models import Issue, Review, Thread
from app.models.user import User
from app.schemas.review import ReviewCreate, ReviewListResponse, ReviewResponse, ReviewUpdate

router = APIRouter(tags=["reviews"])


class PaginateParams(TypedDict):
    """Parameters for pagination."""

    page_size: int
    page_token: str | None


class PaginatedResponse(TypedDict):
    """Paginated response type."""

    reviews: list[ReviewResponse]
    next_page_token: str | None


async def _find_existing_review(
    db: AsyncSession, user_id: int, thread_id: int, issue_id: int | None
) -> Review | None:
    """Find existing review for user/thread/issue combination."""
    query = (
        select(Review)
        .where(
            and_(
                Review.user_id == user_id,
                Review.thread_id == thread_id,
                Review.issue_id == issue_id,
            )
        )
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
    """Create ReviewResponse from Review with thread details."""
    # Re-query the review with relationships loaded to ensure we have the data
    result = await db.execute(
        select(Review)
        .where(Review.id == review.id)
        .options(selectinload(Review.thread), selectinload(Review.issue))
    )
    refreshed_review = result.scalar_one()

    return ReviewResponse(
        id=refreshed_review.id,
        user_id=refreshed_review.user_id,
        thread_id=refreshed_review.thread_id,
        rating=refreshed_review.rating,
        review_text=refreshed_review.review_text,
        issue_id=refreshed_review.issue_id,
        issue_number=refreshed_review.issue.issue_number if refreshed_review.issue else None,
        thread_title=refreshed_review.thread.title,
        thread_format=refreshed_review.thread.format,
        created_at=refreshed_review.created_at,
        updated_at=refreshed_review.updated_at,
    )


@router.post("/", response_model=ReviewResponse, status_code=status.HTTP_201_CREATED)
async def create_review(
    review_data: ReviewCreate,
    current_user: Annotated[User, Depends(get_current_user)],
    db: AsyncSession = Depends(get_db),
) -> ReviewResponse:
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
    result = await db.execute(
        select(Thread).where(and_(Thread.id == thread_id, Thread.user_id == user_id))
    )
    thread = result.scalar_one_or_none()
    if not thread:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Thread {thread_id} not found or does not belong to user",
        )

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
        return await _create_or_update_review_response(existing_review, db)

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
        return await _create_or_update_review_response(review, db)
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
            return await _create_or_update_review_response(existing_review, db)
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
        # Parse page_token to get ID to start from
        try:
            last_id = int(page_token)
            base_query = base_query.where(Review.id < last_id)
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
        next_page_token = str(last_review.id)

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
    result = await db.execute(
        select(Review).where(and_(Review.id == review_id, Review.user_id == current_user.id))
    )
    review = result.scalar_one_or_none()
    if not review:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Review {review_id} not found or not owned by user",
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
    result = await db.execute(
        select(Review).where(and_(Review.id == review_id, Review.user_id == current_user.id))
    )
    review = result.scalar_one_or_none()
    if not review:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Review {review_id} not found or not owned by user",
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
    result = await db.execute(
        select(Review).where(and_(Review.id == review_id, Review.user_id == current_user.id))
    )
    review = result.scalar_one_or_none()
    if not review:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Review {review_id} not found or not owned by user",
        )

    await db.delete(review)
    await db.commit()


@router.get("/threads/{thread_id}/reviews", response_model=list[ReviewResponse])
async def get_thread_reviews(
    thread_id: int,
    current_user: Annotated[User, Depends(get_current_user)],
    db: AsyncSession = Depends(get_db),
) -> list[ReviewResponse]:
    """Get all reviews for a specific thread.

    Args:
        thread_id: ID of the thread
        current_user: The authenticated user
        db: Database session

    Returns:
        List of reviews for the thread

    Raises:
        HTTPException: If thread not found or not owned by user
    """
    # Verify thread exists and belongs to user
    thread_result = await db.execute(
        select(Thread).where(and_(Thread.id == thread_id, Thread.user_id == current_user.id))
    )
    thread = thread_result.scalar_one_or_none()
    if not thread:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Thread {thread_id} not found or does not belong to user",
        )

    # Get all reviews for the thread
    result = await db.execute(
        select(Review)
        .where(and_(Review.thread_id == thread_id, Review.user_id == current_user.id))
        .order_by(Review.created_at.desc())
    )
    reviews = result.scalars().all()

    # Convert to response objects
    review_responses = []
    for review in reviews:
        response = await _create_or_update_review_response(review, db)
        review_responses.append(response)

    return review_responses
