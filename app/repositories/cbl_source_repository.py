"""Query helpers for persisted CBL source-list discovery."""

from __future__ import annotations

from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.cbl_reference import CBLSource, CBLSourceList


async def get_source_list(
    db: AsyncSession,
    *,
    cbl_source_list_id: int,
) -> tuple[CBLSourceList, str] | None:
    """Load one shared CBL source list with its repository name.

    Args:
        db: Async database session.
        cbl_source_list_id: Shared CBL source list ID.

    Returns:
        The source list paired with its source repository name, or ``None``
        when the ID is unknown.
    """
    row = (
        await db.execute(
            select(CBLSourceList, CBLSource.repository)
            .join(CBLSource, CBLSource.id == CBLSourceList.source_id)
            .where(CBLSourceList.id == cbl_source_list_id)
        )
    ).first()
    if row is None:
        return None
    return row[0], row[1]


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
