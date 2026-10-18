"""Query construction for per-user GitHub issue submission rate limiting.

All SQLAlchemy access for the ``GithubIssueSubmissionLimit`` model family lives
here. Functions return ORM models or plain values and never commit; callers
(services) own the transaction boundary.
"""

from datetime import datetime

from sqlalchemy import or_, select, update
from sqlalchemy.dialects.postgresql import insert as postgresql_insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.github_issue_submission_limit import GithubIssueSubmissionLimit


async def claim_submission_slot(
    db: AsyncSession,
    *,
    user_id: int,
    window_start: datetime,
) -> bool:
    """Atomically claim a user's rolling-window submission slot when it is free.

    The check and the claim are a single ``INSERT ... ON CONFLICT DO UPDATE ...
    WHERE`` statement. On a conflict PostgreSQL locks the existing row, so a
    second concurrent caller blocks and then re-evaluates the window against
    the winner's committed state. Two callers can therefore never both claim
    the slot, and the slot is not committed until the caller records success.

    Args:
        db: SQLAlchemy async session.
        user_id: ComicPile user identity that owns the allowance.
        window_start: Earliest ``last_submitted_at`` that still blocks a claim
            (typically ``now - window``).

    Returns:
        True when the caller now owns the slot for its transaction; False when
        a committed successful submission still falls inside the window.
    """
    statement = (
        postgresql_insert(GithubIssueSubmissionLimit)
        .values(user_id=user_id, last_submitted_at=None)
        .on_conflict_do_update(
            index_elements=[GithubIssueSubmissionLimit.user_id],
            set_={"last_submitted_at": GithubIssueSubmissionLimit.last_submitted_at},
            where=or_(
                GithubIssueSubmissionLimit.last_submitted_at.is_(None),
                GithubIssueSubmissionLimit.last_submitted_at <= window_start,
            ),
        )
        .returning(GithubIssueSubmissionLimit.user_id)
    )
    result = await db.execute(statement)
    return result.scalar_one_or_none() is not None


async def record_successful_submission(
    db: AsyncSession,
    *,
    user_id: int,
    submitted_at: datetime,
) -> None:
    """Mark the user's slot consumed after GitHub confirms issue creation.

    Args:
        db: SQLAlchemy async session.
        user_id: ComicPile user identity that owns the allowance.
        submitted_at: Confirmed creation timestamp recorded as the window start.
    """
    await db.execute(
        update(GithubIssueSubmissionLimit)
        .where(GithubIssueSubmissionLimit.user_id == user_id)
        .values(last_submitted_at=submitted_at)
    )


async def get_submission_limit(
    db: AsyncSession,
    *,
    user_id: int,
) -> GithubIssueSubmissionLimit | None:
    """Return the user's limit row, or None when they have never submitted.

    Args:
        db: SQLAlchemy async session.
        user_id: ComicPile user identity that owns the allowance.

    Returns:
        The user's ``GithubIssueSubmissionLimit`` row, if one exists.
    """
    result = await db.execute(
        select(GithubIssueSubmissionLimit).where(
            GithubIssueSubmissionLimit.user_id == user_id
        )
    )
    return result.scalar_one_or_none()
