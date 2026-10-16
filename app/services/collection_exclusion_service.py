"""Business rules for explicitly authored collection exclusions."""

from sqlalchemy.ext.asyncio import AsyncSession

from app.models.collection_exclusion import CollectionExclusion
from app.repositories import collection_exclusion_repository as repository
from app.schemas.collection_exclusion import CollectionExclusionCreate
from app.services.errors import NotFoundError
from app.repositories.reading_list_authoring_repository import lock_reader


async def list_collection_exclusions(
    db: AsyncSession, *, user_id: int
) -> list[CollectionExclusion]:
    """Read only the authenticated reader's exclusions."""
    return await repository.list_for_owner(db, user_id)


async def create_collection_exclusion(
    db: AsyncSession, *, user_id: int, payload: CollectionExclusionCreate
) -> CollectionExclusion:
    """Validate ownership and create a durable exclusion idempotently.

    An external volume identity may not exist locally yet: excluding an absent
    volume is intentional and prevents its subsequent adoption.
    """
    await lock_reader(db, user_id)
    if payload.thread_id is not None and not await repository.get_owned_thread(
        db, user_id, payload.thread_id
    ):
        raise NotFoundError("Thread not found")
    if payload.issue_id is not None and not await repository.get_owned_issue(
        db, user_id, payload.issue_id
    ):
        raise NotFoundError("Issue not found")
    row = await repository.insert_idempotently(
        db, user_id,
        provider=payload.provider,
        external_volume_id=payload.external_volume_id,
        thread_id=payload.thread_id,
        issue_id=payload.issue_id,
    )
    await db.commit()
    return row


async def delete_collection_exclusion(
    db: AsyncSession, *, user_id: int, exclusion_id: int
) -> None:
    """Remove only an exclusion that belongs to the current user."""
    await lock_reader(db, user_id)
    if not await repository.delete_for_owner(db, user_id, exclusion_id):
        raise NotFoundError("Collection exclusion not found")
    await db.commit()
