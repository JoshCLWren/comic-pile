"""Query construction and persistence for custom CBL source links (#4021).

Repositories own all SQLAlchemy access for
:class:`~app.models.custom_cbl_source_link.CustomCBLSourceLink`. Services
never build link queries at call sites.
"""

from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.custom_cbl import CustomCBLList
from app.models.custom_cbl_source_link import CustomCBLSourceLink


async def find_link_for_user_source(
    db: AsyncSession,
    *,
    user_id: int,
    cbl_source_list_id: int,
) -> CustomCBLSourceLink | None:
    """Return this reader's durable link for one external CBL source list.

    Args:
        db: Async database session.
        user_id: Owner user ID.
        cbl_source_list_id: Shared CBL source list ID.

    Returns:
        The link row, or ``None`` when this reader has never linked the source.
    """
    return (
        await db.execute(
            select(CustomCBLSourceLink).where(
                CustomCBLSourceLink.user_id == user_id,
                CustomCBLSourceLink.cbl_source_list_id == cbl_source_list_id,
            )
        )
    ).scalar_one_or_none()


async def find_link_for_list(
    db: AsyncSession,
    *,
    custom_cbl_list_id: int,
) -> CustomCBLSourceLink | None:
    """Return the source link that claims an owned custom CBL list.

    Args:
        db: Async database session.
        custom_cbl_list_id: Reader-owned custom CBL list ID.

    Returns:
        The claiming link, or ``None`` when the list is unrelated to any CBL
        source (for example a manually authored list).
    """
    return (
        await db.execute(
            select(CustomCBLSourceLink).where(
                CustomCBLSourceLink.custom_cbl_list_id == custom_cbl_list_id,
            )
        )
    ).scalar_one_or_none()


async def get_owned_list(
    db: AsyncSession,
    *,
    custom_cbl_list_id: int,
) -> CustomCBLList | None:
    """Load one owned custom CBL list row by ID.

    Args:
        db: Async database session.
        custom_cbl_list_id: Reader-owned custom CBL list ID.

    Returns:
        The row, or ``None`` when it no longer exists.
    """
    return (
        await db.execute(
            select(CustomCBLList).where(CustomCBLList.id == custom_cbl_list_id)
        )
    ).scalar_one_or_none()


async def insert_link(
    db: AsyncSession,
    *,
    user_id: int,
    cbl_source_list_id: int,
    custom_cbl_list_id: int,
    source_revision_sha: str,
    source_content_hash: str,
) -> CustomCBLSourceLink:
    """Insert a new per-reader source link inside the caller's transaction.

    The flush surfaces the unique-constraint race so the caller can converge
    on the winning link instead of creating a second owned list.

    Args:
        db: Async database session inside the first-add transaction.
        user_id: Owner user ID.
        cbl_source_list_id: Shared CBL source list ID.
        custom_cbl_list_id: Reader-owned destination list ID.
        source_revision_sha: Source revision provenance at link time.
        source_content_hash: Source content-hash provenance at link time.

    Returns:
        The persisted link.
    """
    link = CustomCBLSourceLink(
        user_id=user_id,
        cbl_source_list_id=cbl_source_list_id,
        custom_cbl_list_id=custom_cbl_list_id,
        source_revision_sha=source_revision_sha,
        source_content_hash=source_content_hash,
    )
    db.add(link)
    await db.flush()
    return link
