"""PostgreSQL acceptance coverage for the Step 23A Ultimate Universe dry-run."""

from __future__ import annotations

from datetime import UTC, datetime

import pytest
from sqlalchemy import delete, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.cbl_reference import CBLSource, CBLSourceEntry, CBLSourceList
from app.models.continuity_plan import ContinuityPlan
from app.models.continuity_rule import ContinuityRule
from app.models.dependency import Dependency
from app.models.dependency_group import DependencyGroup, DependencyGroupMembership
from app.models.external_identity import ExternalIdentity, IssueExternalIdentityMapping
from app.models.issue import Issue
from app.models.thread import Thread
from app.services.ultimate_universe_production_migration import (
    UltimateUniverseDryRunSpec,
    build_ultimate_universe_dry_run,
)
from comic_pile.dependencies import refresh_user_blocked_status
from tests.conftest import get_or_create_user_async


async def _thread_with_issue(
    db: AsyncSession,
    *,
    user_id: int,
    title: str,
    queue_position: int,
    issue_status: str,
) -> tuple[Thread, Issue]:
    """Create one single-issue thread with internally consistent tracking state."""
    thread = Thread(
        user_id=user_id,
        title=title,
        format="comic",
        queue_position=queue_position,
        status="active" if issue_status != "read" else "completed",
        total_issues=1,
        issues_remaining=1 if issue_status != "read" else 0,
        reading_progress="unstarted" if issue_status != "read" else "completed",
        created_at=datetime.now(UTC),
    )
    db.add(thread)
    await db.flush()
    issue = Issue(
        thread_id=thread.id,
        issue_number="1",
        position=1,
        status=issue_status,
        read_at=datetime.now(UTC) if issue_status == "read" else None,
    )
    db.add(issue)
    await db.flush()
    thread.next_unread_issue_id = issue.id if issue_status != "read" else None
    return thread, issue


async def _production_shaped_fixture(
    db: AsyncSession,
) -> tuple[UltimateUniverseDryRunSpec, list[Issue], list[Thread]]:
    """Create a four-position source with an unread/read/read/unread history gap."""
    user = await get_or_create_user_async(db)
    rows = [
        await _thread_with_issue(
            db,
            user_id=user.id,
            title="Ultimate Test A",
            queue_position=1,
            issue_status="unread",
        ),
        await _thread_with_issue(
            db,
            user_id=user.id,
            title="Ultimate Test B",
            queue_position=2,
            issue_status="read",
        ),
        await _thread_with_issue(
            db,
            user_id=user.id,
            title="Ultimate Test C",
            queue_position=3,
            issue_status="read",
        ),
        await _thread_with_issue(
            db,
            user_id=user.id,
            title="Ultimate Test D",
            queue_position=4,
            issue_status="unread",
        ),
    ]
    threads = [row[0] for row in rows]
    issues = [row[1] for row in rows]

    source = CBLSource(
        repository="test/ultimate-universe-step23",
        revision_sha="b" * 40,
        synced_at=datetime.now(UTC),
    )
    db.add(source)
    await db.flush()
    source_list = CBLSourceList(
        source_id=source.id,
        source_path="Marvel/Ultimate/Test.cbl",
        name="Ultimate Universe Step 23 Test",
        declared_issue_count=4,
        content_hash="a" * 64,
        revision_sha="b" * 40,
        active=True,
    )
    db.add(source_list)
    await db.flush()

    for position, issue in enumerate(issues, start=1):
        identity = ExternalIdentity(
            provider="comicvine",
            entity_type="issue",
            external_id=f"step23-{position}",
            metadata_json={},
        )
        db.add(identity)
        await db.flush()
        db.add(
            IssueExternalIdentityMapping(
                issue_id=issue.id,
                external_identity_id=identity.id,
                status="confirmed",
                evidence_source="step23-test",
                confidence=1.0,
            )
        )
        db.add(
            CBLSourceEntry(
                list_id=source_list.id,
                position=position,
                series_name=f"Ultimate Test {position}",
                issue_number="1",
                external_issue_identity_id=identity.id,
            )
        )

    group = DependencyGroup(
        user_id=user.id,
        name="Ultimate Universe Step 23 Test",
        created_at=datetime.now(UTC),
    )
    db.add(group)
    await db.flush()
    for issue in issues:
        db.add(DependencyGroupMembership(group_id=group.id, issue_id=issue.id))
    await db.flush()

    legacy = Dependency(
        source_issue_id=issues[0].id,
        target_issue_id=issues[3].id,
        note=f"cbl-order:source:{source_list.content_hash}:1->4",
        created_at=datetime.now(UTC),
    )
    db.add(legacy)
    await db.flush()
    await db.execute(
        delete(ContinuityRule).where(ContinuityRule.legacy_dependency_id == legacy.id)
    )
    await db.flush()
    await refresh_user_blocked_status(user.id, db)
    await db.flush()

    spec = UltimateUniverseDryRunSpec(
        user_id=user.id,
        source_list_id=source_list.id,
        dependency_group_id=group.id,
        expected_content_hash=source_list.content_hash,
        expected_positions=4,
        plan_name="Ultimate Universe Test",
    )
    return spec, issues, threads


@pytest.mark.asyncio
async def test_step23a_dry_run_bridges_historical_read_gap_without_writes(
    async_db: AsyncSession,
) -> None:
    """Dry-run preserves Roll eligibility across an out-of-order historical read gap."""
    spec, issues, threads = await _production_shaped_fixture(async_db)
    await async_db.commit()

    before = {
        "plans": await async_db.scalar(select(func.count()).select_from(ContinuityPlan)),
        "dependencies": await async_db.scalar(select(func.count()).select_from(Dependency)),
        "rules": await async_db.scalar(select(func.count()).select_from(ContinuityRule)),
        "memberships": await async_db.scalar(
            select(func.count()).select_from(DependencyGroupMembership)
        ),
    }

    report = await build_ultimate_universe_dry_run(async_db, spec)
    await async_db.rollback()

    assert report["ok"] is True, report["errors"]
    assert report["errors"] == []
    assert report["source"]["position_count"] == 4
    assert report["source"]["first_unread_position"] == 1
    assert report["dependency_group"]["ordered_membership_count"] == 0
    assert len(report["source_legacy_dependencies"]) == 1
    assert report["source_linked_continuity_rules"] == []
    assert report["historical_gap_bridges"] == [
        {
            "source_position": 1,
            "source_issue_id": issues[0].id,
            "target_position": 4,
            "target_issue_id": issues[3].id,
        }
    ]
    assert report["planned"]["adjacent_rule_count"] == 3
    assert report["planned"]["gap_bridge_count"] == 1
    assert report["runtime_behavior"]["current_affected_roll_eligible_thread_ids"] == [
        threads[0].id
    ]
    assert report["runtime_behavior"]["simulated_future_eligible_thread_ids"] == [
        threads[0].id
    ]
    assert report["runtime_behavior"]["planned_extra_direct_blockers"] == []
    assert isinstance(report["snapshot_token"], str)

    after = {
        "plans": await async_db.scalar(select(func.count()).select_from(ContinuityPlan)),
        "dependencies": await async_db.scalar(select(func.count()).select_from(Dependency)),
        "rules": await async_db.scalar(select(func.count()).select_from(ContinuityRule)),
        "memberships": await async_db.scalar(
            select(func.count()).select_from(DependencyGroupMembership)
        ),
    }
    assert after == before


@pytest.mark.asyncio
async def test_step23a_snapshot_token_is_stable_for_unchanged_state(
    async_db: AsyncSession,
) -> None:
    """Repeated dry-runs over unchanged PostgreSQL state produce one review token."""
    spec, _, _ = await _production_shaped_fixture(async_db)
    await async_db.commit()

    first = await build_ultimate_universe_dry_run(async_db, spec)
    await async_db.rollback()
    second = await build_ultimate_universe_dry_run(async_db, spec)
    await async_db.rollback()

    assert first["ok"] is True
    assert second["ok"] is True
    assert first["snapshot_token"] == second["snapshot_token"]
