"""Query helpers for persisted CBL source-list discovery."""

from __future__ import annotations

from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.cbl_reference import CBLSource, CBLSourceEntry, CBLSourceList
from app.models.external_identity import ExternalIdentity


async def discover_cbl_source_lists(
    db: AsyncSession,
    *,
    query_text: str | None,
    limit: int,
) -> list[tuple[CBLSourceList, str]]:
    """Return active CBL lists matching an optional bounded text query."""
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
) -> tuple[CBLSourceList, str, list[tuple[CBLSourceEntry, str | None, str | None]]] | None:
    """Return one active CBL source list with all ordered entries and Comic Vine IDs."""
    statement = (
        select(CBLSourceList, CBLSource.repository)
        .join(CBLSource, CBLSource.id == CBLSourceList.source_id)
        .where(CBLSourceList.id == list_id, CBLSourceList.active.is_(True))
    )
    row = (await db.execute(statement)).first()
    if row is None:
        return None
    source_list, repository = row[0], row[1]

    issue_identity = ExternalIdentity.__table__.alias("issue_identity")
    series_identity = ExternalIdentity.__table__.alias("series_identity")
    entries_statement = (
        select(
            CBLSourceEntry,
            issue_identity.c.external_id,
            series_identity.c.external_id,
        )
        .outerjoin(issue_identity, issue_identity.c.id == CBLSourceEntry.external_issue_identity_id)
        .outerjoin(series_identity, series_identity.c.id == CBLSourceEntry.external_series_identity_id)
        .where(CBLSourceEntry.list_id == list_id)
        .order_by(CBLSourceEntry.position.asc(), CBLSourceEntry.id.asc())
    )
    entry_rows = (await db.execute(entries_statement)).all()
    entries = [(r[0], r[1], r[2]) for r in entry_rows]
    return source_list, repository, entries
