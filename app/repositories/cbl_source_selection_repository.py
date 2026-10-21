"""Query construction and persistence for reader CBL source selections.

Repositories own SQLAlchemy access for
:class:`~app.models.cbl_source_selection.CblSourceSelection`. The record holds
one reader's saved include/exclude choices for one shared CBL source list.
"""

from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.cbl_source_selection import CblSourceSelection


async def find_source_selection(
    db: AsyncSession,
    *,
    user_id: int,
    cbl_source_list_id: int,
) -> CblSourceSelection | None:
    """Return the reader's saved selection for one source list, if any.

    Args:
        db: Async database session.
        user_id: Reader whose saved choices are requested.
        cbl_source_list_id: CBL source list ID.

    Returns:
        The saved selection, or ``None`` when the reader never saved one.
    """
    result = await db.execute(
        select(CblSourceSelection).where(
            CblSourceSelection.user_id == user_id,
            CblSourceSelection.cbl_source_list_id == cbl_source_list_id,
        )
    )
    return result.scalars().first()


async def upsert_source_selection(
    db: AsyncSession,
    *,
    user_id: int,
    cbl_source_list_id: int,
    entry_decisions: dict[str, bool],
    content_hash: str,
    revision_sha: str,
) -> CblSourceSelection:
    """Create or replace the reader's saved selection for one source list.

    The unique ``(user_id, cbl_source_list_id)`` constraint makes the write
    idempotent: repeated adoption of the same source updates one record
    instead of accumulating conflicting choice sets.

    Args:
        db: Async database session inside the caller's transaction.
        user_id: Reader whose choices are saved.
        cbl_source_list_id: CBL source list ID.
        entry_decisions: Saved decisions keyed by CBL source position.
        content_hash: Source content hash observed at save time.
        revision_sha: Source revision observed at save time.

    Returns:
        The persisted selection record.
    """
    result = await db.execute(
        pg_insert(CblSourceSelection)
        .values(
            user_id=user_id,
            cbl_source_list_id=cbl_source_list_id,
            entry_decisions=entry_decisions,
            content_hash=content_hash,
            revision_sha=revision_sha,
        )
        .on_conflict_do_update(
            constraint="uq_cbl_source_selection_user_list",
            set_={
                "entry_decisions": entry_decisions,
                "content_hash": content_hash,
                "revision_sha": revision_sha,
            },
        )
        .returning(CblSourceSelection)
    )
    return result.scalar_one()
