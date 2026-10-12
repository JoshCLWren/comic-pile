"""Set-based refresh of denormalized ``threads.is_blocked`` for every user.

Roll reads the stored flag, not the live evaluator. After a migration that
changes Roll/blocking semantics, this statement recomputes every flag from
canonical Dependencies so the denormalized column matches
``_get_blocked_thread_ids_uncached``. Historical ``cbl-order:%`` rows stay
inert. ContinuityRule and DependencyGroup ordering are not Roll authorities.

The Alembic revision ``c35120000001`` is a thin wrapper around
:func:`refresh_all_users_blocked_status` so the SQL can be unit-tested
without an Alembic context.
"""

from __future__ import annotations

import sqlalchemy as sa
from sqlalchemy.engine import Connection
from sqlalchemy.ext.asyncio import AsyncSession

# A thread is blocked when its current unread frontier has an unread
# prerequisite through a canonical Dependency edge. The predicate matches
# comic_pile.dependencies._get_blocked_thread_ids_uncached exactly.
REFRESH_ALL_USERS_BLOCKED_STATUS_SQL = """
WITH canonically_blocked AS (
    SELECT DISTINCT target_thread.id AS thread_id
    FROM threads AS target_thread
    JOIN issues AS next_unread_issue
        ON next_unread_issue.id = target_thread.next_unread_issue_id
    JOIN dependencies
        ON dependencies.target_issue_id = next_unread_issue.id
    JOIN issues AS source_issue
        ON dependencies.source_issue_id = source_issue.id
    JOIN threads AS source_thread
        ON source_issue.thread_id = source_thread.id
    WHERE source_thread.user_id = target_thread.user_id
      AND source_issue.status <> 'read'
      AND target_thread.next_unread_issue_id IS NOT NULL
      AND (
          dependencies.note IS NULL
          OR dependencies.note NOT LIKE 'cbl-order:%'
      )
),
changed AS (
    UPDATE threads AS t
    SET is_blocked = EXISTS (
        SELECT 1
        FROM canonically_blocked AS blocked
        WHERE blocked.thread_id = t.id
    )
    WHERE t.is_blocked IS DISTINCT FROM EXISTS (
        SELECT 1
        FROM canonically_blocked AS blocked
        WHERE blocked.thread_id = t.id
    )
    RETURNING t.user_id
)
SELECT user_id, COUNT(*) AS changed_count
FROM changed
GROUP BY user_id
ORDER BY user_id
"""


def refresh_all_users_blocked_status(bind: Connection) -> dict[int, int]:
    """Recompute ``threads.is_blocked`` for every user in one statement.

    Args:
        bind: Synchronous SQLAlchemy connection used by Alembic.

    Returns:
        Mapping of user id to the number of flags that changed. Users with
        no stale flags are omitted.
    """
    result = bind.execute(sa.text(REFRESH_ALL_USERS_BLOCKED_STATUS_SQL))
    return {int(row[0]): int(row[1]) for row in result}


async def refresh_all_users_blocked_status_async(db: AsyncSession) -> dict[int, int]:
    """Async wrapper around :func:`refresh_all_users_blocked_status`.

    Args:
        db: Application async session.

    Returns:
        Mapping of user id to the number of flags that changed. Users with
        no stale flags are omitted.
    """
    result = await db.execute(sa.text(REFRESH_ALL_USERS_BLOCKED_STATUS_SQL))
    return {int(row[0]): int(row[1]) for row in result}
