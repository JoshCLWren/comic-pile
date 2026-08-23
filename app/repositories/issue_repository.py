"""Issue query construction and persistence.

All SQLAlchemy access for the ``Issue`` model family lives here. Functions
return ORM models, plain rows/tuples, or counts; callers (services) own
transaction boundaries.
"""

from sqlalchemy import delete, func, select, text, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import Issue, Thread


async def get_issue(db: AsyncSession, issue_id: int) -> Issue | None:
    """Return an issue by primary key.

    Args:
        db: Database session.
        issue_id: Primary key of the issue.

    Returns:
        The issue, or None when it does not exist.
    """
    return await db.get(Issue, issue_id)


async def resolve_owned_thread_id(
    db: AsyncSession, issue_id: int, user_id: int
) -> int | None:
    """Resolve an issue's thread ID when the thread belongs to the user.

    Args:
        db: Database session.
        issue_id: Primary key of the issue.
        user_id: Owner that must own the parent thread.

    Returns:
        The owning thread ID, or None when the issue does not exist or its
        thread is owned by someone else.
    """
    result = await db.execute(
        select(Issue.thread_id)
        .join(Thread, Thread.id == Issue.thread_id)
        .where(Issue.id == issue_id, Thread.user_id == user_id)
    )
    return result.scalar_one_or_none()


async def find_owned(db: AsyncSession, user_id: int, issue_id: int) -> Issue | None:
    """Find an issue by ID scoped to the owner of its parent thread.

    Args:
        db: Database session.
        user_id: Owner that must own the parent thread.
        issue_id: Primary key of the issue.

    Returns:
        The owned issue, or None when absent or foreign.
    """
    result = await db.execute(
        select(Issue)
        .join(Thread, Thread.id == Issue.thread_id)
        .where(Issue.id == issue_id, Thread.user_id == user_id)
    )
    return result.scalar_one_or_none()


async def find_in_thread_by_number(
    db: AsyncSession, thread_id: int, issue_number: str
) -> Issue | None:
    """Find an issue of a thread by its displayed issue number.

    Args:
        db: Database session.
        thread_id: Thread that owns the issue.
        issue_number: Displayed issue number to match exactly.

    Returns:
        The matching issue, or None when absent.
    """
    result = await db.execute(
        select(Issue)
        .where(Issue.thread_id == thread_id)
        .where(Issue.issue_number == issue_number)
    )
    return result.scalar_one_or_none()


async def issues_ordered(db: AsyncSession, thread_id: int) -> list[Issue]:
    """List every issue of a thread in canonical position order.

    Args:
        db: Database session.
        thread_id: Thread whose issues are listed.

    Returns:
        Issues ordered by position.
    """
    result = await db.execute(
        select(Issue).where(Issue.thread_id == thread_id).order_by(Issue.position)
    )
    return list(result.scalars().all())


async def locked_issues(db: AsyncSession, thread_id: int) -> list[Issue]:
    """Lock and return every issue of a thread in canonical order.

    Rows are selected ``FOR UPDATE`` so concurrent reorders serialize.

    Args:
        db: Database session.
        thread_id: Thread whose issues are locked.

    Returns:
        Locked issues ordered by ``(position, id)``.
    """
    result = await db.execute(
        select(Issue)
        .where(Issue.thread_id == thread_id)
        .order_by(Issue.position, Issue.id)
        .with_for_update()
    )
    return list(result.scalars().all())


async def locked_issue_rows(db: AsyncSession, thread_id: int) -> list[tuple[int, str, int]]:
    """Lock a thread's issues and return compact identity rows.

    Args:
        db: Database session.
        thread_id: Thread whose issues are locked.

    Returns:
        ``(id, issue_number, position)`` rows ordered by position.
    """
    result = await db.execute(
        select(Issue.id, Issue.issue_number, Issue.position)
        .where(Issue.thread_id == thread_id)
        .with_for_update()
        .order_by(Issue.position)
    )
    return [(row[0], row[1], row[2]) for row in result.all()]


async def add_issue(db: AsyncSession, issue: Issue) -> None:
    """Stage a newly constructed issue on the session.

    Args:
        db: Database session.
        issue: Issue instance to add.
    """
    db.add(issue)


async def delete_issues_for_thread(db: AsyncSession, thread_id: int) -> None:
    """Delete every issue belonging to a thread.

    Args:
        db: Database session.
        thread_id: Thread whose issues should be removed.
    """
    await db.execute(delete(Issue).where(Issue.thread_id == thread_id))


async def delete_issue(db: AsyncSession, issue: Issue) -> None:
    """Delete one issue row via the session.

    Args:
        db: Database session.
        issue: Issue instance to delete.
    """
    await db.delete(issue)


async def shift_positions_after(
    db: AsyncSession, thread_id: int, *, after_position: int, delta: int
) -> None:
    """Move every issue later than a position by ``delta`` positions.

    Args:
        db: Database session.
        thread_id: Thread whose issues shift.
        after_position: Positions strictly greater than this value move.
        delta: Signed offset applied to each matching position.
    """
    await db.execute(
        update(Issue)
        .where(Issue.thread_id == thread_id, Issue.position > after_position)
        .values(position=Issue.position + delta)
    )


async def defer_position_unique_constraint(db: AsyncSession) -> None:
    """Defer the thread-position uniqueness constraint for this transaction.

    Required while shifting existing issues upward before inserting the new
    block into the freed position range.

    Args:
        db: Database session.
    """
    await db.execute(text("SET CONSTRAINTS uq_issue_thread_position DEFERRED"))


async def count_for_thread(
    db: AsyncSession, thread_id: int, status_filter: str | None = None
) -> int:
    """Count a thread's issues, optionally filtered by status.

    Args:
        db: Database session.
        thread_id: Thread whose issues are counted.
        status_filter: Optional exact issue status ("read"/"unread").

    Returns:
        Number of matching issues (0 when none).
    """
    query = select(func.count()).select_from(Issue).where(Issue.thread_id == thread_id)
    if status_filter:
        query = query.where(Issue.status == status_filter)
    result = await db.execute(query)
    return result.scalar() or 0


async def first_unread(db: AsyncSession, thread_id: int) -> Issue | None:
    """Return the earliest-position unread issue of a thread.

    Args:
        db: Database session.
        thread_id: Thread whose issues are searched.

    Returns:
        The first unread issue by position, or None when all are read.
    """
    result = await db.execute(
        select(Issue)
        .where(Issue.thread_id == thread_id, Issue.status == "unread")
        .order_by(Issue.position)
        .limit(1)
    )
    return result.scalar_one_or_none()


async def list_page(
    db: AsyncSession,
    thread_id: int,
    *,
    status_filter: str | None,
    cursor: tuple[int, int] | None,
    limit: int,
) -> list[Issue]:
    """Fetch one page of a thread's issues in canonical order.

    Args:
        db: Database session.
        thread_id: Thread whose issues are listed.
        status_filter: Optional exact issue status ("read"/"unread").
        cursor: Decoded ``(position, id)`` continuation cursor, or None for
            the first page.
        limit: Maximum number of issues to return.

    Returns:
        Issues ordered by position, at most ``limit`` rows.
    """
    query = select(Issue).where(Issue.thread_id == thread_id)

    if status_filter:
        query = query.where(Issue.status == status_filter)

    query = query.order_by(Issue.position)

    if cursor is not None:
        cursor_position, cursor_id = cursor
        query = query.where(
            (Issue.position > cursor_position)
            | ((Issue.position == cursor_position) & (Issue.id > cursor_id))
        )

    query = query.limit(limit)
    result = await db.execute(query)
    return list(result.scalars().all())


def is_thread_number_conflict(exc: IntegrityError) -> bool:
    """Report whether an integrity error came from issue thread/number uniqueness.

    Args:
        exc: Integrity error raised by the database driver.

    Returns:
        True when the violation identifies ``uq_issue_thread_number`` or an
        equivalent Postgres duplicate-key message over thread/number.
    """
    error_text = str(exc).lower()
    return "uq_issue_thread_number" in error_text or (
        "duplicate key value violates unique constraint" in error_text
        and "thread_id" in error_text
        and "issue_number" in error_text
    )
