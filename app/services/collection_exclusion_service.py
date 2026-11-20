"""Business rules for explicitly authored collection exclusions."""

from fastapi import HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.collection_exclusion import CollectionExclusion
from app.repositories import collection_exclusion_repository as repository
from app.schemas.collection_exclusion import CollectionExclusionCreate, CollectionExclusionResponse
from app.services.errors import InvalidRequestError, NotFoundError
from app.repositories.reading_list_authoring_repository import lock_reader
from app.services.reading_list_authoring import load_authoring_snapshot
from app.services.reading_list_cycle_validator import (
    ReadingCycleError,
    validate_reading_constraints,
)


async def _validate_mutation(db: AsyncSession, user_id: int) -> None:
    """Reject and roll back invalid exclusions while the reader lock is held."""
    try:
        snapshot, _ = await load_authoring_snapshot(db, user_id)
        validate_reading_constraints(snapshot)
    except HTTPException as error:
        await db.rollback()
        detail: object = error.detail
        message = detail.get("message") if isinstance(detail, dict) else detail
        raise InvalidRequestError(str(message or "Invalid reading constraints")) from error
    except ReadingCycleError as error:
        await db.rollback()
        raise InvalidRequestError(str(error)) from error
    except ValueError as error:
        await db.rollback()
        raise InvalidRequestError("Invalid or unresolved reading constraints") from error


async def list_collection_exclusions(
    db: AsyncSession, *, user_id: int
) -> list[CollectionExclusion]:
    """Read only the authenticated reader's exclusions."""
    return await repository.list_for_owner(db, user_id)


async def create_collection_exclusion(
    db: AsyncSession, *, user_id: int, payload: CollectionExclusionCreate
) -> CollectionExclusionResponse:
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
        db,
        user_id,
        provider=payload.provider,
        external_volume_id=payload.external_volume_id,
        thread_id=payload.thread_id,
        issue_id=payload.issue_id,
    )
    await _validate_mutation(db, user_id)
    response = CollectionExclusionResponse.model_validate(row)
    await db.commit()
    return response


async def delete_collection_exclusion(db: AsyncSession, *, user_id: int, exclusion_id: int) -> None:
    """Remove only an exclusion that belongs to the current user."""
    await lock_reader(db, user_id)
    if not await repository.delete_for_owner(db, user_id, exclusion_id):
        raise NotFoundError("Collection exclusion not found")
    await _validate_mutation(db, user_id)
    await db.commit()
