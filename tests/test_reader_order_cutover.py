"""Regression coverage for the guarded raw-Dependency Roll cutover."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import cast

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
    assert blocked["remaining_reading_plan_order_dependency_ids"] == [reader_order.id]
    assert blocked["active_standalone_prerequisite_dependency_ids"] == [standalone.id]

    # Marking the source read only dormants the edge; semantic cutover still fails.
    issues[0].status = "read"
    issues[0].read_at = datetime.now(UTC)
    await async_db.commit()
    dormant = await reader_order_cutover.build_reader_order_cutover_audit(
        async_db,
        user_id=user_id,
    )
    assert dormant["release_condition_met"] is False
    assert dormant["runtime_cutover_safe"] is False
    assert dormant["active_reading_plan_order_dependency_ids"] == []
    assert dormant["remaining_reading_plan_order_dependency_ids"] == [reader_order.id]
    assert dormant["active_standalone_prerequisite_dependency_ids"] == [standalone.id]

    await async_db.execute(delete(Dependency).where(Dependency.id == reader_order.id))
    await async_db.commit()
    clean = await reader_order_cutover.build_reader_order_cutover_audit(
        async_db,
        user_id=user_id,
    )
    assert clean["release_condition_met"] is True
    assert clean["runtime_cutover_safe"] is True
    assert clean["remaining_reading_plan_order_dependency_ids"] == []
    assert clean["active_standalone_prerequisite_dependency_ids"] == [standalone.id]
    assert clean["remaining_standalone_prerequisite_dependency_ids"] == [standalone.id]
    assert clean["legacy_only_blocked_thread_ids"] == []


@pytest.mark.asyncio
async def test_cutover_rejects_dormant_standalone_with_drifted_mirror(
    async_db: AsyncSession,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A linked rule with wrong source/target/item_read semantics fails cutover."""
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

    await async_db.execute(delete(Dependency).where(Dependency.id == reader_order.id))
    # Dormant the standalone source so point-in-time Roll looks fine.
    issues[2].status = "read"
    issues[2].read_at = datetime.now(UTC)
    drifted = await async_db.scalar(
        select(ContinuityRule).where(
            ContinuityRule.legacy_dependency_id == standalone.id
        )
    )
    assert drifted is not None
    # Keep the linkage ID but break the mirrored edge semantics.
    drifted.source_id = issues[0].id
    drifted.target_id = issues[1].id
    drifted.satisfaction_type = "converged"
    drifted.convergence_targets = [{"type": "issue", "id": issues[0].id}]
    await async_db.commit()

    audit = await reader_order_cutover.build_reader_order_cutover_audit(
        async_db,
        user_id=user_id,
    )
    assert audit["release_condition_met"] is True
    assert audit["runtime_cutover_safe"] is False
    assert audit["standalone_dependencies_missing_continuity_mirror"] == []
    assert audit["standalone_dependencies_with_mismatched_continuity_mirror"] == [
        standalone.id
    ]
    assert standalone.id in cast(
        list[int],
        audit["active_standalone_dependencies_missing_continuity_mirror"],
    )


@pytest.mark.asyncio
async def test_cutover_fails_when_sequence_order_contributes_to_eligibility(
    async_db: AsyncSession,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """sequence_order blockers cannot clear legacy_only or green the cutover."""
    from app.models.dependency_group import DependencyGroup, DependencyGroupMembership

    user_id, threads, issues, reader_order, standalone = await _two_dependency_families(
        async_db
    )
    await async_db.execute(delete(Dependency).where(Dependency.id == reader_order.id))
    group = DependencyGroup(user_id=user_id, name="Forbidden sequence order")
    async_db.add(group)
    await async_db.flush()
    async_db.add_all(
        [
            DependencyGroupMembership(
                group_id=group.id,
                issue_id=issues[2].id,
                sequence_order=1,
            ),
            DependencyGroupMembership(
                group_id=group.id,
                issue_id=issues[3].id,
                sequence_order=2,
            ),
        ]
    )
    await async_db.commit()

    monkeypatch.setattr(reader_order_cutover, "_load_step14_index", lambda: {})
    monkeypatch.setattr(
        reader_order_cutover,
        "_explicit_classifications",
        lambda _index: (
            {standalone.id: "standalone_prerequisite"},
            {},
        ),
    )
    monkeypatch.setattr(
        reader_order_cutover,
        "_generated_reader_order_patterns",
        lambda _index: (),
    )

    audit = await reader_order_cutover.build_reader_order_cutover_audit(
        async_db,
        user_id=user_id,
    )
    assert audit["release_condition_met"] is True
    sequence_blocked = audit["sequence_order_blocked_thread_ids"]
    assert isinstance(sequence_blocked, list)
    assert threads[3].id in sequence_blocked
    assert audit["runtime_cutover_safe"] is False


@pytest.mark.asyncio
async def test_runtime_switch_uses_only_canonical_dependencies_for_roll_eligibility(
    async_db: AsyncSession,
) -> None:
    """Deleting ContinuityRule mirrors must not alter Dependency-authority blocking."""
    user_id, threads, _issues, reader_order, standalone = await _two_dependency_families(
        async_db
    )
    linked_rules = list(
        (
            await async_db.scalars(
                select(ContinuityRule).where(
                    ContinuityRule.legacy_dependency_id.in_(
                        [reader_order.id, standalone.id]
                    )
                )
            )
        ).all()
    )
    assert len(linked_rules) == 2
    await async_db.execute(
        delete(ContinuityRule).where(
            ContinuityRule.id.in_([rule.id for rule in linked_rules])
        )
    )
    await async_db.commit()

    # ContinuityRule mirrors are inert triggers; canonical Dependency rows are
    # the only authority for Roll eligibility.
    blocked = await dependencies._get_blocked_thread_ids_uncached(user_id, async_db)
    assert threads[1].id in blocked
    assert threads[3].id in blocked

    await dependencies.refresh_user_blocked_status(user_id, async_db)
    await async_db.commit()
    roll_ids = {thread.id for thread in await get_roll_pool(user_id, async_db)}
    assert threads[1].id not in roll_ids
    assert threads[3].id not in roll_ids
