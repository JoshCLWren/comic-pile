"""Collection API endpoints."""

from datetime import UTC, datetime
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.future import select

from app.auth import get_current_user
from app.database import get_db
from app.models import Collection
from app.models.user import User
from app.schemas.collection import (
    CollectionCreate,
    CollectionListResponse,
    CollectionResponse,
    CollectionUpdate,
)

router = APIRouter(tags=["collections"])


@router.post("/", response_model=CollectionResponse, status_code=status.HTTP_201_CREATED)
async def create_collection(
    collection_data: CollectionCreate,
    current_user: Annotated[User, Depends(get_current_user)],
    db: AsyncSession = Depends(get_db),
) -> CollectionResponse:
    """Create a new collection.

    Args:
        collection_data: Collection creation data.
        current_user: The authenticated user making the request.
        db: SQLAlchemy session for database operations.

    Returns:
        CollectionResponse with created collection details.
    """
    new_collection = Collection(
        name=collection_data.name,
        user_id=current_user.id,
        is_default=collection_data.is_default,
        position=collection_data.position,
        created_at=datetime.now(UTC),
    )
    db.add(new_collection)
    await db.commit()
    await db.refresh(new_collection)

    return CollectionResponse(
        id=new_collection.id,
        name=new_collection.name,
        user_id=new_collection.user_id,
        is_default=new_collection.is_default,
        position=new_collection.position,
        created_at=new_collection.created_at,
    )


@router.get("/", response_model=CollectionListResponse)
async def list_collections(
    current_user: Annotated[User, Depends(get_current_user)],
    db: AsyncSession = Depends(get_db),
    page_size: int = Query(50, ge=1, le=100),
    page_token: str | None = Query(None),
) -> CollectionListResponse:
    """List collections with pagination.

    Args:
        current_user: The authenticated user making the request.
        db: SQLAlchemy session for database operations.
        page_size: Number of collections to return per page.
        page_token: Token for pagination continuation.

    Returns:
        CollectionListResponse with paginated collections.
    """
    query = select(Collection).where(Collection.user_id == current_user.id)
    query = query.order_by(Collection.position)
    query = query.limit(page_size)

    result = await db.execute(query)
    collections = result.scalars().all()

    collection_responses = [
        CollectionResponse(
            id=c.id,
            name=c.name,
            user_id=c.user_id,
            is_default=c.is_default,
            position=c.position,
            created_at=c.created_at,
        )
        for c in collections
    ]

    # Simple pagination - return empty next_page_token for now
    next_token = None
    if len(collections) == page_size:
        # In a real implementation, this would be an encoded cursor
        next_token = ""

    return CollectionListResponse(
        collections=collection_responses,
        next_page_token=next_token,
    )


@router.get("/{collection_id}", response_model=CollectionResponse)
async def get_collection(
    collection_id: int,
    current_user: Annotated[User, Depends(get_current_user)],
    db: AsyncSession = Depends(get_db),
) -> CollectionResponse:
    """Get a single collection.

    Args:
        collection_id: The collection ID to retrieve.
        current_user: The authenticated user making the request.
        db: SQLAlchemy session for database operations.

    Returns:
        CollectionResponse with collection details.

    Raises:
        HTTPException: If collection not found.
    """
    collection = await db.get(Collection, collection_id)
    if not collection or collection.user_id != current_user.id:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Collection {collection_id} not found",
        )

    return CollectionResponse(
        id=collection.id,
        name=collection.name,
        user_id=collection.user_id,
        is_default=collection.is_default,
        position=collection.position,
        created_at=collection.created_at,
    )


@router.put("/{collection_id}", response_model=CollectionResponse)
async def update_collection(
    collection_id: int,
    collection_data: CollectionUpdate,
    current_user: Annotated[User, Depends(get_current_user)],
    db: AsyncSession = Depends(get_db),
) -> CollectionResponse:
    """Update a collection (full update).

    Args:
        collection_id: The collection ID to update.
        collection_data: Collection update data.
        current_user: The authenticated user making the request.
        db: SQLAlchemy session for database operations.

    Returns:
        CollectionResponse with updated collection details.

    Raises:
        HTTPException: If collection not found.
    """
    collection = await db.get(Collection, collection_id)
    if not collection or collection.user_id != current_user.id:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Collection {collection_id} not found",
        )

    if collection_data.name is not None:
        collection.name = collection_data.name
    if collection_data.is_default is not None:
        collection.is_default = collection_data.is_default
    if collection_data.position is not None:
        collection.position = collection_data.position

    await db.commit()
    await db.refresh(collection)

    return CollectionResponse(
        id=collection.id,
        name=collection.name,
        user_id=collection.user_id,
        is_default=collection.is_default,
        position=collection.position,
        created_at=collection.created_at,
    )


@router.patch("/{collection_id}", response_model=CollectionResponse)
async def patch_collection(
    collection_id: int,
    collection_data: CollectionUpdate,
    current_user: Annotated[User, Depends(get_current_user)],
    db: AsyncSession = Depends(get_db),
) -> CollectionResponse:
    """Partial update of a collection.

    Args:
        collection_id: The collection ID to update.
        collection_data: Collection update data.
        current_user: The authenticated user making the request.
        db: SQLAlchemy session for database operations.

    Returns:
        CollectionResponse with updated collection details.

    Raises:
        HTTPException: If collection not found.
    """
    collection = await db.get(Collection, collection_id)
    if not collection or collection.user_id != current_user.id:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Collection {collection_id} not found",
        )

    if collection_data.name is not None:
        collection.name = collection_data.name
    if collection_data.is_default is not None:
        collection.is_default = collection_data.is_default
    if collection_data.position is not None:
        collection.position = collection_data.position

    await db.commit()
    await db.refresh(collection)

    return CollectionResponse(
        id=collection.id,
        name=collection.name,
        user_id=collection.user_id,
        is_default=collection.is_default,
        position=collection.position,
        created_at=collection.created_at,
    )


@router.delete("/{collection_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_collection(
    collection_id: int,
    current_user: Annotated[User, Depends(get_current_user)],
    db: AsyncSession = Depends(get_db),
) -> None:
    """Delete a collection. Threads move to default/null.

    Args:
        collection_id: The collection ID to delete.
        current_user: The authenticated user making the request.
        db: SQLAlchemy session for database operations.

    Raises:
        HTTPException: If collection not found.
    """
    from sqlalchemy import update as sa_update

    collection = await db.get(Collection, collection_id)
    if not collection or collection.user_id != current_user.id:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Collection {collection_id} not found",
        )

    # Update threads to remove collection reference
    from app.models import Thread

    await db.execute(
        sa_update(Thread).where(Thread.collection_id == collection_id).values(collection_id=None)
    )

    await db.delete(collection)
    await db.commit()
