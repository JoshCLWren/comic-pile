"""Regression coverage for the guarded raw-Dependency Roll cutover."""

from __future__ import annotations

from datetime import UTC, datetime
from types import SimpleNamespace

import pytest
from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.continuity_rule import ContinuityRule
from app.models.dependency import Dependency
from app.models.issue import Issue
from app.models.thread import Thread
from app.services import reader_order_cutover
from comic_pile import dependencies
from comic_pile.queue import get_roll_pool
from tests.conftest import get_or_create_user_async


async def _thread_issue(
    db: AsyncSession,
    *,
    user_id: int,
    title: str,
    queue_position: int,
) -> tuple[Thread, Issue]:
    thread = Thread(
        user_id=user_id,
        title=title,
        format="comic",
        queue_position=queue_position,
        status="active",
        total_issues=1,
        issues_remaining=1,
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


async def _two_dependency_families(
    db: AsyncSession,
) -> tuple[int, list[Thread], list[Issue], Dependency, Dependency]:
    user = await get_or_create_user_async(db)
    rows = [
        await _thread_issue(
            db,
            user_id=user.id,
            title=title,
            queue_position=position,
        )
        for position, title in enumerate(
            ("Reader source", "Reader target", "Prerequisite source", "Prerequisite target"),
            start=1,
        )
    ]
    threads = [row[0] for row in rows]
    issues = [row[1] for row in rows]
    reader_order = Dependency(
        source_issue_id=issues[0].id,
        target_issue_id=issues[1].id,
        note="classified reader order",
    )
    standalone = Dependency(
        source_issue_id=issues[2].id,
        target_issue_id=issues[3].id,
        note="genuine standalone prerequisite",
    )
    db.add_all([reader_order, standalone])
    await db.flush()
    db.add_all(
        [
            ContinuityRule(
                user_id=user.id,
                legacy_dependency_id=dependency.id,
                source_type="issue",
                source_id=dependency.source_issue_id,
                target_type="issue",
                target_id=dependency.target_issue_id,
                satisfaction_type="item_read",
            )
            for dependency in (reader_order, standalone)
        ]
    )
    await db.commit()
    return user.id, threads, issues, reader_order, standalone


@pytest.mark.asyncio
async def test_cutover_audit_requires_reader_order_migration_but_preserves_standalone(
    async_db: AsyncSession,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The release gate clears reader order while accepting mirrored prerequisites."""
    user_id, _threads, issues, reader_order, standalone = await _two_dependency_families(
        async_db
    )
    monkeypatch.setattr(reader_order_cutover, "_load_step14_index", lambda: {})
    monkeypatch.setattr(
        reader_order_cutover,
        "_explicit_classifications",
        lambda _index: (
            {
                reader_order.id: "reading_plan_order",
                standalone.id: "standalone_prerequisite",
            },
            {},
        ),
    )
    monkeypatch.setattr(
        reader_order_cutover,
        "_generated_reader_order_patterns",
        lambda _index: (),
    )

    blocked = await reader_order_cutover.build_reader_order_cutover_audit(
        async_db,
        user_id=user_id,
    )
    assert blocked["release_condition_met"] is False
    assert blocked["runtime_cutover_safe"] is False
    assert blocked["active_reading_plan_order_dependency_ids"] == [reader_order.id]
    assert blocked["active_standalone_prerequisite_dependency_ids"] == [standalone.id]

    issues[0].status = "read"
    issues[0].read_at = datetime.now(UTC)
    await async_db.commit()
    clean = await reader_order_cutover.build_reader_order_cutover_audit(
        async_db,
        user_id=user_id,
    )
    assert clean["release_condition_met"] is True
    assert clean["runtime_cutover_safe"] is True
    assert clean["active_standalone_prerequisite_dependency_ids"] == [standalone.id]
    assert clean["legacy_only_blocked_thread_ids"] == []


@pytest.mark.asyncio
async def test_runtime_switch_uses_only_canonical_rules_for_roll_eligibility(
    async_db: AsyncSession,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Turning off raw blocking ignores debris while canonical prerequisites remain."""
    user_id, threads, _issues, reader_order, _standalone = await _two_dependency_families(
        async_db
    )
    linked_reader_rule = await async_db.scalar(
        select(ContinuityRule).where(
            ContinuityRule.legacy_dependency_id == reader_order.id
        )
    )
    assert linked_reader_rule is not None
    await async_db.execute(
        delete(ContinuityRule).where(ContinuityRule.id == linked_reader_rule.id)
    )
    await async_db.commit()

    monkeypatch.setattr(
        dependencies,
        "get_app_settings",
        lambda: SimpleNamespace(legacy_dependency_blocking_enabled=False),
    )
    blocked = await dependencies._get_blocked_thread_ids_uncached(user_id, async_db)
    assert threads[1].id not in blocked
    assert threads[3].id in blocked

    await dependencies.refresh_user_blocked_status(user_id, async_db)
    await async_db.commit()
    roll_ids = {thread.id for thread in await get_roll_pool(user_id, async_db)}
    assert threads[1].id in roll_ids
    assert threads[3].id not in roll_ids
