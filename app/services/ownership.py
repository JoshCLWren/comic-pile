"""Ownership-scoped data access helpers."""

from fastapi import HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import Issue, Session as SessionModel, Thread


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
