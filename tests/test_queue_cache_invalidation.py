"""Focused coverage for queue cache invalidation."""

from unittest.mock import AsyncMock

import pytest

from app.api import queue


@pytest.mark.asyncio
async def test_queue_invalidation_uses_one_user_generation_bump(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Queue mutations should invalidate one bounded user namespace.

    Args:
        monkeypatch: Pytest fixture used to replace the generation invalidator.

    Returns:
        None.
    """
    invalidator = AsyncMock(return_value=True)
    monkeypatch.setattr(queue, "invalidate_user_view", invalidator)

    await queue._invalidate_queue_caches(17)

    invalidator.assert_awaited_once_with(17)


@pytest.mark.asyncio
async def test_queue_invalidation_keeps_users_isolated(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Separate owners must remain separate generation invalidations.

    Args:
        monkeypatch: Pytest fixture used to replace the generation invalidator.

    Returns:
        None.
    """
    invalidator = AsyncMock(return_value=True)
    monkeypatch.setattr(queue, "invalidate_user_view", invalidator)

    await queue._invalidate_queue_caches(17)
    await queue._invalidate_queue_caches(23)

    assert invalidator.await_count == 2
    assert [call.args for call in invalidator.await_args_list] == [(17,), (23,)]
