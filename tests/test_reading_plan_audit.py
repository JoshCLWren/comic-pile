"""Audit and deterministic reconciliation of Reading Plan membership duplicates.

``uq_reading_plan_issue_plan_issue`` makes repeated membership unpersistable, but
rows written before that constraint existed can still violate it. These tests
cover the tooling that reports those rows and collapses them without guessing
between conflicting reader state.
"""

from datetime import UTC, datetime

import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.continuity_plan import ContinuityPlan
from app.models.issue import Issue
from app.models.reading_plan_membership import (
    ReadingPlanIssue,
    ReadingPlanSource,
    ReadingPlanSourcePlacement,
)
from app.models.thread import Thread
from app.repositories import reading_plan_repository
from app.services import reading_plan_audit
from tests.conftest import get_or_create_user_async

CONSTRAINT = "uq_reading_plan_issue_plan_issue"


async def _make_issue(db: AsyncSession, *, user_id: int, suffix: str) -> Issue:
    """Create one owned Issue for Reading Plan membership audit tests."""
    thread = Thread(
        title=f"Audit plan {suffix}",
        format="comic",
        issues_remaining=1,
        queue_position=1,
        status="active",
        user_id=user_id,
        total_issues=1,
        reading_progress="unstarted",
        created_at=datetime.now(UTC),
    )
    db.add(thread)
    await db.flush()
    issue = Issue(thread_id=thread.id, issue_number="1", position=1, status="unread")
    db.add(issue)
    await db.flush()
    return issue


async def _make_plan(db: AsyncSession, *, user_id: int, name: str) -> ContinuityPlan:
    """Persist an empty plan to own membership rows."""
    plan = ContinuityPlan(
        user_id=user_id,
        name=name,
        ordering_mode="informational",
        nodes_json=[],
        lanes_json=[],
    )
    db.add(plan)
    await db.flush()
    return plan


async def _insert_legacy_duplicates(
    db: AsyncSession,
    *,
    plan_id: int,
    issue_id: int,
    occurrences: list[tuple[str, int, str | None]],
) -> None:
    """Insert membership rows that predate the uniqueness constraint.

    The constraint is dropped inside the per-test transaction so legacy state
    can be reproduced; the fixture rollback restores it for every other test.
    """
    await db.execute(text(f"ALTER TABLE reading_plan_issues DROP CONSTRAINT {CONSTRAINT}"))
    db.add_all(
        [
            ReadingPlanIssue(
                plan_id=plan_id,
                occurrence_id=occurrence_id,
                issue_id=issue_id,
                lane_id="main",
                display_position=position,
                label=label,
            )
            for occurrence_id, position, label in occurrences
        ]
    )
    await db.flush()


@pytest.mark.asyncio
async def test_audit_reports_a_clean_plan(async_db: AsyncSession) -> None:
    """A plan holding each Issue once satisfies the invariant."""
    user = await get_or_create_user_async(async_db)
    issue = await _make_issue(async_db, user_id=user.id, suffix="clean")
    plan = await _make_plan(async_db, user_id=user.id, name="Clean")
    async_db.add(
        ReadingPlanIssue(
            plan_id=plan.id,
            occurrence_id="only",
            issue_id=issue.id,
            lane_id="main",
            display_position=0,
        )
    )
    await async_db.flush()

    result = await reading_plan_audit.audit_reading_plan_duplicate_memberships(
        async_db, plan_id=plan.id
    )

    assert result.is_clean is True
    assert result.total_duplicate_issues == 0


@pytest.mark.asyncio
async def test_audit_detects_and_reconciles_legacy_duplicates(
    async_db: AsyncSession,
) -> None:
    """Audit finds pre-constraint duplicates and reconciliation collapses them."""
    user = await get_or_create_user_async(async_db)
    issue = await _make_issue(async_db, user_id=user.id, suffix="legacy")
    plan = await _make_plan(async_db, user_id=user.id, name="Legacy")
    await _insert_legacy_duplicates(
        async_db,
        plan_id=plan.id,
        issue_id=issue.id,
        occurrences=[("second", 1, "Recap"), ("first", 0, "Primary"), ("third", 2, None)],
    )

    report = await reading_plan_audit.audit_plan_duplicate_memberships(
        async_db, plan_id=plan.id
    )
    assert report.total_duplicate_issues == 1
    assert report.total_extra_occurrences == 2
    duplicate = report.duplicates[0]
    assert duplicate.count == 3
    assert duplicate.occurrence_ids == ("first", "second", "third")
    assert duplicate.has_conflicts is True
    assert set(duplicate.conflicting_fields) == {"label"}

    plan_of_actions = reading_plan_audit.create_reconciliation_plan(report)
    assert plan_of_actions.primary_occurrence_ids == {issue.id: "first"}
    assert sorted(plan_of_actions.removal_occurrence_ids) == ["second", "third"]

    await reading_plan_audit.apply_reconciliation_plan(async_db, plan=plan_of_actions)

    rows = await reading_plan_repository.list_plan_issues(async_db, plan_id=plan.id)
    assert [row.occurrence_id for row in rows] == ["first"]
    assert rows[0].label == "Primary"

    verified = await reading_plan_audit.audit_reading_plan_duplicate_memberships(
        async_db, plan_id=plan.id
    )
    assert verified.is_clean is True


@pytest.mark.asyncio
async def test_reconciliation_repoints_provenance_onto_the_survivor(
    async_db: AsyncSession,
) -> None:
    """Import provenance follows the collapse instead of being orphaned."""
    user = await get_or_create_user_async(async_db)
    issue = await _make_issue(async_db, user_id=user.id, suffix="provenance")
    plan = await _make_plan(async_db, user_id=user.id, name="Provenance")
    await _insert_legacy_duplicates(
        async_db,
        plan_id=plan.id,
        issue_id=issue.id,
        occurrences=[("first", 0, None), ("second", 1, None)],
    )
    snapshot = ReadingPlanSource(plan_id=plan.id, raw_source_path="cbl:one")
    async_db.add(snapshot)
    await async_db.flush()
    async_db.add_all(
        [
            ReadingPlanSourcePlacement(
                plan_id=plan.id,
                occurrence_id="first",
                plan_source_id=snapshot.id,
                source_position=1,
            ),
            ReadingPlanSourcePlacement(
                plan_id=plan.id,
                occurrence_id="second",
                plan_source_id=snapshot.id,
                source_position=7,
            ),
        ]
    )
    await async_db.flush()

    report = await reading_plan_audit.audit_plan_duplicate_memberships(
        async_db, plan_id=plan.id
    )
    await reading_plan_audit.apply_reconciliation_plan(
        async_db, plan=reading_plan_audit.create_reconciliation_plan(report)
    )

    placements = await reading_plan_repository.list_plan_source_placements(
        async_db, plan_id=plan.id
    )
    surviving = {placement.occurrence_id for placement in placements}
    assert surviving == {"first"}
    assert sorted(placement.source_position for placement in placements) == [1, 7]
    sources = await reading_plan_repository.list_plan_sources(async_db, plan_id=plan.id)
    assert [source.raw_source_path for source in sources] == ["cbl:one"]


@pytest.mark.asyncio
async def test_reconciliation_drops_provenance_the_survivor_already_owns(
    async_db: AsyncSession,
) -> None:
    """A re-pointed placement never duplicates provenance the survivor owns."""
    user = await get_or_create_user_async(async_db)
    issue = await _make_issue(async_db, user_id=user.id, suffix="collision")
    plan = await _make_plan(async_db, user_id=user.id, name="Collision")
    await _insert_legacy_duplicates(
        async_db,
        plan_id=plan.id,
        issue_id=issue.id,
        occurrences=[("first", 0, None), ("second", 1, None)],
    )

    snapshot = ReadingPlanSource(plan_id=plan.id, raw_source_path="cbl:one")
    async_db.add(snapshot)
    await async_db.flush()
    async_db.add_all(
        [
            ReadingPlanSourcePlacement(
                plan_id=plan.id,
                occurrence_id="first",
                plan_source_id=snapshot.id,
                source_position=3,
            ),
            ReadingPlanSourcePlacement(
                plan_id=plan.id,
                occurrence_id="second",
                plan_source_id=snapshot.id,
                source_position=3,
            ),
        ]
    )
    await async_db.flush()

    report = await reading_plan_audit.audit_plan_duplicate_memberships(
        async_db, plan_id=plan.id
    )
    await reading_plan_audit.apply_reconciliation_plan(
        async_db, plan=reading_plan_audit.create_reconciliation_plan(report)
    )

    placements = await reading_plan_repository.list_plan_source_placements(
        async_db, plan_id=plan.id
    )
    assert [(p.occurrence_id, p.source_position) for p in placements] == [("first", 3)]


@pytest.mark.asyncio
async def test_conflicting_duplicates_are_reported_not_guessed(
    async_db: AsyncSession,
) -> None:
    """Disagreeing reader state is surfaced and skipped by default."""
    user = await get_or_create_user_async(async_db)
    issue = await _make_issue(async_db, user_id=user.id, suffix="conflict")
    plan = await _make_plan(async_db, user_id=user.id, name="Conflict")
    await _insert_legacy_duplicates(
        async_db,
        plan_id=plan.id,
        issue_id=issue.id,
        occurrences=[("first", 0, "Primary"), ("second", 1, "Recap")],
    )

    result = await reading_plan_audit.reconcile_reading_plan_duplicate_memberships(
        async_db, plan_id=plan.id
    )
    assert result.reports[0].conflicting_issue_ids == (issue.id,)
    rows = await reading_plan_repository.list_plan_issues(async_db, plan_id=plan.id)
    assert sorted(row.occurrence_id for row in rows) == ["first", "second"]

    forced = await reading_plan_audit.reconcile_reading_plan_duplicate_memberships(
        async_db, plan_id=plan.id, allow_conflicts=True
    )
    assert forced.total_extra_occurrences == 1
    rows = await reading_plan_repository.list_plan_issues(async_db, plan_id=plan.id)
    assert [row.occurrence_id for row in rows] == ["first"]


@pytest.mark.asyncio
async def test_reconciliation_audit_covers_every_plan(async_db: AsyncSession) -> None:
    """The plan-wide audit reports only the plans that violate the invariant."""
    user = await get_or_create_user_async(async_db)
    clean_issue = await _make_issue(async_db, user_id=user.id, suffix="wide-clean")
    legacy_issue = await _make_issue(async_db, user_id=user.id, suffix="wide-legacy")
    clean_plan = await _make_plan(async_db, user_id=user.id, name="Wide Clean")
    legacy_plan = await _make_plan(async_db, user_id=user.id, name="Wide Legacy")
    async_db.add(
        ReadingPlanIssue(
            plan_id=clean_plan.id,
            occurrence_id="only",
            issue_id=clean_issue.id,
            lane_id="main",
            display_position=0,
        )
    )
    await _insert_legacy_duplicates(
        async_db,
        plan_id=legacy_plan.id,
        issue_id=legacy_issue.id,
        occurrences=[("first", 0, None), ("second", 1, None)],
    )

    result = await reading_plan_audit.audit_reading_plan_duplicate_memberships(async_db)

    assert [report.plan_id for report in result.reports] == [legacy_plan.id]


@pytest.mark.asyncio
async def test_migration_constraint_is_present(async_db: AsyncSession) -> None:
    """The database itself refuses a repeated canonical Issue membership."""
    names = (
        await async_db.execute(
            text(
                "SELECT conname FROM pg_constraint "
                "WHERE conrelid = 'reading_plan_issues'::regclass AND contype = 'u'"
            )
        )
    ).scalars().all()
    assert CONSTRAINT in names