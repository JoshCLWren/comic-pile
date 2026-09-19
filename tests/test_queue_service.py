"""Focused unit coverage for queue service orchestration.

The queue router now delegates every mutation to ``QueueService``. These
tests pin the orchestration decisions (ownership lookup, change detection,
reorder-event write, cache invalidation) without a database by mocking the
repository and mutation boundaries.
"""

from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from app.services import queue_service
from app.services.errors import InvalidRequestError, NotFoundError


def _make_thread(thread_id: int = 7, queue_position: int = 2) -> SimpleNamespace:
    """Build a minimal thread stand-in carrying the fields the service reads.

    Args:
        thread_id: Thread primary key.
        queue_position: Thread's current queue position.

    Returns:
        A simple namespace with the service-relevant thread fields.
    """
    return SimpleNamespace(id=thread_id, queue_position=queue_position)


def _fake_db() -> AsyncMock:
    """Build a fake async session whose mutation methods record calls.

    Returns:
        An AsyncMock session stand-in.
    """
    return AsyncMock()


async def _patch_service_boundaries(
    monkeypatch: pytest.MonkeyPatch,
    *,
    thread: SimpleNamespace | None,
    before: dict[int, int] | None = None,
    after: dict[int, int] | None = None,
) -> tuple[AsyncMock, AsyncMock, AsyncMock, AsyncMock]:
    """Patch every repository and mutation boundary the service relies on.

    Args:
        monkeypatch: Pytest monkeypatch fixture.
        thread: Owned-thread lookup result (None → not owned).
        before: Position map captured before the mutation.
        after: Position map captured after the mutation.

    Returns:
        Tuple of (mutation mock, add_reorder_event mock, thread_to_response
        mock, invalidator mock).
    """
    find_owned = AsyncMock(return_value=thread)
    monkeypatch.setattr(queue_service.thread_repository, "find_owned", find_owned)

    if before is not None:
        positions = AsyncMock(side_effect=[before, after])
    else:
        positions = AsyncMock(return_value={})
    monkeypatch.setattr(queue_service.queue_repository, "active_queue_positions", positions)

    add_reorder_event = AsyncMock()
    monkeypatch.setattr(queue_service.queue_repository, "add_reorder_event", add_reorder_event)

    mutation = AsyncMock(return_value={})
    monkeypatch.setattr(queue_service, "_move_to_position", mutation)

    to_response = AsyncMock(return_value={"id": thread.id if thread else None})
    monkeypatch.setattr(queue_service, "thread_to_response", to_response)

    invalidator = AsyncMock(return_value=True)
    monkeypatch.setattr(queue_service, "invalidate_user_view", invalidator)

    return mutation, add_reorder_event, to_response, invalidator


@pytest.mark.asyncio
async def test_move_to_position_records_reorder_event_and_invalidates(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A real position change writes a reorder event and bumps caches."""
    _mutation, add_reorder_event, _to_response, invalidator = await _patch_service_boundaries(
        monkeypatch,
        thread=_make_thread(),
        before={10: 1, 7: 2, 11: 3},
        after={7: 1, 10: 2, 11: 3},
    )

    db = _fake_db()
    service = queue_service.QueueService(db)
    await service.move_to_position(1, 7, 1)

    _mutation.assert_awaited_once_with(7, 1, 1, db)
    add_reorder_event.assert_awaited_once_with(db, 7)
    invalidator.assert_awaited_once_with(1)
    db.commit.assert_awaited_once()


@pytest.mark.asyncio
async def test_move_to_position_noop_skips_mutation(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Moving a thread to its current position never mutates the queue."""
    _mutation, add_reorder_event, _to_response, invalidator = await _patch_service_boundaries(
        monkeypatch,
        thread=_make_thread(queue_position=1),
    )

    service = queue_service.QueueService(_fake_db())
    await service.move_to_position(1, 7, 1)

    _mutation.assert_not_awaited()
    add_reorder_event.assert_not_awaited()
    invalidator.assert_not_awaited()


@pytest.mark.asyncio
async def test_move_to_position_missing_thread_raises_not_found(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A foreign or absent thread maps to the 404 domain error."""
    _mutation, _add_reorder_event, _to_response, invalidator = await _patch_service_boundaries(
        monkeypatch,
        thread=None,
    )

    service = queue_service.QueueService(_fake_db())
    with pytest.raises(NotFoundError):
        await service.move_to_position(1, 999, 3)

    _mutation.assert_not_awaited()
    invalidator.assert_not_awaited()


@pytest.mark.asyncio
async def test_move_to_position_invalid_target_raises_invalid_request(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """An out-of-range target position surfaces as a 400-mapped error."""
    _mutation, _add_reorder_event, _to_response, invalidator = await _patch_service_boundaries(
        monkeypatch,
        thread=_make_thread(),
        before={10: 1, 7: 2, 11: 3},
        after={10: 1, 7: 2, 11: 3},
    )

    async def _raise_value_error(*_args, **_kwargs):
        raise ValueError("Position 9 is out of range. Maximum position is 3.")

    monkeypatch.setattr(queue_service, "_move_to_position", _raise_value_error)

    service = queue_service.QueueService(_fake_db())
    with pytest.raises(InvalidRequestError, match="Position 9 is out of range"):
        await service.move_to_position(1, 7, 9)

    invalidator.assert_not_awaited()


@pytest.mark.asyncio
async def test_move_to_front_delegates_to_front_mutation(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Move-to-front uses the front mutation and records a reorder event."""
    thread = _make_thread(queue_position=3)
    find_owned = AsyncMock(return_value=thread)
    monkeypatch.setattr(queue_service.thread_repository, "find_owned", find_owned)
    monkeypatch.setattr(
        queue_service.queue_repository,
        "active_queue_positions",
        AsyncMock(side_effect=[{10: 1, 7: 3, 11: 2}, {7: 1, 10: 3, 11: 2}]),
    )
    add_reorder_event = AsyncMock()
    monkeypatch.setattr(queue_service.queue_repository, "add_reorder_event", add_reorder_event)
    front_mutation = AsyncMock(return_value={})
    monkeypatch.setattr(queue_service, "_move_to_front", front_mutation)
    monkeypatch.setattr(
        queue_service, "thread_to_response", AsyncMock(return_value={"id": 7})
    )
    invalidator = AsyncMock(return_value=True)
    monkeypatch.setattr(queue_service, "invalidate_user_view", invalidator)

    db = _fake_db()
    service = queue_service.QueueService(db)
    await service.move_to_front(1, 7)

    front_mutation.assert_awaited_once_with(7, 1, db)
    add_reorder_event.assert_awaited_once_with(db, 7)
    invalidator.assert_awaited_once_with(1)


@pytest.mark.asyncio
async def test_move_to_back_uses_back_mutation(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Move-to-back delegates to the back mutation and records the event."""
    thread = _make_thread(queue_position=1)
    find_owned = AsyncMock(return_value=thread)
    monkeypatch.setattr(queue_service.thread_repository, "find_owned", find_owned)
    monkeypatch.setattr(
        queue_service.queue_repository,
        "active_queue_positions",
        AsyncMock(side_effect=[{7: 1, 10: 2}, {7: 3, 10: 1, 11: 2}]),
    )
    add_reorder_event = AsyncMock()
    monkeypatch.setattr(queue_service.queue_repository, "add_reorder_event", add_reorder_event)
    back_mutation = AsyncMock(return_value={})
    monkeypatch.setattr(queue_service, "_move_to_back", back_mutation)
    monkeypatch.setattr(
        queue_service, "thread_to_response", AsyncMock(return_value={"id": 7})
    )
    invalidator = AsyncMock(return_value=True)
    monkeypatch.setattr(queue_service, "invalidate_user_view", invalidator)

    db = _fake_db()
    service = queue_service.QueueService(db)
    await service.move_to_back(1, 7)

    back_mutation.assert_awaited_once_with(7, 1, db)
    add_reorder_event.assert_awaited_once_with(db, 7)
    invalidator.assert_awaited_once_with(1)


@pytest.mark.asyncio
async def test_shuffle_invalidates_only_when_order_changes(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Shuffle bumps caches only when the random reorder actually moved rows."""
    monkeypatch.setattr(
        queue_service.queue_repository,
        "active_queue_positions",
        AsyncMock(side_effect=[{10: 1, 7: 2}, {7: 1, 10: 2}]),
    )
    shuffle = AsyncMock()
    monkeypatch.setattr(queue_service, "_shuffle_queue", shuffle)
    invalidator = AsyncMock(return_value=True)
    monkeypatch.setattr(queue_service, "invalidate_user_view", invalidator)

    service = queue_service.QueueService(_fake_db())
    await service.shuffle(1)
    invalidator.assert_awaited_once_with(1)

    monkeypatch.setattr(
        queue_service.queue_repository,
        "active_queue_positions",
        AsyncMock(return_value={10: 1, 7: 2}),
    )
    await service.shuffle(1)
    assert invalidator.await_count == 1