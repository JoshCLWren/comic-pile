"""Focused tests for blocked-roll recovery guidance."""

from unittest.mock import AsyncMock

import pytest

from app.continuity_chains import ContinuityTraversalNode, ContinuityTraversalResult
from app.roll_recovery import build_roll_recovery
from app.schemas.continuity_readiness import ContinuityBlocker


@pytest.mark.asyncio
async def test_roll_recovery_is_absent_without_pending_roll(monkeypatch: pytest.MonkeyPatch) -> None:
    resolver = AsyncMock()
    monkeypatch.setattr("app.roll_recovery.resolve_continuity_chains", resolver)

    recovery = await build_roll_recovery(
        AsyncMock(),
        user_id=1,
        pending_thread_id=None,
        pending_thread_title=None,
    )

    assert recovery is None
    resolver.assert_not_awaited()


@pytest.mark.asyncio
async def test_roll_recovery_is_absent_when_pending_roll_is_readable(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    resolver = AsyncMock(
        return_value=ContinuityTraversalResult(
            node_type="thread",
            node_id=42,
            evaluated_issue_id=420,
            direct_blockers=(),
            chains=(),
            readable_prerequisites=(),
            diagnostics=(),
        )
    )
    monkeypatch.setattr("app.roll_recovery.resolve_continuity_chains", resolver)

    recovery = await build_roll_recovery(
        AsyncMock(),
        user_id=1,
        pending_thread_id=42,
        pending_thread_title="Original Roll",
    )

    assert recovery is None
    resolver.assert_awaited_once()


@pytest.mark.asyncio
async def test_roll_recovery_preserves_original_and_recommends_readable_leaf(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    blocker = ContinuityBlocker(
        rule_id=7,
        source_type="issue",
        source_id=100,
        source_label="Prerequisite #1",
        satisfaction_type="item_read",
        causing_issue_ids=[100],
    )
    readable_leaf = ContinuityTraversalNode(
        node_type="issue",
        node_id=90,
        label="Earlier Series #3",
        is_readable=True,
    )
    resolver = AsyncMock(
        return_value=ContinuityTraversalResult(
            node_type="thread",
            node_id=42,
            evaluated_issue_id=420,
            direct_blockers=(blocker,),
            chains=((readable_leaf,),),
            readable_prerequisites=(readable_leaf,),
            diagnostics=(),
        )
    )
    monkeypatch.setattr("app.roll_recovery.resolve_continuity_chains", resolver)

    recovery = await build_roll_recovery(
        AsyncMock(),
        user_id=1,
        pending_thread_id=42,
        pending_thread_title="Original Roll",
    )

    assert recovery is not None
    assert recovery.original_thread_id == 42
    assert recovery.original_thread_title == "Original Roll"
    assert recovery.direct_blockers == [blocker]
    assert recovery.readable_prerequisites[0].node_id == 90
    assert recovery.readable_prerequisites[0].label == "Earlier Series #3"
    resolver.assert_awaited_once_with(
        pytest.ANY,
        user_id=1,
        node_type="thread",
        node_id=42,
    )
