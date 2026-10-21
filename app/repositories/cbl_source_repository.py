"""Query helpers for persisted CBL source-list discovery and detail previews."""

from __future__ import annotations

from sqlalchemy import and_, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.cbl_reference import CBLSource, CBLSourceEntry, CBLSourceList
from app.models.external_identity import ExternalIdentity

COMICVINE_PROVIDER = "comicvine"


async def discover_cbl_source_lists(
    db: AsyncSession,
    *,
    query_text: str | None,
    limit: int,
) -> list[tuple[CBLSourceList, str]]:
    """Return active CBL lists matching an optional bounded text query.

    Args:
        db: Database session.
        query_text: Optional case-insensitive match against list name or source path.
        limit: Maximum number of rows to return.

    Returns:
        Active source lists paired with their source repository names in stable order.
    """
    statement = (
        select(CBLSourceList, CBLSource.repository)
        .join(CBLSource, CBLSource.id == CBLSourceList.source_id)
        .where(CBLSourceList.active.is_(True))
    )

    term = query_text.strip() if query_text else ""
    if term:
        pattern = f"%{term}%"
        statement = statement.where(
            or_(
                CBLSourceList.name.ilike(pattern),
                CBLSourceList.source_path.ilike(pattern),
            )
        )

    statement = statement.order_by(
        CBLSourceList.name.asc(),
        CBLSourceList.source_path.asc(),
        CBLSourceList.id.asc(),
    ).limit(limit)
    rows = (await db.execute(statement)).all()
    return [(row[0], row[1]) for row in rows]


async def get_cbl_source_list_detail(
    db: AsyncSession,
    *,
    list_id: int,
    offset: int,
    limit: int,
) -> tuple[CBLSourceList, str, int, list[tuple[CBLSourceEntry, str | None, str | None]]] | None:
    """Return one active CBL source list with one bounded page of ordered entries.

    Entries keep their original source position, including repeated positions
    for duplicated issues. Comic Vine IDs are resolved only from Comic Vine
    issue and series identities, so a missing or malformed provider identity
    is reported as ``None`` instead of an unrelated provider ID.

    Args:
        db: Database session.
        list_id: CBL source list identifier.
        offset: Zero-based index of the first returned source entry.
        limit: Maximum number of source entries to return.

    Returns:
        The active source list, its repository name, the total number of source
        entries, and the ordered page of entries with their Comic Vine issue and
        volume IDs. ``None`` when the list is missing or inactive.
    """
    statement = (
        select(CBLSourceList, CBLSource.repository)
        .join(CBLSource, CBLSource.id == CBLSourceList.source_id)
        .where(CBLSourceList.id == list_id, CBLSourceList.active.is_(True))
    )
    row = (await db.execute(statement)).first()
    if row is None:
        return None
    source_list, repository = row[0], row[1]

    entries_total = int(
        await db.scalar(
            select(func.count())
            .select_from(CBLSourceEntry)
            .where(CBLSourceEntry.list_id == list_id)
        )
        or 0
    )

    issue_identity = ExternalIdentity.__table__.alias("issue_identity")
    series_identity = ExternalIdentity.__table__.alias("series_identity")
    entries_statement = (
        select(
            CBLSourceEntry,
            issue_identity.c.external_id,
            series_identity.c.external_id,
        )
        .outerjoin(
            issue_identity,
            and_(
                issue_identity.c.id == CBLSourceEntry.external_issue_identity_id,
                issue_identity.c.provider == COMICVINE_PROVIDER,
                issue_identity.c.entity_type == "issue",
            ),
        )
        .outerjoin(
            series_identity,
            and_(
                series_identity.c.id == CBLSourceEntry.external_series_identity_id,
                series_identity.c.provider == COMICVINE_PROVIDER,
                series_identity.c.entity_type == "series",
            ),
        )
        .where(CBLSourceEntry.list_id == list_id)
        .order_by(CBLSourceEntry.position.asc(), CBLSourceEntry.id.asc())
        .offset(offset)
        .limit(limit)
    )
    entry_rows = (await db.execute(entries_statement)).all()
    entries = [(r[0], r[1], r[2]) for r in entry_rows]
    return source_list, repository, entries_total, entries
