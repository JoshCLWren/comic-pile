"""Model- and schema-level collection exclusion contracts.

These checks do not use the retired HTTP endpoints; they pin the durable
``CollectionExclusion`` database constraints and the public payload validation
that the CBL reconciliation and adoption services still rely on.
"""

import pytest
from pydantic import ValidationError
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import User
from app.models.collection_exclusion import CollectionExclusion
from app.schemas.collection_exclusion import CollectionExclusionCreate


async def test_database_exactly_one_target_constraint(
    async_db: AsyncSession, default_user: User
) -> None:
    """Database enforcement remains effective for writers bypassing Pydantic."""
    user_id = default_user.id
    with pytest.raises(IntegrityError):
        async with async_db.begin_nested():
            async_db.add(
                CollectionExclusion(user_id=user_id, thread_id=1, issue_id=6)
            )
            await async_db.flush()
    with pytest.raises(IntegrityError):
        async with async_db.begin_nested():
            async_db.add(
                CollectionExclusion(user_id=user_id, external_volume_id="4050-1")
            )
            await async_db.flush()


def test_payload_validation_without_database() -> None:
    """Validate the public exactly-one-target contract independently of FastAPI."""
    with pytest.raises(ValidationError):
        CollectionExclusionCreate(thread_id=1, issue_id=2)
    with pytest.raises(ValidationError):
        CollectionExclusionCreate(provider="comicvine", external_volume_id=" ")
