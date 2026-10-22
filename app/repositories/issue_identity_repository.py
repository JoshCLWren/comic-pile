"""Issue identity reconciliation query construction and persistence.

All SQLAlchemy access for issue identity reconciliation operations lives here.
Functions return ORM models, plain rows/tuples, or counts; callers (services) own
transaction boundaries.
"""

from collections.abc import Iterable
from dataclasses import dataclass

from sqlalchemy import select, text
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.engine import Result
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.sql.elements import TextClause

from app.models.external_identity import ExternalIdentity, IssueExternalIdentityMapping
from app.models.issue import Issue
from app.models.thread import Thread


@dataclass(frozen=True, slots=True)
class ConfirmedComicvineIssueIdentity:
    """One confirmed Comic Vine issue identity for a reader-owned Issue."""

    issue_id: int
    external_identity_id: int
    comicvine_issue_id: str


def _as_int_tuple(value: object) -> tuple[int, ...]:
    """Convert a database array value to a tuple of integers."""
    if value is None:
        return ()
    if not isinstance(value, Iterable) or isinstance(value, str | bytes):
        raise TypeError("Expected an iterable database array value")
    return tuple(int(item) for item in value)


def _as_str_tuple(value: object) -> tuple[str, ...]:
    """Convert a database array value to a tuple of strings."""
    if value is None:
        return ()
    if not isinstance(value, Iterable) or isinstance(value, str | bytes):
        raise TypeError("Expected an iterable database array value")
    return tuple(str(item) for item in value)


def _as_object_list(value: object) -> list[object]:
    """Convert a database array value to a list of objects."""
    if value is None:
        return []
    if not isinstance(value, Iterable) or isinstance(value, str | bytes):
        raise TypeError("Expected an iterable database array value")
    return list(value)


def _count_scalar(result: Result[int]) -> int:
    """Return an integer scalar count from a SQLAlchemy result."""
    return int(result.scalar_one() or 0)


async def find_confirmed_comicvine_issue_identities(
    db: AsyncSession,
    *,
    user_id: int,
    issue_ids: tuple[int, ...],
) -> tuple[ConfirmedComicvineIssueIdentity, ...]:
    """Return confirmed Comic Vine identities for reader-owned Issues only.

    A confirmed mapping is the canonical exact identity used to query the
    shared CBL catalog. Candidate, rejected, deferred, and unresolved mappings
    are deliberately excluded so a list comparison never guesses an identity.
    Conflicting confirmed mappings are returned as separate rows so the caller
    can report the conflict instead of choosing one silently.

    Args:
        db: Database session.
        user_id: Owner of the Issues' Threads.
        issue_ids: ComicPile Issue IDs to resolve.

    Returns:
        Confirmed identity rows ordered by Issue position, Issue ID, and
        external identity ID.
    """
    if not issue_ids:
        return ()

    statement = (
        select(
            IssueExternalIdentityMapping.issue_id,
            ExternalIdentity.id,
            ExternalIdentity.external_id,
        )
        .join(
            ExternalIdentity,
            ExternalIdentity.id == IssueExternalIdentityMapping.external_identity_id,
        )
        .join(Issue, Issue.id == IssueExternalIdentityMapping.issue_id)
        .join(Thread, Thread.id == Issue.thread_id)
        .where(
            Thread.user_id == user_id,
            IssueExternalIdentityMapping.issue_id.in_(issue_ids),
            IssueExternalIdentityMapping.status == "confirmed",
            ExternalIdentity.provider == "comicvine",
            ExternalIdentity.entity_type == "issue",
        )
        .order_by(
            Issue.position.asc(),
            Issue.id.asc(),
            ExternalIdentity.id.asc(),
        )
    )
    rows = (await db.execute(statement)).all()
    return tuple(
        ConfirmedComicvineIssueIdentity(
            issue_id=int(row[0]),
            external_identity_id=int(row[1]),
            comicvine_issue_id=str(row[2]),
        )
        for row in rows
    )


_DUPLICATE_ANOMALY_COUNT_SQL = text(
    """
    SELECT COUNT(*) as total
    FROM (
        SELECT ei.id
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
    ) sub
    """
)


def _paged_duplicate_anomaly_sql(limit: int | None) -> TextClause:
    """Build the duplicate anomaly query with optional pagination."""
    query = """
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
        """
    if limit is None:
        return text(query)
    return text(f"{query.rstrip()}\nLIMIT :limit OFFSET :offset")


async def count_duplicate_physical_issues(
    db: AsyncSession,
    *,
    user_id: int,
) -> int:
    """Count confirmed ComicVine identities that map to multiple user-owned issues.

    Args:
        db: Async database session.
        user_id: Owner user ID to scope the count.

    Returns:
        Total number of duplicate anomaly groups.
    """
    result = await db.execute(
        _DUPLICATE_ANOMALY_COUNT_SQL,
        {
            "provider": "comicvine",
            "entity_type": "issue",
            "confirmed": "confirmed",
            "user_id": user_id,
        },
    )
    return _count_scalar(result)


async def find_duplicate_physical_issues(
    db: AsyncSession,
    *,
    user_id: int,
    limit: int | None = None,
    offset: int = 0,
) -> list[dict[str, object]]:
    """Find confirmed ComicVine identities that map to multiple user-owned issues.

    A duplicate is defined as one ExternalIdentity (comicvine issue) with
    status=confirmed on multiple Issue rows that belong to the same user via
    their threads. Thread boundaries do not define physical identity - two
    threads with issues at the same position/number can still be the same
    physical comic when their ComicVine IDs agree.

    Args:
        db: Async database session.
        user_id: Owner user ID to scope the anomaly search.
        limit: Optional maximum number of anomaly groups to return.
        offset: Number of anomaly groups to skip.

    Returns:
        One anomaly per duplicated ComicVine issue identity, each listing all
        affected Issue rows for that user.
    """
    params = {
        "provider": "comicvine",
        "entity_type": "issue",
        "confirmed": "confirmed",
        "user_id": user_id,
    }
    if limit is not None:
        params.update({"limit": limit, "offset": offset})
    result = await db.execute(_paged_duplicate_anomaly_sql(limit), params)
    anomalies: list[dict[str, object]] = []
    for row in result.mappings():
        issue_ids = _as_int_tuple(row["issue_ids"])
        thread_ids = _as_int_tuple(row["thread_ids"])
        statuses = _as_str_tuple(row["statuses"])
        has_read = "read" in statuses
        has_unread = "unread" in statuses
        issue_numbers = _as_object_list(row["issue_numbers"])
        thread_titles = _as_object_list(row["thread_titles"])
        read_ats = _as_object_list(row["read_ats"])
        details: list[dict[str, object]] = []
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


_CONFLICT_COUNT_SQL = text(
    """
    SELECT COUNT(*) as total
    FROM (
        SELECT i.id
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
    ) sub
    """
)

_CONFLICT_QUERY_SQL = text(
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
    """
)


def _paged_conflict_sql(limit: int | None) -> TextClause:
    """Build the conflict query with optional pagination."""
    query = """
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
        """
    if limit is None:
        return text(query)
    return text(f"{query.rstrip()}\nLIMIT :limit OFFSET :offset")


async def count_conflicting_provider_identities(
    db: AsyncSession,
    *,
    user_id: int,
) -> int:
    """Count issues that have confirmed mappings to different ComicVine IDs.

    Args:
        db: Async database session.
        user_id: Owner user ID.

    Returns:
        Total number of conflict groups.
    """
    result = await db.execute(
        _CONFLICT_COUNT_SQL,
        {
            "provider": "comicvine",
            "entity_type": "issue",
            "confirmed": "confirmed",
            "user_id": user_id,
        },
    )
    return _count_scalar(result)


async def find_conflicting_provider_identities(
    db: AsyncSession,
    *,
    user_id: int,
    limit: int | None = None,
    offset: int = 0,
) -> list[dict[str, object]]:
    """Find issues that have confirmed mappings to different ComicVine IDs.

    This surfaces ambiguous cases where the same Issue row claims conflicting
    provider identities (should not happen via normal single-provider confirm
    but may exist from legacy or manual corrections). These are reported
    rather than silently merged.

    Args:
        db: Async database session.
        user_id: Owner user ID.
        limit: Optional maximum number of conflicts to return.
        offset: Number of conflict groups to skip.

    Returns:
        One entry per Issue with conflicting confirmed ComicVine IDs.
    """
    params = {
        "provider": "comicvine",
        "entity_type": "issue",
        "confirmed": "confirmed",
        "user_id": user_id,
    }
    if limit is not None:
        params.update({"limit": limit, "offset": offset})
    result = await db.execute(_paged_conflict_sql(limit), params)
    conflicts: list[dict[str, object]] = []
    for row in result.mappings():
        conflicts.append(
            {
                "issue_id": int(row["issue_id"]),
                "thread_id": int(row["thread_id"]),
                "thread_title": str(row["thread_title"] or ""),
                "issue_number": str(row["issue_number"] or ""),
                "comicvine_ids": list(_as_str_tuple(row["comicvine_ids"])),
                "distinct_identities": int(row["distinct_identities"]),
            }
        )
    return conflicts


async def upsert_comicvine_external_identity(
    db: AsyncSession,
    *,
    external_id: str,
    series_name: str,
    volume_year: int | None,
) -> ExternalIdentity:
    """Upsert a Comic Vine external identity with metadata.
    
    Args:
        db: Database session.
        external_id: Comic Vine issue external ID.
        series_name: Series name for metadata.
        volume_year: Volume start year for metadata.
        
    Returns:
        The external identity (existing or newly created).
    """
    # Build the upsert statement
    statement = pg_insert(ExternalIdentity).values(
        provider="comicvine",
        entity_type="issue",
        external_id=external_id,
        metadata_json={
            "volume": {
                "name": series_name,
                "start_year": volume_year,
            }
        },
    ).on_conflict_do_nothing(
        index_elements=("provider", "entity_type", "external_id"),
    )
    
    await db.execute(statement)
    
    # Return the existing or newly created identity
    result = await db.execute(
        select(ExternalIdentity).where(
            ExternalIdentity.provider == "comicvine",
            ExternalIdentity.entity_type == "issue",
            ExternalIdentity.external_id == external_id,
        )
    )
    return result.scalar_one()


async def get_comicvine_external_identity(
    db: AsyncSession,
    *,
    external_id: str,
) -> ExternalIdentity | None:
    """Get a Comic Vine external identity by external ID.
    
    Args:
        db: Database session.
        external_id: Comic Vine issue external ID.
        
    Returns:
        The external identity, or None if not found.
    """
    result = await db.execute(
        select(ExternalIdentity).where(
            ExternalIdentity.provider == "comicvine",
            ExternalIdentity.entity_type == "issue",
            ExternalIdentity.external_id == external_id,
        )
    )
    return result.scalar_one_or_none()


async def upsert_issue_external_identity_mapping(
    db: AsyncSession,
    *,
    issue_id: int,
    external_identity_id: int,
    status: str = "confirmed",
    evidence_source: str = "fixture",
) -> IssueExternalIdentityMapping:
    """Upsert an issue to external identity mapping.
    
    Args:
        db: Database session.
        issue_id: Issue ID to map.
        external_identity_id: External identity ID to map to.
        status: Mapping status (default: "confirmed").
        evidence_source: Source of the mapping evidence.
        
    Returns:
        The mapping (existing or newly created).
    """
    # Build the upsert statement
    statement = pg_insert(IssueExternalIdentityMapping).values(
        issue_id=issue_id,
        external_identity_id=external_identity_id,
        status=status,
        evidence_source=evidence_source,
    ).on_conflict_do_nothing(
        index_elements=("issue_id", "external_identity_id"),
    )
    
    await db.execute(statement)
    
    # Return the existing or newly created mapping
    result = await db.execute(
        select(IssueExternalIdentityMapping).where(
            IssueExternalIdentityMapping.issue_id == issue_id,
            IssueExternalIdentityMapping.external_identity_id == external_identity_id,
        )
    )
    return result.scalar_one()
