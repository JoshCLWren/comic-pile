"""Queries and writes for owner-scoped collection exclusion records."""

from sqlalchemy import delete, select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.collection_exclusion import CollectionExclusion
from app.models.issue import Issue
from app.models.thread import Thread


async def get_owned_thread(db: AsyncSession, user_id: int, thread_id: int) -> bool:
    """Check that the user owns the named Thread without lazy-loading."""
    result = await db.execute(
        select(Thread.id).where(Thread.id == thread_id, Thread.user_id == user_id)
    )
    return result.scalar_one_or_none() is not None


async def get_owned_issue(db: AsyncSession, user_id: int, issue_id: int) -> bool:
    """Check that the named Issue belongs to one of the user's Threads."""
    result = await db.execute(
        select(Issue.id)
        .join(Thread, Thread.id == Issue.thread_id)
        .where(Issue.id == issue_id, Thread.user_id == user_id)
    )
    return result.scalar_one_or_none() is not None


async def list_for_owner(db: AsyncSession, user_id: int) -> list[CollectionExclusion]:
    """List only one reader's durable exclusions in stable order."""
    result = await db.execute(
        select(CollectionExclusion)
        .where(CollectionExclusion.user_id == user_id)
        .order_by(CollectionExclusion.id)
    )
    return list(result.scalars().all())


async def get_for_owner(
    db: AsyncSession, user_id: int, exclusion_id: int
) -> CollectionExclusion | None:
    """Look up one exclusion by ID with mandatory ownership filtering."""
    result = await db.execute(
        select(CollectionExclusion).where(
            CollectionExclusion.id == exclusion_id,
            CollectionExclusion.user_id == user_id,
        )
    )
    return result.scalar_one_or_none()


async def get_for_target(
    db: AsyncSession,
    user_id: int,
    *,
    provider: str | None,
    external_volume_id: str | None,
    thread_id: int | None,
    issue_id: int | None,
) -> CollectionExclusion | None:
    """Return a duplicate owned target if it exists."""
    statement = select(CollectionExclusion).where(CollectionExclusion.user_id == user_id)
    if external_volume_id is not None:
        statement = statement.where(
            CollectionExclusion.provider == provider,
            CollectionExclusion.external_volume_id == external_volume_id,
        )
    elif thread_id is not None:
        statement = statement.where(CollectionExclusion.thread_id == thread_id)
    else:
        statement = statement.where(CollectionExclusion.issue_id == issue_id)
    result = await db.execute(statement)
    return result.scalar_one_or_none()


async def insert_idempotently(
    db: AsyncSession,
    user_id: int,
    *,
    provider: str | None,
    external_volume_id: str | None,
    thread_id: int | None,
    issue_id: int | None,
) -> CollectionExclusion:
    """Use PostgreSQL uniqueness to make concurrent identical POSTs safe."""
    await db.execute(
        insert(CollectionExclusion)
        .values(
            user_id=user_id,
            provider=provider,
            external_volume_id=external_volume_id,
            thread_id=thread_id,
            issue_id=issue_id,
        )
        .on_conflict_do_nothing()
    )
    row = await get_for_target(
        db, user_id,
        provider=provider, external_volume_id=external_volume_id,
        thread_id=thread_id, issue_id=issue_id,
    )
    if row is None:
        raise RuntimeError("Collection exclusion not found after idempotent insert")
    return row


async def delete_for_owner(db: AsyncSession, user_id: int, exclusion_id: int) -> bool:
    """Delete only a reader-owned exclusion, returning whether it existed."""
    result = await db.execute(
        delete(CollectionExclusion)
        .where(
            CollectionExclusion.id == exclusion_id,
            CollectionExclusion.user_id == user_id,
        )
        .returning(CollectionExclusion.id)
    )
    return result.scalar_one_or_none() is not None
