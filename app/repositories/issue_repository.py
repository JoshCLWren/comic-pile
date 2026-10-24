"""Issue query construction and persistence.

All SQLAlchemy access for the ``Issue`` model family lives here. Functions
return ORM models, plain rows/tuples, or counts; callers (services) own
transaction boundaries.
"""

from sqlalchemy import case, delete, func, select, text, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import Issue, Thread


async def active_frontier_rows(
    db: AsyncSession, user_id: int
) -> list[tuple[int, int | None, int | None, int | None, str | None]]:
    """Load scalar frontier inputs, including empty active threads, without flushing.

    Args:
        db: Database session, whose pending changes must not be persisted.
        user_id: Owner of every returned thread and issue.

    Returns:
        Thread ID, stored pointer, issue ID, position and status rows, ordered
        by thread, position and stable issue ID. Position gaps are preserved.
    """
    with db.no_autoflush:
        result = await db.execute(
            select(
                Thread.id, Thread.next_unread_issue_id,
                Issue.id, Issue.position, Issue.status,
            )
            .outerjoin(Issue, Issue.thread_id == Thread.id)
            .where(Thread.user_id == user_id, Thread.status == "active")
            .order_by(Thread.id, Issue.position, Issue.id)
        )
    return [(row[0], row[1], row[2], row[3], row[4]) for row in result.all()]


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


async def thread_ids_for_issues(
    db: AsyncSession, *, issue_ids: list[int], user_id: int
) -> dict[int, int]:
    """Resolve thread IDs for several owned issues in one round trip.

    Bulk variant of :func:`resolve_owned_thread_id` for callers that inspect
    many issues at once (the bulk-unassign inheritance report in issue
    #3557). The same privacy boundary applies: an issue maps to its thread
    only when the thread belongs to ``user_id``.

    Args:
        db: Database session.
        issue_ids: Canonical Issue ids to resolve. Duplicates are ignored.
        user_id: Owner that must own the parent threads.

    Returns:
        Map from each requested issue ID to its owning thread ID. Issues that
        do not exist or whose thread is owned by someone else are omitted.
    """
    unique_ids = list(dict.fromkeys(issue_ids))
    if not unique_ids:
        return {}
    result = await db.execute(
        select(Issue.id, Issue.thread_id)
        .join(Thread, Thread.id == Issue.thread_id)
        .where(Issue.id.in_(unique_ids), Thread.user_id == user_id)
    )
    return {row[0]: row[1] for row in result.all()}


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


async def find_owned_issue_by_confirmed_identity(
    db: AsyncSession,
    user_id: int,
    *,
    provider: str,
    external_id: str,
) -> Issue | None:
    """Find the user-owned issue with a confirmed mapping to a provider identity.

    The confirmed mapping is the canonical ComicVine identity link established
    by the #2722 mapping path; this lookup lets adoption reuse the canonical
    Issue instead of creating a second physical copy.

    Args:
        db: Database session.
        user_id: Owner that must own the issue's thread.
        provider: External provider name (e.g. "comicvine").
        external_id: Provider-specific issue identifier.

    Returns:
        The owned issue with a confirmed mapping to that identity, or None.
    """
    from app.models.external_identity import ExternalIdentity, IssueExternalIdentityMapping

    result = await db.execute(
        select(Issue)
        .join(Thread, Thread.id == Issue.thread_id)
        .join(
            IssueExternalIdentityMapping,
            IssueExternalIdentityMapping.issue_id == Issue.id,
        )
        .join(
            ExternalIdentity,
            ExternalIdentity.id == IssueExternalIdentityMapping.external_identity_id,
        )
        .where(
            Thread.user_id == user_id,
            IssueExternalIdentityMapping.status == "confirmed",
            ExternalIdentity.provider == provider,
            ExternalIdentity.entity_type == "issue",
            ExternalIdentity.external_id == external_id,
        )
        .order_by(Issue.id)
        .limit(1)
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


async def issues_for_threads(
    db: AsyncSession, thread_ids: set[int]
) -> dict[int, list[Issue]]:
    """Load every issue for a set of threads in one query, grouped by thread.

    Args:
        db: Database session.
        thread_ids: Threads whose issues are loaded; an empty set returns an
            empty mapping.

    Returns:
        Mapping of thread ID to that thread's issues in canonical position
        order. Threads without issues are absent from the mapping.
    """
    if not thread_ids:
        return {}
    result = await db.execute(
        select(Issue)
        .where(Issue.thread_id.in_(thread_ids))
        .order_by(Issue.thread_id, Issue.position)
    )
    issues_by_thread: dict[int, list[Issue]] = {}
    for issue in result.scalars().all():
        issues_by_thread.setdefault(issue.thread_id, []).append(issue)
    return issues_by_thread


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


async def set_positions(
    db: AsyncSession, thread_id: int, positions_by_id: dict[int, int]
) -> None:
    """Assign absolute positions with one set-based ``UPDATE``.

    Used when reseating many rows at once (natural-order inserts). Callers must
    defer ``uq_issue_thread_position`` before invoking this when the new
    positions would temporarily collide.

    Args:
        db: Database session.
        thread_id: Thread that owns every issue in ``positions_by_id``.
        positions_by_id: Mapping of issue primary key to the target position.
    """
    if not positions_by_id:
        return

    await db.execute(
        update(Issue)
        .where(Issue.thread_id == thread_id, Issue.id.in_(tuple(positions_by_id)))
        .values(position=case(positions_by_id, value=Issue.id))
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


async def exists_read_at_or_after(
    db: AsyncSession, thread_id: int, position: int
) -> bool:
    """Check whether a read issue sits at or after a position.

    The rate flow derives ``issues_remaining`` from the next unread
    issue's position only while every issue at or after that position
    is unread. A manual reorder can seat a read issue above unread
    ones (issue #3104), so callers use this probe to decide whether
    the positional shortcut stays sound.

    Args:
        db: Database session.
        thread_id: Thread whose issues are checked.
        position: Inclusive lower position bound.

    Returns:
        True when at least one read issue has ``position >= position``.
    """
    result = await db.execute(
        select(Issue.id)
        .where(
            Issue.thread_id == thread_id,
            Issue.status == "read",
            Issue.position >= position,
        )
        .limit(1)
    )
    return result.scalar_one_or_none() is not None


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


async def issue_ids_for_thread(db: AsyncSession, thread_id: int) -> set[int]:
    """Collect the primary keys of every issue in a thread.

    Args:
        db: Database session.
        thread_id: Thread whose issue IDs are collected.

    Returns:
        The set of issue IDs belonging to the thread.
    """
    result = await db.execute(select(Issue.id).where(Issue.thread_id == thread_id))
    return set(result.scalars().all())


async def get_issues_by_thread(db: AsyncSession, thread_id: int) -> list[Issue]:
    """List every issue of a thread in canonical position order.

    Args:
        db: Database session.
        thread_id: Thread whose issues are listed.

    Returns:
        Issues ordered by position.
    """
    result = await db.execute(
        select(Issue).where(Issue.thread_id == thread_id).order_by(Issue.position, Issue.id)
    )
    return list(result.scalars().all())


async def get_issues_by_ids(db: AsyncSession, issue_ids: list[int]) -> list[Issue]:
    """Load issues by primary key.

    Args:
        db: Database session.
        issue_ids: Issue identifiers to load.

    Returns:
        The issues matching the given identifiers.
    """
    if not issue_ids:
        return []
    result = await db.execute(select(Issue).where(Issue.id.in_(issue_ids)))
    return list(result.scalars())


async def confirmed_comicvine_credits_for_thread(
    db: AsyncSession,
    thread_id: int,
) -> list[tuple[int, object, object]]:
    """Read stored ComicVine credit arrays for every confirmed issue mapping.

    One query covers the whole thread so caller surfaces (for example the
    thread issue list) never fan out into one provider-intelligence request
    per issue. Only the ``person_credits`` / ``creator_credits`` arrays are
    extracted from the stored provider metadata, so the payload stays small
    regardless of how large each issue's full metadata document is. When an
    issue has several confirmed ComicVine mappings, the highest-confidence
    mapping wins (ties broken by identity id), matching the single-issue
    intelligence read.

    Args:
        db: Database session.
        thread_id: Thread whose confirmed-mapping credit arrays are read.

    Returns:
        One ``(issue_id, person_credits, creator_credits)`` tuple per issue
        with a confirmed ComicVine mapping; either credits value may be None
        when the stored metadata lacks that key.
    """
    result = await db.execute(
        text(
            """
            SELECT DISTINCT ON (i.id)
                   i.id AS issue_id,
                   ei.metadata_json -> 'person_credits' AS person_credits,
                   ei.metadata_json -> 'creator_credits' AS creator_credits
            FROM issues i
            JOIN issue_external_identity_mappings iem ON iem.issue_id = i.id
            JOIN external_identities ei ON ei.id = iem.external_identity_id
            WHERE i.thread_id = :thread_id
              AND iem.status = 'confirmed'
              AND ei.provider = 'comicvine'
              AND ei.entity_type = 'issue'
            ORDER BY i.id, iem.confidence DESC NULLS LAST, ei.id
            """
        ),
        {"thread_id": thread_id},
    )
    return [
        (int(row["issue_id"]), row["person_credits"], row["creator_credits"])
        for row in result.mappings().all()
    ]


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
