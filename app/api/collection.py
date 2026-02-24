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

    # Extract attributes immediately after refresh to avoid MissingGreenlet error
    new_collection_id = new_collection.id
    new_collection_name = new_collection.name
    new_collection_user_id = new_collection.user_id
    new_collection_is_default = new_collection.is_default
    new_collection_position = new_collection.position
    new_collection_created_at = new_collection.created_at

    return CollectionResponse(
        id=new_collection_id,
        name=new_collection_name,
        user_id=new_collection_user_id,
        is_default=new_collection_is_default,
        position=new_collection_position,
        created_at=new_collection_created_at,
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
        page_token: Token for pagination continuation (position value).

    Returns:
        CollectionListResponse with paginated collections.
    """
    query = select(Collection).where(Collection.user_id == current_user.id)
    query = query.order_by(Collection.position)

    # Apply cursor-based pagination if page_token provided
    # Uses composite cursor of (position, id) to handle non-unique positions
    if page_token:
        try:
            parts = page_token.split(",")
            if len(parts) != 2:
                raise ValueError("Invalid format")
            cursor_position = int(parts[0])
            cursor_id = int(parts[1])
            # Filter: (position > cursor_position) OR (position == cursor_position AND id > cursor_id)
            from sqlalchemy import or_

            query = query.where(
                or_(
                    Collection.position > cursor_position,
                    (Collection.position == cursor_position) & (Collection.id > cursor_id),
                )
            )
        except ValueError:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Invalid page_token format",
            ) from None

    # Query for page_size + 1 to detect if there's a next page
    query = query.limit(page_size + 1)

    result = await db.execute(query)
    collections = result.scalars().all()

    # Check if there are more pages
    has_more = len(collections) > page_size

    # Only return the first page_size items
    collections_to_return = collections[:page_size]

    collection_responses = [
        CollectionResponse(
            id=c.id,
            name=c.name,
            user_id=c.user_id,
            is_default=c.is_default,
            position=c.position,
            created_at=c.created_at,
        )
        for c in collections_to_return
    ]

    # Set next_page_token to composite cursor of last item if there are more pages
    next_token = None
    if has_more and collections_to_return:
        last = collections_to_return[-1]
        next_token = f"{last.position},{last.id}"

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

    # Extract attributes before commit to avoid MissingGreenlet error
    collection_id_val = collection.id
    collection_name = collection.name
    collection_user_id = collection.user_id
    collection_is_default = collection.is_default
    collection_position = collection.position
    collection_created_at = collection.created_at

    await db.commit()

    return CollectionResponse(
        id=collection_id_val,
        name=collection_name,
        user_id=collection_user_id,
        is_default=collection_is_default,
        position=collection_position,
        created_at=collection_created_at,
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

    # Extract attributes before commit to avoid MissingGreenlet error
    collection_id_val = collection.id
    collection_name = collection.name
    collection_user_id = collection.user_id
    collection_is_default = collection.is_default
    collection_position = collection.position
    collection_created_at = collection.created_at

    await db.commit()

    return CollectionResponse(
        id=collection_id_val,
        name=collection_name,
        user_id=collection_user_id,
        is_default=collection_is_default,
        position=collection_position,
        created_at=collection_created_at,
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

    if collection.is_default:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Cannot delete default collection",
        )

    # Update threads to remove collection reference
    from app.models import Thread

    await db.execute(
        sa_update(Thread)
        .where(Thread.collection_id == collection_id)
        .where(Thread.user_id == current_user.id)
        .values(collection_id=None)
    )

    await db.delete(collection)
    await db.commit()
