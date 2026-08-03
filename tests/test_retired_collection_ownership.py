"""Regression coverage for retired Collections ownership compatibility."""

from unittest.mock import AsyncMock

import pytest
from fastapi import HTTPException, status

from app.services.ownership import get_owned_collection_or_404


@pytest.mark.asyncio
async def test_retired_collection_reference_returns_not_found_without_querying_database() -> None:
    """Reject collection IDs without consulting retained collection persistence."""
    db = AsyncMock()

    with pytest.raises(HTTPException) as exc_info:
        await get_owned_collection_or_404(db, user_id=7, collection_id=11)

    assert exc_info.value.status_code == status.HTTP_404_NOT_FOUND
    assert exc_info.value.detail == "Collection not found"
    db.execute.assert_not_awaited()
