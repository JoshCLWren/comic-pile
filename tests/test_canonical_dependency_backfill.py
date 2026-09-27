"""Regression coverage for the canonical ContinuityRule-to-Dependency backfill.

The migration ``c86400000001`` is the data half of issue #2553: it must persist
every proven hard rule as a canonical Dependency row without touching existing
rows, and it must be safe to re-run.
"""

from __future__ import annotations

import importlib.util
from pathlib import Path
from types import ModuleType

import pytest
from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.continuity_rule import ContinuityRule
from app.models.dependency import Dependency
from app.models.issue import Issue
from app.models.thread import Thread
from tests.conftest import get_or_create_user_async

VERSIONS = Path(__file__).parents[1] / "alembic" / "versions"
BACKFILL_PATH = VERSIONS / "c86400000001_persist_canonical_continuity_dependencies.py"


def _load_migration() -> ModuleType:
    """Load the backfill migration module without running Alembic."""
    spec = importlib.util.spec_from_file_location(
        "canonical_continuity_backfill", BACKFILL_PATH
    )
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.fixture(autouse=True)
def _backfill() -> ModuleType:
    return _load_migration()


async def _run_sql(
    db: AsyncSession,
    statement: str,
) -> None:
    await db.execute(text(statement))


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
async def test_backfill_persists_item_read_and_expands_converged_rules(
    async_db: AsyncSession,
    _backfill: ModuleType,
) -> None:
    """Both production rule forms become canonical incoming Dependency edges."""
    user = await get_or_create_user_async(async_db)
    source_thread, source_issue = await _thread_issue(
        async_db, user_id=user.id, title="Source", queue_position=1
    )
    prereq_a_thread, prereq_a_issue = await _thread_issue(
        async_db, user_id=user.id, title="Prerequisite A", queue_position=2
    )
    prereq_b_thread, prereq_b_issue = await _thread_issue(
        async_db, user_id=user.id, title="Prerequisite B", queue_position=3
    )
    target_thread, target_issue = await _thread_issue(
        async_db, user_id=user.id, title="Target", queue_position=4
    )
    db_only_thread, db_only_issue = await _thread_issue(
        async_db, user_id=user.id, title="Convergence target", queue_position=5
    )
    async_db.add_all(
        [
            ContinuityRule(
                user_id=user.id,
                source_type="issue",
                source_id=source_issue.id,
                target_type="issue",
                target_id=target_issue.id,
                satisfaction_type="item_read",
                note="continuity-plan:21",
            ),
            ContinuityRule(
                user_id=user.id,
                source_type="issue",
                source_id=db_only_issue.id,
                target_type="issue",
                target_id=db_only_issue.id,
                satisfaction_type="converged",
                convergence_targets=[
                    {"type": "issue", "id": prereq_a_issue.id},
                    {"type": "issue", "id": prereq_b_issue.id},
                ],
                note="continuity-plan:31",
            ),
        ]
    )
    await async_db.commit()

    await _run_sql(async_db, _backfill.SUSPEND_MIRRORING_TRIGGER_SQL)
    await _run_sql(async_db, _backfill.PERSIST_ITEM_READ_EDGES_SQL)
    await _run_sql(async_db, _backfill.PERSIST_CONVERGED_EDGES_SQL)
    await _run_sql(async_db, _backfill.RESUME_MIRRORING_TRIGGER_SQL)

    edges = {
        (row.source_issue_id, row.target_issue_id, row.note)
        for row in (await async_db.execute(select(Dependency))).scalars()
    }
    new_edges = {(s, t) for s, t, n in edges if n and n.startswith("canonical-from-rule:")}
    assert (source_issue.id, target_issue.id) in new_edges
    assert (prereq_a_issue.id, db_only_issue.id) in new_edges
    assert (prereq_b_issue.id, db_only_issue.id) in new_edges
    assert len(new_edges) == 3

    # Re-running the backfill must not duplicate anything.
    await _run_sql(async_db, _backfill.SUSPEND_MIRRORING_TRIGGER_SQL)
    await _run_sql(async_db, _backfill.PERSIST_ITEM_READ_EDGES_SQL)
    await _run_sql(async_db, _backfill.PERSIST_CONVERGED_EDGES_SQL)
    await _run_sql(async_db, _backfill.RESUME_MIRRORING_TRIGGER_SQL)
    repeated = {
        (row.source_issue_id, row.target_issue_id)
        for row in (await async_db.execute(select(Dependency))).scalars()
    }
    assert repeated == {(s, t) for s, t, _n in edges}

    # Downgrade removes exactly the rows this migration created.
    await _run_sql(async_db, _backfill.DELETE_CANONICAL_EDGES_SQL)
    remaining = {
        (row.source_issue_id, row.target_issue_id, row.note)
        for row in (await async_db.execute(select(Dependency))).scalars()
    }
    assert remaining == edges - {
        (s, t, n) for s, t, n in edges if n and n.startswith("canonical-from-rule:")
    }
    assert source_thread.id is not None
    assert prereq_a_thread.id is not None
    assert prereq_b_thread.id is not None
    assert target_thread.id is not None


@pytest.mark.asyncio
async def test_backfill_skips_existing_mirrored_cross_user_and_non_production_rules(
    async_db: AsyncSession,
    _backfill: ModuleType,
) -> None:
    """Only missing, single-user, production-shaped hard rules are persisted."""
    user = await get_or_create_user_async(async_db)
    other = await get_or_create_user_async(async_db, username="other_user")
    mirrored_source, mirrored_source_issue = await _thread_issue(
        async_db, user_id=user.id, title="Mirrored source", queue_position=1
    )
    mirrored_target, mirrored_target_issue = await _thread_issue(
        async_db, user_id=user.id, title="Mirrored target", queue_position=2
    )
    compat_source, compat_source_issue = await _thread_issue(
        async_db, user_id=user.id, title="Compat source", queue_position=3
    )
    compat_target, compat_target_issue = await _thread_issue(
        async_db, user_id=user.id, title="Compat target", queue_position=4
    )
    foreign_target, foreign_target_issue = await _thread_issue(
        async_db, user_id=other.id, title="Other user target", queue_position=1
    )
    historical_source, historical_source_issue = await _thread_issue(
        async_db, user_id=user.id, title="Historical source", queue_position=5
    )
    historical_target, historical_target_issue = await _thread_issue(
        async_db, user_id=user.id, title="Historical target", queue_position=6
    )
    async_db.add_all(
        [
            Dependency(
                source_issue_id=mirrored_source_issue.id,
                target_issue_id=mirrored_target_issue.id,
                note="genuine standalone prerequisite",
            ),
            Dependency(
                source_issue_id=historical_source_issue.id,
                target_issue_id=historical_target_issue.id,
                note="cbl-order:group-16:1",
            ),
            ContinuityRule(
                user_id=user.id,
                source_type="issue",
                source_id=compat_source_issue.id,
                target_type="issue",
                target_id=compat_target_issue.id,
                satisfaction_type="all_members_read",
                note="non-production compatibility form",
            ),
            ContinuityRule(
                user_id=user.id,
                source_type="issue",
                source_id=mirrored_source_issue.id,
                target_type="issue",
                target_id=foreign_target_issue.id,
                satisfaction_type="item_read",
                note="cross-user edge must not be persisted",
            ),
        ]
    )
    await async_db.commit()

    await _run_sql(async_db, _backfill.SUSPEND_MIRRORING_TRIGGER_SQL)
    await _run_sql(async_db, _backfill.PERSIST_ITEM_READ_EDGES_SQL)
    await _run_sql(async_db, _backfill.PERSIST_CONVERGED_EDGES_SQL)
    await _run_sql(async_db, _backfill.RESUME_MIRRORING_TRIGGER_SQL)

    rows = list((await async_db.execute(select(Dependency))).scalars())
    canonical = {
        (row.source_issue_id, row.target_issue_id)
        for row in rows
        if row.note and row.note.startswith("canonical-from-rule:")
    }
    assert canonical == set()
    assert {(row.source_issue_id, row.target_issue_id) for row in rows} == {
        (mirrored_source_issue.id, mirrored_target_issue.id),
        (historical_source_issue.id, historical_target_issue.id),
    }
    assert mirrored_source.id is not None
    assert mirrored_target.id is not None
    assert compat_source.id is not None
    assert compat_target.id is not None
    assert foreign_target.id is not None
    assert historical_source.id is not None
    assert historical_target.id is not None


@pytest.mark.asyncio
async def test_backfill_leaves_existing_rule_notes_untouched(
    async_db: AsyncSession,
    _backfill: ModuleType,
) -> None:
    """Suspending the mirroring trigger preserves Reading-Plan rule markers."""
    user = await get_or_create_user_async(async_db)
    _source_thread, source_issue = await _thread_issue(
        async_db, user_id=user.id, title="Noted source", queue_position=1
    )
    _target_thread, target_issue = await _thread_issue(
        async_db, user_id=user.id, title="Noted target", queue_position=2
    )
    rule = ContinuityRule(
        user_id=user.id,
        source_type="issue",
        source_id=source_issue.id,
        target_type="issue",
        target_id=target_issue.id,
        satisfaction_type="item_read",
        note="continuity-plan:77",
    )
    async_db.add(rule)
    await async_db.commit()
    rule_id = rule.id

    await _run_sql(async_db, _backfill.SUSPEND_MIRRORING_TRIGGER_SQL)
    await _run_sql(async_db, _backfill.PERSIST_ITEM_READ_EDGES_SQL)
    await _run_sql(async_db, _backfill.PERSIST_CONVERGED_EDGES_SQL)
    await _run_sql(async_db, _backfill.RESUME_MIRRORING_TRIGGER_SQL)

    stored = await async_db.get(ContinuityRule, rule_id)
    assert stored is not None
    assert stored.note == "continuity-plan:77"
    assert stored.legacy_dependency_id is None
