"""Unit test for list_plan_threads sort order without a database."""

import pytest
from unittest.mock import MagicMock

from app.repositories.reading_plan_repository import list_plan_threads


class FakeResult:
    """Fake SQLAlchemy result wrapper returning canned rows."""

    def __init__(self, rows):
        """Store canned rows for later retrieval."""
        self._rows = rows

    def all(self):
        """Return the canned rows."""
        return self._rows


class FakeSession:
    """Fake async session that returns canned membership then node rows."""

    def __init__(self, membership_rows, node_rows):
        """Store canned membership and node row sets."""
        self._membership_rows = membership_rows
        self._node_rows = node_rows
        self.call_count = 0

    async def execute(self, stmt):
        """Return membership rows on first call, node rows on second."""
        self.call_count += 1
        if self.call_count == 1:
            return FakeResult(self._membership_rows)
        return FakeResult(self._node_rows)


def _row(thread_id, thread_title, position=None):
    """Build a fake SQLAlchemy Row with attribute access."""
    row = MagicMock()
    row.thread_id = thread_id
    row.thread_title = thread_title
    if position is not None:
        row.position = position
    return row


@pytest.mark.asyncio
async def test_node_only_threads_follow_membership_threads():
    """Node-only threads (position=0) sort after membership threads."""
    # Membership: B Thread at position 2, A Thread at position 1
    membership_rows = [
        _row(1, "B Thread", 2),
        _row(2, "A Thread", 1),
    ]
    # Node-only: C Thread (no membership row)
    node_rows = [_row(3, "C Thread")]

    session = FakeSession(membership_rows, node_rows)
    threads = await list_plan_threads(
        session, plan_id=1, extra_thread_ids=(3,)
    )

    assert [t.thread_id for t in threads] == [2, 1, 3]
    assert [t.position for t in threads] == [1, 2, 0]
    assert [t.thread_title for t in threads] == ["A Thread", "B Thread", "C Thread"]


@pytest.mark.asyncio
async def test_node_only_threads_sort_by_title_among_themselves():
    """Multiple node-only threads follow membership threads in title order."""
    membership_rows = [_row(1, "M Thread", 1)]
    node_rows = [_row(3, "Z Thread"), _row(2, "A Thread")]

    session = FakeSession(membership_rows, node_rows)
    threads = await list_plan_threads(
        session, plan_id=1, extra_thread_ids=(3, 2)
    )

    assert [t.thread_id for t in threads] == [1, 2, 3]
    assert [t.position for t in threads] == [1, 0, 0]
    assert [t.thread_title for t in threads] == ["M Thread", "A Thread", "Z Thread"]


@pytest.mark.asyncio
async def test_extra_thread_ids_already_in_membership_are_not_duplicated():
    """Thread IDs already in membership are not re-added as node-only."""
    membership_rows = [_row(1, "A Thread", 1), _row(2, "B Thread", 2)]
    node_rows = []

    session = FakeSession(membership_rows, node_rows)
    threads = await list_plan_threads(
        session, plan_id=1, extra_thread_ids=(1, 2)
    )

    assert len(threads) == 2
    assert [t.thread_id for t in threads] == [1, 2]
