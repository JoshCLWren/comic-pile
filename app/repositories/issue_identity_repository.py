"""Issue identity reconciliation query construction and persistence.

All SQLAlchemy access for issue identity reconciliation operations lives here.
Functions return ORM models, plain rows/tuples, or counts; callers (services) own
transaction boundaries.
"""

from typing import Any

from sqlalchemy import func, select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import ExternalIdentity, Issue, Thread, IssueExternalIdentityMapping


async def find_duplicate_physical_issues(
    db: AsyncSession,
    *,
    user_id: int,
    limit: int = 100,
) -> list[dict[str, Any]]:
    """Find confirmed ComicVine identities that map to multiple user-owned issues.

    A duplicate is defined as one ExternalIdentity (comicvine issue) with
    status=confirmed on multiple Issue rows that belong to the same user via
    their threads. Thread boundaries do not define physical identity - two
    threads with issues at the same position/number can still be the same
    physical comic when their ComicVine IDs agree.

    Args:
        db: Async database session.
        user_id: Owner user ID to scope the anomaly search.
        limit: Maximum number of anomalies to return (hard cap).

    Returns:
        One anomaly per duplicated ComicVine issue identity, each listing all
        affected Issue rows for that user.
    """
    result = await db.execute(
        text(
            """
            SELECT
                ei.external_id AS comicvine_issue_id,
                ei.id AS external_identity_id,
                array_agg(iem.issue_id ORDER BY iem.issue_id) AS issue_ids,
                array_agg(i.thread_id ORDER BY iem.issue_id) AS thread_ids,
                array_agg(i.status ORDER BY iem.issue_id) AS statuses,
                array_agg(i.read_at ORDER BY iem.issue_id) AS read_ats,
                array_agg(i.issue_number ORDER BY iem.issue_id) AS issue_numbers,
                array_agg(t.title ORDER BY iem.issue_id) AS thread_titles
            FROM external_identities ei
            JOIN issue_external_identity_mappings iem
                ON iem.external_identity_id = ei.id
            JOIN issues i ON i.id = iem.issue_id
            JOIN threads t ON t.id = i.thread_id
            WHERE ei.provider = :provider
              AND ei.entity_type = :entity_type
              AND iem.status = :confirmed
              AND t.user_id = :user_id
            GROUP BY ei.id, ei.external_id
            HAVING COUNT(DISTINCT iem.issue_id) > 1
            ORDER BY ei.external_id
            LIMIT :limit
            """
        ),
        {
            "provider": "comicvine",
            "entity_type": "issue",
            "confirmed": "confirmed",
            "user_id": user_id,
            "limit": limit,
        },
    )
    anomalies: list[dict[str, Any]] = []
    for row in result.mappings():
        issue_ids = tuple(int(v) for v in (row["issue_ids"] or []))
        thread_ids = tuple(int(v) for v in (row["thread_ids"] or []))
        statuses = tuple(str(v) for v in (row["statuses"] or []))
        has_read = "read" in statuses
        has_unread = "unread" in statuses
        issue_numbers = list(row["issue_numbers"] or [])
        thread_titles = list(row["thread_titles"] or [])
        read_ats = list(row["read_ats"] or [])
        details: list[dict[str, Any]] = []
        for idx, iid in enumerate(issue_ids):
            details.append(
                {
                    "issue_id": iid,
                    "thread_id": thread_ids[idx] if idx < len(thread_ids) else None,
                    "thread_title": thread_titles[idx] if idx < len(thread_titles) else None,
                    "issue_number": issue_numbers[idx] if idx < len(issue_numbers) else None,
                    "status": statuses[idx] if idx < len(statuses) else None,
                    "read_at": read_ats[idx] if idx < len(read_ats) else None,
                }
            )
        anomalies.append(
            {
                "comicvine_issue_id": str(row["comicvine_issue_id"]),
                "external_identity_id": int(row["external_identity_id"]),
                "issue_ids": issue_ids,
                "thread_ids": thread_ids,
                "statuses": statuses,
                "has_read": has_read,
                "has_unread": has_unread,
                "issue_details": tuple(details),
            }
        )
    return anomalies


async def find_conflicting_provider_identities(
    db: AsyncSession,
    *,
    user_id: int,
    limit: int = 100,
) -> list[dict[str, Any]]:
    """Find issues that have confirmed mappings to different ComicVine IDs.

    This surfaces ambiguous cases where the same Issue row claims conflicting
    provider identities (should not happen via normal single-provider confirm
    but may exist from legacy or manual corrections). These are reported
    rather than silently merged.

    Args:
        db: Async database session.
        user_id: Owner user ID.
        limit: Maximum number of conflicts to return (hard cap).

    Returns:
        One entry per Issue with conflicting confirmed ComicVine IDs.
    """
    result = await db.execute(
        text(
            """
            SELECT
                i.id AS issue_id,
                i.thread_id,
                t.title AS thread_title,
                i.issue_number,
                array_agg(ei.external_id ORDER BY ei.external_id) AS comicvine_ids,
                COUNT(DISTINCT ei.id) AS distinct_identities
            FROM issues i
            JOIN threads t ON t.id = i.thread_id
            JOIN issue_external_identity_mappings iem ON iem.issue_id = i.id
            JOIN external_identities ei ON ei.id = iem.external_identity_id
            WHERE t.user_id = :user_id
              AND ei.provider = :provider
              AND ei.entity_type = :entity_type
              AND iem.status = :confirmed
            GROUP BY i.id, i.thread_id, t.title, i.issue_number
            HAVING COUNT(DISTINCT ei.id) > 1
            ORDER BY i.id
            LIMIT :limit
            """
        ),
        {
            "provider": "comicvine",
            "entity_type": "issue",
            "confirmed": "confirmed",
            "user_id": user_id,
            "limit": limit,
        },
    )
    conflicts: list[dict[str, Any]] = []
    for row in result.mappings():
        conflicts.append(
            {
                "issue_id": int(row["issue_id"]),
                "thread_id": int(row["thread_id"]),
                "thread_title": str(row["thread_title"] or ""),
                "issue_number": str(row["issue_number"] or ""),
                "comicvine_ids": list(row["comicvine_ids"] or []),
                "distinct_identities": int(row["distinct_identities"]),
            }
        )
    return conflicts