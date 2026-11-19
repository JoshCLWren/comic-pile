"""Model- and schema-level collection exclusion contracts.

These checks do not use the retired HTTP endpoints; they pin the durable
``CollectionExclusion`` database constraints and the public payload validation
that the CBL reconciliation and adoption services still rely on.
"""

import pytest
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import User
from app.models.collection_exclusion import CollectionExclusion


async def test_database_exactly_one_target_constraint(
    async_db: AsyncSession, default_user: User
) -> None:
    """Database enforcement remains effective for writers bypassing Pydantic."""
    user_id = default_user.id
    with pytest.raises(IntegrityError):
        async with async_db.begin_nested():
            async_db.add(CollectionExclusion(user_id=user_id, thread_id=1, issue_id=6))
            await async_db.flush()
    with pytest.raises(IntegrityError):
        async with async_db.begin_nested():
            async_db.add(CollectionExclusion(user_id=user_id, external_volume_id="4050-1"))
            await async_db.flush()
