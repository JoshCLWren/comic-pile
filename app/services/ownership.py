"""Ownership-scoped data access helpers."""

from fastapi import HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.models import Collection, Issue, Review, Session as SessionModel, Thread


async def get_owned_thread_or_404(
    db: AsyncSession,
    user_id: int,
    thread_id: int,
    *,
    for_update: bool = False,
) -> Thread:
    """Fetch a thread by ID only if it belongs to the user."""
    query = select(Thread).where(Thread.id == thread_id, Thread.user_id == user_id)
    if for_update:
        query = query.with_for_update()
    result = await db.execute(query)
    thread = result.scalar_one_or_none()
    if thread is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Thread {thread_id} not found",
        )
    return thread


async def get_owned_collection_or_404(
    db: AsyncSession,
    user_id: int,
    collection_id: int,
) -> Collection:
    """Fetch a collection by ID only if it belongs to the user."""
    result = await db.execute(
        select(Collection).where(
            Collection.id == collection_id,
            Collection.user_id == user_id,
        )
    )
    collection = result.scalar_one_or_none()
    if collection is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Collection {collection_id} not found",
        )
    return collection


async def get_owned_issue_or_404(db: AsyncSession, user_id: int, issue_id: int) -> Issue:
    """Fetch an issue by ID only if its thread belongs to the user."""
    result = await db.execute(
        select(Issue)
        .join(Thread, Thread.id == Issue.thread_id)
        .where(Issue.id == issue_id, Thread.user_id == user_id)
    )
    issue = result.scalar_one_or_none()
    if issue is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Issue {issue_id} not found",
        )
    return issue


async def get_owned_review_or_404(
    db: AsyncSession,
    user_id: int,
    review_id: int,
    *,
    include_relations: bool = False,
) -> Review:
    """Fetch a review by ID only if it belongs to the user."""
    query = select(Review).where(Review.id == review_id, Review.user_id == user_id)
    if include_relations:
        query = query.options(selectinload(Review.thread), selectinload(Review.issue))
    result = await db.execute(query)
    review = result.scalar_one_or_none()
    if review is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Review {review_id} not found",
        )
    return review


async def get_owned_session_or_404(db: AsyncSession, user_id: int, session_id: int) -> SessionModel:
    """Fetch a session by ID only if it belongs to the user."""
    result = await db.execute(
        select(SessionModel).where(
            SessionModel.id == session_id,
            SessionModel.user_id == user_id,
        )
    )
    session = result.scalar_one_or_none()
    if session is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Session not found",
        )
    return session
