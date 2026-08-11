"""Tests for bounded mutation cache invalidation."""

from collections.abc import Iterator
from unittest.mock import AsyncMock

import pytest

from app import cache_invalidation


@pytest.mark.asyncio
async def test_invalidate_user_view_delegates_to_generation_boundary(monkeypatch: pytest.MonkeyPatch) -> None:
    """One user mutation should issue one generation invalidation request."""
    invalidator = AsyncMock(return_value=True)
    monkeypatch.setattr(cache_invalidation, "invalidate_user_cache", invalidator)

    assert await cache_invalidation.invalidate_user_view(7) is True

    invalidator.assert_awaited_once_with(7)


@pytest.mark.asyncio
async def test_invalidate_user_views_deduplicates_inside_generation_boundary(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A logical batch should delegate each affected owner exactly once."""
    invalidator = AsyncMock(return_value=2)
    monkeypatch.setattr(cache_invalidation, "invalidate_user_caches", invalidator)

    user_ids: Iterator[int] = iter((9, 7, 7, 9))
    assert await cache_invalidation.invalidate_user_views(user_ids) == 2

    invalidator.assert_awaited_once_with((7, 9))


@pytest.mark.asyncio
@pytest.mark.parametrize("user_id", [0, -1])
async def test_invalidation_rejects_non_positive_user_ids(user_id: int) -> None:
    """Invalid owner identities must never produce shared cache invalidation."""
    with pytest.raises(ValueError, match="user_id must be positive"):
        await cache_invalidation.invalidate_user_view(user_id)

    with pytest.raises(ValueError, match="user_id must be positive"):
        await cache_invalidation.invalidate_user_views((1, user_id))


@pytest.mark.asyncio
async def test_invalid_batch_does_not_issue_partial_invalidation(monkeypatch: pytest.MonkeyPatch) -> None:
    """Validate the complete batch before touching any user generation namespace."""
    invalidator = AsyncMock(return_value=1)
    monkeypatch.setattr(cache_invalidation, "invalidate_user_caches", invalidator)

    with pytest.raises(ValueError, match="user_id must be positive"):
        await cache_invalidation.invalidate_user_views((7, 0, 9))

    invalidator.assert_not_awaited()
