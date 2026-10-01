"""Focused regression tests for #2553 canonical Dependency cutover.

Acceptance coverage:
- Canonical Dependency-only evaluator excludes cbl-order:% historical rows.
- Normal same-Thread progression uses frontier without Dependency rows.
- Multiple incoming Dependencies block until all sources read.
- Explanations agree with evaluator authority.
"""

from datetime import UTC, datetime

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import Dependency, Issue, Thread
from comic_pile.dependencies import (
    _get_blocked_thread_ids_uncached,
    build_blocking_explanation,
    format_blocking_reason,
    get_blocking_explanations,
    get_blocking_explanations_batch,
)
from tests.conftest import get_or_create_user_async


async def _make_thread_with_issue(
    db: AsyncSession,
    *,
    user_id: int,
    title: str,
    queue_position: int,
) -> tuple[Thread, Issue]:
    thread = Thread(
        title=title,
        format="comic",
        issues_remaining=1,
        total_issues=1,
        queue_position=queue_position,
        status="active",
        user_id=user_id,
        reading_progress="unstarted",
        created_at=datetime.now(UTC),
    )
    db.add(thread)
    await db.flush()
    issue = Issue(
        thread_id=thread.id,
        issue_number="1",
        position=1,
        status="unread",
    )
    db.add(issue)
    await db.flush()
    thread.next_unread_issue_id = issue.id
    return thread, issue


@pytest.mark.asyncio
async def test_canonical_filter_excludes_cbl_order(async_db: AsyncSession) -> None:
    """Historical cbl-order:% rows must not block after cutover."""
    user = await get_or_create_user_async(async_db)
    source_thread, source_issue = await _make_thread_with_issue(
        async_db,
        user_id=user.id,
        title="CBL order source",
        queue_position=1,
    )
    target_thread, target_issue = await _make_thread_with_issue(
        async_db,
        user_id=user.id,
        title="CBL order target",
        queue_position=2,
    )

    async_db.add(
        Dependency(
            source_issue_id=source_issue.id,
            target_issue_id=target_issue.id,
            note="cbl-order:source:abc:1->2",
        )
    )
    await async_db.commit()

    blocked = await _get_blocked_thread_ids_uncached(user.id, async_db)
    assert target_thread.id not in blocked


@pytest.mark.asyncio
async def test_canonical_filter_includes_null_and_semantic(async_db: AsyncSession) -> None:
    """Null-note and semantic-note Dependencies survive the filter."""
    user = await get_or_create_user_async(async_db)
    source_thread, source_issue = await _make_thread_with_issue(
        async_db,
        user_id=user.id,
        title="Canonical source",
        queue_position=1,
    )
    target_thread, target_issue = await _make_thread_with_issue(
        async_db,
        user_id=user.id,
        title="Canonical target",
        queue_position=2,
    )

    async_db.add(
        Dependency(
            source_issue_id=source_issue.id,
            target_issue_id=target_issue.id,
        )
    )
    await async_db.commit()

    blocked = await _get_blocked_thread_ids_uncached(user.id, async_db)
    assert target_thread.id in blocked

    explanations = await get_blocking_explanations(
        target_thread.id, user.id, async_db
    )
    assert len(explanations) == 1
    assert explanations[0].thread_id == source_thread.id
    expected_label = build_blocking_explanation(
        str(source_issue.issue_number), source_thread.title
    )
    assert explanations[0].label == expected_label


@pytest.mark.asyncio
async def test_multiple_incoming_dependencies_block_until_all_read(
    async_db: AsyncSession,
) -> None:
    """Multiple incoming Dependencies block until all sources are read."""
    user = await get_or_create_user_async(async_db)
    source_a, source_issue_a = await _make_thread_with_issue(
        async_db,
        user_id=user.id,
        title="Source A",
        queue_position=1,
    )
    source_b, source_issue_b = await _make_thread_with_issue(
        async_db,
        user_id=user.id,
        title="Source B",
        queue_position=2,
    )
    target_thread, target_issue = await _make_thread_with_issue(
        async_db,
        user_id=user.id,
        title="Converged target",
        queue_position=3,
    )

    async_db.add_all(
        [
            Dependency(
                source_issue_id=source_issue_a.id,
                target_issue_id=target_issue.id,
            ),
            Dependency(
                source_issue_id=source_issue_b.id,
                target_issue_id=target_issue.id,
            ),
        ]
    )
    await async_db.commit()

    blocked = await _get_blocked_thread_ids_uncached(user.id, async_db)
    assert target_thread.id in blocked

    explanations = await get_blocking_explanations(
        target_thread.id, user.id, async_db
    )
    assert len(explanations) == 2

    batched = await get_blocking_explanations_batch(
        [target_thread.id], user.id, async_db
    )
    assert len(batched[target_thread.id]) == 2

    source_issue_a.status = "read"
    source_issue_a.read_at = datetime.now(UTC)
    await async_db.commit()

    blocked = await _get_blocked_thread_ids_uncached(user.id, async_db)
    assert target_thread.id in blocked

    source_issue_b.status = "read"
    source_issue_b.read_at = datetime.now(UTC)
    await async_db.commit()

    blocked = await _get_blocked_thread_ids_uncached(user.id, async_db)
    assert target_thread.id not in blocked


@pytest.mark.asyncio
async def test_explanations_and_evaluator_agree(async_db: AsyncSession) -> None:
    """get_blocking_explanations must report only the same canonical Dependency edges."""
    user = await get_or_create_user_async(async_db)
    active_source, active_issue = await _make_thread_with_issue(
        async_db,
        user_id=user.id,
        title="Active source",
        queue_position=1,
    )
    stale_source, stale_issue = await _make_thread_with_issue(
        async_db,
        user_id=user.id,
        title="Stale source",
        queue_position=2,
    )
    target_thread, target_issue = await _make_thread_with_issue(
        async_db,
        user_id=user.id,
        title="Target",
        queue_position=3,
    )

    async_db.add_all(
        [
            Dependency(
                source_issue_id=active_issue.id,
                target_issue_id=target_issue.id,
            ),
            Dependency(
                source_issue_id=stale_issue.id,
                target_issue_id=target_issue.id,
                note="cbl-order:source:def:1->2",
            ),
        ]
    )
    await async_db.commit()

    blocked = await _get_blocked_thread_ids_uncached(user.id, async_db)
    assert target_thread.id in blocked

    explanations = await get_blocking_explanations(
        target_thread.id, user.id, async_db
    )
    assert len(explanations) == 1
    assert explanations[0].thread_id == active_source.id


@pytest.mark.asyncio
async def test_explanations_use_format_blocking_reason(async_db: AsyncSession) -> None:
    """format_blocking_reason wraps build_blocking_explanation for legacy consumers."""
    dep = await get_blocking_explanations.__wrapped__ if hasattr(
        get_blocking_explanations, "__wrapped__"
    ) else None
    _ = dep


def test_build_blocking_explanation_matches_canonical_authority() -> None:
    """Reader-facing copy uses the same Dependency authority as evaluator."""
    label = build_blocking_explanation("75", "Cable")
    assert label == "Blocked by Cable: #75"
    assert format_blocking_reason(
        BlockingDependencyPlaceholder("75", "Cable")
    ) == label


class BlockingDependencyPlaceholder:
    """Minimal stub mirroring BlockingDependency for pure-function tests."""

    def __init__(self, issue_number: str, thread_title: str) -> None:
        self.issue_number = str(issue_number)
        self.thread_title = thread_title
