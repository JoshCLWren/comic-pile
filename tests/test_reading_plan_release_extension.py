"""Tests for extending Reading Plans with adopted release issues (#3118)."""

from datetime import UTC, datetime

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.continuity_plan import ContinuityPlan
from app.models.external_identity import ExternalIdentity, ThreadExternalSeriesMapping
from app.models.issue import Issue
from app.models.reading_plan_membership import ReadingPlanIssue
from app.models.reading_plan_release_source import ReadingPlanReleaseSource
from app.models.thread import Thread
from app.services.reading_plan_release_extension import extend_plans_with_issue
from tests.conftest import get_or_create_user_async


async def _setup(async_db: AsyncSession, *, username: str) -> tuple[int, int, int, int]:
    user = await get_or_create_user_async(async_db, username)
    plan = ContinuityPlan(
        user_id=user.id, name="P", ordering_mode="informational",
        nodes_json=[], lanes_json=[],
    )
    async_db.add(plan)
    await async_db.flush()
    thread = Thread(
        title="T", format="comic", issues_remaining=1, queue_position=1,
        status="active", user_id=user.id, total_issues=1,
        reading_progress="unstarted", created_at=datetime.now(UTC),
    )
    async_db.add(thread)
    await async_db.flush()
    issue = Issue(thread_id=thread.id, issue_number="1", position=1, status="read")
    async_db.add(issue)
    await async_db.flush()
    identity = ExternalIdentity(
        provider="comicvine", entity_type="series", external_id="100",
        metadata_json={"name": "Vol"},
    )
    async_db.add(identity)
    await async_db.flush()
    async_db.add(ThreadExternalSeriesMapping(
        thread_id=thread.id, external_identity_id=identity.id,
        status="confirmed", evidence_source="test",
    ))
    await async_db.flush()
    source = ReadingPlanReleaseSource(
        plan_id=plan.id, thread_id=thread.id,
        external_identity_id=identity.id, enabled=True,
    )
    async_db.add(source)
    await async_db.flush()
    await async_db.commit()
    return user.id, plan.id, thread.id, source.id


async def _make_issue(async_db: AsyncSession, *, thread_id: int, number: str) -> Issue:
    issue = Issue(thread_id=thread_id, issue_number=number, position=99, status="unread")
    async_db.add(issue)
    await async_db.flush()
    await async_db.commit()
    return issue


@pytest.mark.asyncio
async def test_extends_plan_with_new_issue(async_db: AsyncSession) -> None:
    """A newly adopted issue becomes a plan member."""
    _, plan_id, thread_id, source_id = await _setup(async_db, username="ext1")
    new_issue = await _make_issue(async_db, thread_id=thread_id, number="2")
    result = await extend_plans_with_issue(
        async_db, issue_id=new_issue.id, source_id=source_id,
        store_date=datetime(2024, 1, 15, tzinfo=UTC),
    )
    assert plan_id in result.plans_extended
    # Verify membership row exists.
    rows = (
        await async_db.execute(
            select(ReadingPlanIssue).where(
                ReadingPlanIssue.plan_id == plan_id,
                ReadingPlanIssue.issue_id == new_issue.id,
            )
        )
    ).all()
    assert len(rows) == 1


@pytest.mark.asyncio
async def test_idempotent_on_retry(async_db: AsyncSession) -> None:
    """Re-running does not duplicate membership."""
    _, plan_id, thread_id, source_id = await _setup(async_db, username="ext2")
    new_issue = await _make_issue(async_db, thread_id=thread_id, number="2")
    first = await extend_plans_with_issue(
        async_db, issue_id=new_issue.id, source_id=source_id,
        store_date=datetime(2024, 1, 15, tzinfo=UTC),
    )
    assert plan_id in first.plans_extended
    second = await extend_plans_with_issue(
        async_db, issue_id=new_issue.id, source_id=source_id,
        store_date=datetime(2024, 1, 15, tzinfo=UTC),
    )
    assert plan_id in second.plans_skipped_duplicate
    assert plan_id not in second.plans_extended
