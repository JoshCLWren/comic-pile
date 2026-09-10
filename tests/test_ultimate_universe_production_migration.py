"""PostgreSQL acceptance coverage for Step 23A dry-run and Step 23B apply/rollback."""

from __future__ import annotations

from datetime import UTC, datetime

import pytest
from sqlalchemy import delete, func, select, text
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
    MigrationInvariantError,
    TEMPORARY_REPAIR_NOTE,
    UltimateUniverseDryRunSpec,
    apply_ultimate_universe_migration,
    build_ultimate_universe_dry_run,
    rollback_ultimate_universe_migration,
)
from comic_pile.dependencies import refresh_user_blocked_status
from comic_pile.queue import get_roll_pool
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
) -> tuple[UltimateUniverseDryRunSpec, list[Issue], list[Thread], Dependency]:
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
    return spec, issues, threads, legacy


async def _step23b_fixture(
    db: AsyncSession,
) -> tuple[
    UltimateUniverseDryRunSpec,
    list[Issue],
    list[Thread],
    Dependency,
    ContinuityRule,
    Dependency,
    ContinuityRule,
]:
    """Production shape plus a reusable standalone edge and a temporary repair.

    Returns the spec, issues, threads, the legacy source dependency, the
    reusable standalone ``item_read`` rule, the temporary repair dependency,
    and its dependency-linked temporary rule.
    """
    spec, issues, threads, legacy_dependency = await _production_shaped_fixture(db)
    issue_ids = [issue.id for issue in issues]

    standalone_rule = ContinuityRule(
        user_id=spec.user_id,
        source_type="issue",
        source_id=issue_ids[2],
        target_type="issue",
        target_id=issue_ids[3],
        satisfaction_type="item_read",
        note="standalone prerequisite",
    )
    db.add(standalone_rule)
    await db.flush()

    temp_dependency = Dependency(
        source_issue_id=issue_ids[1],
        target_issue_id=issue_ids[3],
        note=TEMPORARY_REPAIR_NOTE,
        created_at=datetime.now(UTC),
    )
    db.add(temp_dependency)
    await db.flush()
    temp_rule = ContinuityRule(
        user_id=spec.user_id,
        legacy_dependency_id=temp_dependency.id,
        source_type="issue",
        source_id=issue_ids[1],
        target_type="issue",
        target_id=issue_ids[3],
        satisfaction_type="item_read",
        note=TEMPORARY_REPAIR_NOTE,
    )
    db.add(temp_rule)
    await db.flush()
    await refresh_user_blocked_status(spec.user_id, db)
    await db.flush()

    return (
        spec,
        issues,
        threads,
        legacy_dependency,
        standalone_rule,
        temp_dependency,
        temp_rule,
    )


@pytest.mark.asyncio
async def test_step23a_dry_run_bridges_historical_read_gap_without_writes(
    async_db: AsyncSession,
) -> None:
    """Dry-run preserves Roll eligibility across an out-of-order historical read gap."""
    spec, issues, threads, _legacy = await _production_shaped_fixture(async_db)
    issue_ids = [issue.id for issue in issues]
    thread_ids = [thread.id for thread in threads]
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
            "source_issue_id": issue_ids[0],
            "target_position": 4,
            "target_issue_id": issue_ids[3],
        }
    ]
    assert report["planned"]["adjacent_rule_count"] == 3
    assert report["planned"]["gap_bridge_count"] == 1
    assert report["runtime_behavior"]["current_affected_roll_eligible_thread_ids"] == [
        thread_ids[0]
    ]
    assert report["runtime_behavior"]["simulated_future_eligible_thread_ids"] == [
        thread_ids[0]
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
    spec, _, _, _ = await _production_shaped_fixture(async_db)
    await async_db.commit()

    first = await build_ultimate_universe_dry_run(async_db, spec)
    await async_db.rollback()
    second = await build_ultimate_universe_dry_run(async_db, spec)
    await async_db.rollback()

    assert first["ok"] is True
    assert second["ok"] is True
    assert first["snapshot_token"] == second["snapshot_token"]


async def _eligible_of(
    user_id: int,
    db: AsyncSession,
    thread_ids: set[int],
) -> list[int]:
    """Return roll-eligible thread IDs restricted to one inspected thread set."""
    pool = await get_roll_pool(user_id, db)
    return sorted(thread.id for thread in pool if thread.id in thread_ids)


@pytest.mark.asyncio
async def test_step23b_apply_creates_plan_keeps_standalone_and_preserves_roll(
    async_db: AsyncSession,
) -> None:
    """Apply builds the strict plan + gap bridge while preserving Roll eligibility.

    This covers the issue contract: the strict plan and derived convergence gate
    appear, source and temporary authority are removed, equivalent standalone
    ``item_read`` edges survive un-owned, temporary rules disappear, and the
    protected reader facts and affected Roll-eligible set stay byte-for-byte same.
    """
    spec, issues, threads, legacy, standalone, temp_dep, temp_rule = (
        await _step23b_fixture(async_db)
    )
    issue_ids = [issue.id for issue in issues]
    thread_ids = {thread.id for thread in threads}
    await async_db.commit()

    snapshot = await build_ultimate_universe_dry_run(async_db, spec)
    assert snapshot["ok"] is True, snapshot["errors"]
    preflight_eligible = snapshot["runtime_behavior"][
        "current_affected_roll_eligible_thread_ids"
    ]
    assert preflight_eligible == [threads[0].id]

    receipt = await apply_ultimate_universe_migration(
        async_db,
        snapshot=snapshot,
        spec=spec,
    )
    await async_db.commit()

    assert receipt["plan_rule_count"] == 3
    assert receipt["expected_new_plan_rule_count"] == 3
    assert receipt["removed_source_dependency_count"] == 1
    assert receipt["removed_temporary_dependency_count"] == 1
    assert receipt["reused_standalone_rule_count"] == 1
    assert receipt["affected_roll_eligible_thread_ids"] == preflight_eligible

    plan = await async_db.get(ContinuityPlan, receipt["plan_id"])
    assert plan is not None
    assert plan.ordering_mode == "strict_sequential"
    assert [node["ref_id"] for node in plan.nodes_json] == issue_ids
    assert plan.nodes_json[-1]["convergence_gate"] == [
        {"node_type": "issue", "node_id": f"issue-{issue_ids[0]}"}
    ]

    assert await async_db.get(Dependency, legacy.id) is None
    assert await async_db.get(Dependency, temp_dep.id) is None
    assert await async_db.get(ContinuityRule, temp_rule.id) is None

    survivor = await async_db.get(ContinuityRule, standalone.id)
    assert survivor is not None
    assert survivor.note == "standalone prerequisite"
    assert survivor.satisfaction_type == "item_read"
    edge_rules = (
        await async_db.execute(
            select(ContinuityRule).where(
                ContinuityRule.user_id == spec.user_id,
                ContinuityRule.source_id == issue_ids[2],
                ContinuityRule.target_id == issue_ids[3],
            )
        )
    ).scalars().all()
    assert [rule.id for rule in edge_rules] == [standalone.id]
    assert not any(
        (rule.note or "").startswith("continuity-plan:") for rule in edge_rules
    )

    for key in (
        "issue_state_hash",
        "thread_state_hash",
        "event_state_hash",
        "identity_state_hash",
    ):
        assert receipt[key] == snapshot["factual"][key]

    assert await _eligible_of(spec.user_id, async_db, thread_ids) == preflight_eligible


@pytest.mark.asyncio
async def test_step23b_rollback_restores_exact_ids_and_temporary_linkage(
    async_db: AsyncSession,
) -> None:
    """Rollback restores exact dependency/rule IDs and temporary rule linkage."""
    spec, _issues, threads, legacy, standalone, temp_dep, temp_rule = (
        await _step23b_fixture(async_db)
    )
    thread_ids = {thread.id for thread in threads}
    await async_db.commit()

    snapshot = await build_ultimate_universe_dry_run(async_db, spec)
    preflight_eligible = snapshot["runtime_behavior"][
        "current_affected_roll_eligible_thread_ids"
    ]
    receipt = await apply_ultimate_universe_migration(
        async_db,
        snapshot=snapshot,
        spec=spec,
    )
    await async_db.commit()

    result = await rollback_ultimate_universe_migration(
        async_db,
        snapshot=snapshot,
        receipt=receipt,
        spec=spec,
    )
    await async_db.commit()

    assert result["restored_dependency_ids"] == sorted([legacy.id, temp_dep.id])
    assert result["restored_temporary_rule_ids"] == [temp_rule.id]
    assert result["affected_roll_eligible_thread_ids"] == preflight_eligible

    assert await async_db.get(ContinuityPlan, receipt["plan_id"]) is None
    marker = f"continuity-plan:{receipt['plan_id']}"
    remaining_marked_rules = await async_db.scalar(
        select(func.count())
        .select_from(ContinuityRule)
        .where(
            ContinuityRule.user_id == spec.user_id,
            ContinuityRule.note == marker,
        )
    )
    assert remaining_marked_rules == 0

    restored_legacy = await async_db.get(Dependency, legacy.id)
    assert restored_legacy is not None
    assert restored_legacy.source_issue_id == legacy.source_issue_id
    assert restored_legacy.target_issue_id == legacy.target_issue_id
    assert restored_legacy.note == legacy.note
    assert restored_legacy.created_at == legacy.created_at

    restored_temp = await async_db.get(Dependency, temp_dep.id)
    assert restored_temp is not None
    assert restored_temp.note == TEMPORARY_REPAIR_NOTE
    assert restored_temp.created_at == temp_dep.created_at

    restored_rule = await async_db.get(ContinuityRule, temp_rule.id)
    assert restored_rule is not None
    assert restored_rule.legacy_dependency_id == temp_dep.id
    assert restored_rule.note == TEMPORARY_REPAIR_NOTE
    assert restored_rule.source_id == temp_rule.source_id
    assert restored_rule.target_id == temp_rule.target_id

    survivor = await async_db.get(ContinuityRule, standalone.id)
    assert survivor is not None
    assert survivor.note == "standalone prerequisite"

    for key in (
        "issue_state_hash",
        "thread_state_hash",
        "event_state_hash",
        "identity_state_hash",
    ):
        assert result["factual"][key] == snapshot["factual"][key]

    assert await _eligible_of(spec.user_id, async_db, thread_ids) == preflight_eligible


@pytest.mark.asyncio
async def test_step23b_rollback_refuses_after_reader_edits_plan(
    async_db: AsyncSession,
) -> None:
    """Rollback fails closed instead of overwriting reader changes to the plan."""
    spec, _issues, _threads, _legacy, _standalone, _temp_dep, _temp_rule = (
        await _step23b_fixture(async_db)
    )
    await async_db.commit()

    snapshot = await build_ultimate_universe_dry_run(async_db, spec)
    receipt = await apply_ultimate_universe_migration(
        async_db,
        snapshot=snapshot,
        spec=spec,
    )
    await async_db.commit()

    plan = await async_db.get(ContinuityPlan, receipt["plan_id"])
    assert plan is not None
    plan.name = "Reader edited this plan"
    await async_db.commit()

    with pytest.raises(MigrationInvariantError, match="edited after cutover"):
        await rollback_ultimate_universe_migration(
            async_db,
            snapshot=snapshot,
            receipt=receipt,
            spec=spec,
        )
    await async_db.rollback()

    edited = await async_db.get(ContinuityPlan, receipt["plan_id"])
    assert edited is not None
    assert edited.name == "Reader edited this plan"


@pytest.mark.asyncio
async def test_step23b_stale_snapshot_token_refuses_apply_before_any_write(
    async_db: AsyncSession,
) -> None:
    """Apply refuses a stale token without deleting or persisting any row."""
    spec, _issues, _threads, legacy, _standalone, temp_dep, _temp_rule = (
        await _step23b_fixture(async_db)
    )
    await async_db.commit()

    snapshot = await build_ultimate_universe_dry_run(async_db, spec)
    assert snapshot["ok"] is True

    source_list = await async_db.get(CBLSourceList, spec.source_list_id)
    assert source_list is not None
    source_list.content_hash = "b" * 64
    await async_db.commit()

    plans_before = await async_db.scalar(select(func.count()).select_from(ContinuityPlan))

    with pytest.raises(MigrationInvariantError, match="changed since dry-run"):
        await apply_ultimate_universe_migration(
            async_db,
            snapshot=snapshot,
            spec=spec,
        )
    await async_db.rollback()

    assert (
        await async_db.scalar(select(func.count()).select_from(ContinuityPlan))
        == plans_before
    )
    assert await async_db.get(Dependency, legacy.id) is not None
    assert await async_db.get(Dependency, temp_dep.id) is not None
    assert await async_db.scalar(
        select(func.count())
        .select_from(ContinuityRule)
        .where(ContinuityRule.note.like("continuity-plan:%"))
    ) == 0


@pytest.mark.asyncio
async def test_step23b_rollback_cooperates_with_legacy_dependency_sync_trigger(
    async_db: AsyncSession,
) -> None:
    """Rollback restores exact rows when the production mirror trigger exists."""
    spec, _issues, threads, legacy, standalone, temp_dep, temp_rule = (
        await _step23b_fixture(async_db)
    )
    thread_ids = {thread.id for thread in threads}
    await async_db.commit()

    trigger_function = "test_step23b_sync_legacy_dependency"
    trigger_name = "trg_test_step23b_sync_legacy_dependency"
    await async_db.execute(
        text(
            f"""
            CREATE OR REPLACE FUNCTION {trigger_function}()
            RETURNS trigger
            LANGUAGE plpgsql
            AS $$
            DECLARE
                owner_id integer;
            BEGIN
                SELECT thread.user_id
                  INTO owner_id
                  FROM issues AS issue
                  JOIN threads AS thread ON thread.id = issue.thread_id
                 WHERE issue.id = NEW.source_issue_id;

                DELETE FROM continuity_rules
                 WHERE legacy_dependency_id = NEW.id;

                INSERT INTO continuity_rules (
                    user_id, source_type, source_id, target_type, target_id,
                    satisfaction_type, checkpoint_issue_id, legacy_dependency_id,
                    note, created_at, updated_at
                )
                VALUES (
                    owner_id, 'issue', NEW.source_issue_id, 'issue',
                    NEW.target_issue_id, 'item_read', NULL, NEW.id, NEW.note,
                    NEW.created_at, CURRENT_TIMESTAMP
                )
                ON CONFLICT (user_id, source_type, source_id, target_type, target_id)
                DO UPDATE SET
                    satisfaction_type = 'item_read',
                    checkpoint_issue_id = NULL,
                    legacy_dependency_id = EXCLUDED.legacy_dependency_id,
                    note = EXCLUDED.note,
                    updated_at = CURRENT_TIMESTAMP;
                RETURN NEW;
            END;
            $$
            """
        )
    )
    await async_db.execute(
        text(
            f"""
            CREATE TRIGGER {trigger_name}
            AFTER INSERT OR UPDATE OF source_issue_id, target_issue_id, note
            ON dependencies
            FOR EACH ROW
            EXECUTE FUNCTION {trigger_function}()
            """
        )
    )
    await async_db.commit()

    try:
        snapshot = await build_ultimate_universe_dry_run(async_db, spec)
        assert snapshot["ok"] is True, snapshot["errors"]
        preflight_eligible = snapshot["runtime_behavior"][
            "current_affected_roll_eligible_thread_ids"
        ]
        receipt = await apply_ultimate_universe_migration(
            async_db,
            snapshot=snapshot,
            spec=spec,
        )
        await async_db.commit()

        result = await rollback_ultimate_universe_migration(
            async_db,
            snapshot=snapshot,
            receipt=receipt,
            spec=spec,
        )
        await async_db.commit()

        assert result["restored_dependency_ids"] == sorted([legacy.id, temp_dep.id])
        assert result["restored_temporary_rule_ids"] == [temp_rule.id]
        assert result["affected_roll_eligible_thread_ids"] == preflight_eligible
        assert await async_db.get(ContinuityPlan, receipt["plan_id"]) is None

        assert await async_db.get(Dependency, legacy.id) is not None
        assert await async_db.get(Dependency, temp_dep.id) is not None
        restored_rule = await async_db.get(ContinuityRule, temp_rule.id)
        assert restored_rule is not None
        assert restored_rule.legacy_dependency_id == temp_dep.id
        survivor = await async_db.get(ContinuityRule, standalone.id)
        assert survivor is not None
        assert survivor.note == "standalone prerequisite"
        assert await _eligible_of(spec.user_id, async_db, thread_ids) == preflight_eligible
    finally:
        await async_db.rollback()
        await async_db.execute(text(f"DROP TRIGGER IF EXISTS {trigger_name} ON dependencies"))
        await async_db.execute(text(f"DROP FUNCTION IF EXISTS {trigger_function}()"))
        await async_db.commit()


@pytest.mark.asyncio
async def test_step23b_rollback_repairs_standalone_rule_claimed_by_sync_trigger(
    async_db: AsyncSession,
) -> None:
    """Rollback restores a standalone rule whose edge a restored source
    dependency re-claims through the production sync trigger.

    Production source-12 dependencies include every internal edge, so a
    reusable standalone ``item_read`` rule can share its edge with a restored
    source dependency. The sync trigger then rewrites the rule's
    ``legacy_dependency_id``/``note``/``updated_at`` during rollback; rollback
    must repair the rule back to its reviewed snapshot instead of refusing.
    """
    spec, _issues, threads, legacy, standalone, temp_dep, temp_rule = (
        await _step23b_fixture(async_db)
    )
    thread_ids = {thread.id for thread in threads}
    overlap = Dependency(
        source_issue_id=_issues[2].id,
        target_issue_id=_issues[3].id,
        note=f"cbl-order:source:{spec.expected_content_hash}:3->4",
        created_at=datetime.now(UTC),
    )
    async_db.add(overlap)
    await async_db.commit()

    trigger_function = "test_step23b_sync_legacy_dependency"
    trigger_name = "trg_test_step23b_sync_legacy_dependency"
    await async_db.execute(
        text(
            f"""
            CREATE OR REPLACE FUNCTION {trigger_function}()
            RETURNS trigger
            LANGUAGE plpgsql
            AS $$
            DECLARE
                owner_id integer;
            BEGIN
                SELECT thread.user_id
                  INTO owner_id
                  FROM issues AS issue
                  JOIN threads AS thread ON thread.id = issue.thread_id
                 WHERE issue.id = NEW.source_issue_id;

                DELETE FROM continuity_rules
                 WHERE legacy_dependency_id = NEW.id;

                INSERT INTO continuity_rules (
                    user_id, source_type, source_id, target_type, target_id,
                    satisfaction_type, checkpoint_issue_id, legacy_dependency_id,
                    note, created_at, updated_at
                )
                VALUES (
                    owner_id, 'issue', NEW.source_issue_id, 'issue',
                    NEW.target_issue_id, 'item_read', NULL, NEW.id, NEW.note,
                    NEW.created_at, CURRENT_TIMESTAMP
                )
                ON CONFLICT (user_id, source_type, source_id, target_type, target_id)
                DO UPDATE SET
                    satisfaction_type = 'item_read',
                    checkpoint_issue_id = NULL,
                    legacy_dependency_id = EXCLUDED.legacy_dependency_id,
                    note = EXCLUDED.note,
                    updated_at = CURRENT_TIMESTAMP;
                RETURN NEW;
            END;
            $$
            """
        )
    )
    await async_db.execute(
        text(
            f"""
            CREATE TRIGGER {trigger_name}
            AFTER INSERT OR UPDATE OF source_issue_id, target_issue_id, note
            ON dependencies
            FOR EACH ROW
            EXECUTE FUNCTION {trigger_function}()
            """
        )
    )
    await async_db.commit()

    try:
        snapshot = await build_ultimate_universe_dry_run(async_db, spec)
        assert snapshot["ok"] is True, snapshot["errors"]
        assert len(snapshot["source_legacy_dependencies"]) == 2
        preflight_eligible = snapshot["runtime_behavior"][
            "current_affected_roll_eligible_thread_ids"
        ]
        assert preflight_eligible == [threads[0].id]

        receipt = await apply_ultimate_universe_migration(
            async_db,
            snapshot=snapshot,
            spec=spec,
        )
        await async_db.commit()

        assert receipt["removed_source_dependency_count"] == 2
        assert receipt["removed_temporary_dependency_count"] == 1
        assert receipt["reused_standalone_rule_count"] == 1
        assert await async_db.get(Dependency, overlap.id) is None
        survivor = await async_db.get(ContinuityRule, standalone.id)
        assert survivor is not None
        assert survivor.note == "standalone prerequisite"
        assert survivor.legacy_dependency_id is None

        result = await rollback_ultimate_universe_migration(
            async_db,
            snapshot=snapshot,
            receipt=receipt,
            spec=spec,
        )
        await async_db.commit()

        assert result["restored_dependency_ids"] == sorted(
            [legacy.id, overlap.id, temp_dep.id]
        )
        assert result["restored_source_dependency_count"] == 2
        assert result["restored_temporary_rule_ids"] == [temp_rule.id]
        assert result["affected_roll_eligible_thread_ids"] == preflight_eligible
        assert await async_db.get(ContinuityPlan, receipt["plan_id"]) is None

        assert await async_db.get(Dependency, overlap.id) is not None
        assert await async_db.get(Dependency, legacy.id) is not None
        assert await async_db.get(Dependency, temp_dep.id) is not None
        restored_temp_rule = await async_db.get(ContinuityRule, temp_rule.id)
        assert restored_temp_rule is not None
        assert restored_temp_rule.legacy_dependency_id == temp_dep.id

        restored_standalone = await async_db.get(ContinuityRule, standalone.id)
        assert restored_standalone is not None
        assert restored_standalone.legacy_dependency_id is None
        assert restored_standalone.note == "standalone prerequisite"
        assert restored_standalone.satisfaction_type == "item_read"
        assert await _eligible_of(spec.user_id, async_db, thread_ids) == preflight_eligible
    finally:
        await async_db.rollback()
        await async_db.execute(text(f"DROP TRIGGER IF EXISTS {trigger_name} ON dependencies"))
        await async_db.execute(text(f"DROP FUNCTION IF EXISTS {trigger_function}()"))
        await async_db.commit()