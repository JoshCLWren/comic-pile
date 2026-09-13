"""Coordinator and batch-receipt edge coverage for Step 27 migrations."""

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path

import pytest
from httpx import AsyncClient
from sqlalchemy import delete, select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.continuity_plan import ContinuityPlan
from app.models.dependency import Dependency
from app.models.dependency_group import DependencyGroup, DependencyGroupMembership
from app.models.issue import Issue
from app.models.thread import Thread
from app.services.explicit_reader_order_migration import (
    PRODUCTION_EXPLICIT_READER_ORDER_SPECS,
    ExplicitReaderOrderSpec,
    _explicit_classifications,
    _load_step14_index,
    _resolve_selected_dependency_ids,
    apply_explicit_reader_order_migration,
    build_explicit_reader_order_dry_run,
)
from app.services.reader_order_migration_coordinator import (
    LEGACY_READING_ORDERS_MANIFEST,
    apply_explicit_reader_order_overlay,
    build_manifest_report,
    manifest_reader_order_dependency_ids,
    migration_report_status,
    reconcile_batch_manifest_reports,
)
from app.services.legacy_reading_order_production_migration import (
    apply_legacy_reading_order_migration,
    build_legacy_reading_order_dry_run,
    load_reviewed_step23a_contract,
)
from app.services.ultimate_universe_production_migration import MigrationInvariantError
from comic_pile.dependencies import refresh_user_blocked_status
from scripts import reader_order_migration as cli
from tests.conftest import get_or_create_user_async
from tests.test_legacy_reading_order_production_migration import (
    seed_step23a_shape,
)


async def _thread_issue(
    db: AsyncSession,
    *,
    user_id: int,
    title: str,
    queue_position: int,
    status: str = "unread",
) -> tuple[Thread, Issue]:
    thread = Thread(
        user_id=user_id,
        title=title,
        format="comic",
        queue_position=queue_position,
        status="completed" if status == "read" else "active",
        total_issues=1,
        issues_remaining=0 if status == "read" else 1,
        reading_progress="completed" if status == "read" else "unstarted",
        created_at=datetime.now(UTC),
    )
    db.add(thread)
    await db.flush()
    issue = Issue(
        thread_id=thread.id,
        issue_number="1",
        position=1,
        status=status,
        read_at=datetime.now(UTC) if status == "read" else None,
    )
    db.add(issue)
    await db.flush()
    thread.next_unread_issue_id = None if status == "read" else issue.id
    return thread, issue


def test_migration_report_status_buckets() -> None:
    """Operator-facing statuses stay stable for every refusal class."""
    assert migration_report_status({"already_migrated": True, "ok": True}) == (
        "already-migrated"
    )
    assert migration_report_status({"ok": True}) == "safe-to-migrate"
    assert (
        migration_report_status(
            {"ok": False, "errors": ["needs_review dependencies touch this plan: [9]"]}
        )
        == "blocked-by-needs-review"
    )
    assert (
        migration_report_status(
            {"ok": False, "errors": ["Roll eligibility would change for thread 3"]}
        )
        == "behavior-mismatch"
    )
    assert (
        migration_report_status(
            {"ok": False, "errors": ["source identity is ambiguous for position 2"]}
        )
        == "blocked-by-identity-or-source"
    )


def _real_overlap_reports() -> dict[str, dict[str, object]]:
    """Build report-shaped fixtures from the checked-in production contracts."""
    evidence = load_reviewed_step23a_contract()
    targets = evidence["proposed_canonical_targets"]
    assert isinstance(targets, list)
    target_by_name: dict[str, object] = {}
    for target in targets:
        assert isinstance(target, dict)
        payload = target["writer_payload"]
        assert isinstance(payload, dict)
        target_by_name[str(payload["name"])] = payload
    _, families = _explicit_classifications(_load_step14_index())
    reports: dict[str, dict[str, object]] = {
        LEGACY_READING_ORDERS_MANIFEST: {
            "status": "safe-to-migrate",
            "ok": True,
            "errors": [],
            "snapshot_token": "legacy-token",
            "dependency_overlap": evidence["dependency_overlap"],
            "proposed_canonical_targets": targets,
        }
    }
    for manifest in (
        "doctor-strange-epic-vol-10",
        "starman-compendiums",
        "starman-jsa-bridge",
    ):
        spec = PRODUCTION_EXPLICIT_READER_ORDER_SPECS[manifest]
        dependency_ids = _resolve_selected_dependency_ids(spec, by_family=families)
        plan_payload = target_by_name[spec.plan_name]
        assert isinstance(plan_payload, dict)
        if spec.expected_issue_ids:
            plan_payload = {
                **plan_payload,
                "nodes": [
                    {
                        "id": f"issue-{issue_id}",
                        "node_type": "issue",
                        "ref_id": issue_id,
                    }
                    for issue_id in spec.expected_issue_ids
                ],
            }
        reports[manifest] = {
            "status": "safe-to-migrate",
            "ok": True,
            "errors": [],
            "snapshot_token": f"{manifest}-token",
            "manifest": {"resolved_reader_order_dependency_ids": list(dependency_ids)},
            "planned": {"plan": plan_payload, "rules": []},
            "selected_reader_order_dependencies": [
                {"id": dependency_id} for dependency_id in dependency_ids
            ],
            "runtime_behavior": {
                "affected_thread_ids": [],
                "current_affected_roll_eligible_thread_ids": [],
            },
        }
    return reports


def test_reconcile_batch_uses_exact_real_overlap_sets() -> None:
    """Step 23B overlays only its exact subset of each production manifest."""
    reports = _real_overlap_reports()
    reconciled = reconcile_batch_manifest_reports(reports)
    assert reconciled[LEGACY_READING_ORDERS_MANIFEST]["status"] == "safe-to-migrate"
    expected = {
        "doctor-strange-epic-vol-10": ([1806, 1807, 1808, 1810, 1811], [], []),
        "starman-compendiums": (
            [1832, 1846, 1847],
            [32, 955, 1355, 1551, 1552],
            [],
        ),
        "starman-jsa-bridge": ([1833], [], [26360]),
    }
    for manifest, (covered, remaining, added) in expected.items():
        assert reconciled[manifest]["status"] == "safe-to-migrate"
        assert reconciled[manifest]["apply_mode"] == "existing-plan-overlay"
        assert reconciled[manifest]["covered_by"] == LEGACY_READING_ORDERS_MANIFEST
        assert reconciled[manifest]["covered_dependency_ids"] == covered
        assert reconciled[manifest]["remaining_dependency_ids"] == remaining
        assert reconciled[manifest]["overlay_added_issue_ids"] == added

    blocked_reports = _real_overlap_reports()
    blocked_reports["starman-compendiums"]["status"] = "blocked-by-identity-or-source"
    blocked_reports["starman-compendiums"]["ok"] = False
    blocked_reports["starman-compendiums"]["errors"] = ["identity mismatch"]
    blocked = reconcile_batch_manifest_reports(blocked_reports)["starman-compendiums"]
    assert blocked["status"] == "blocked-by-identity-or-source"
    assert blocked["ok"] is False
    assert "apply_mode" not in blocked

    resumed_reports = _real_overlap_reports()
    resumed_reports[LEGACY_READING_ORDERS_MANIFEST]["status"] = "already-migrated"
    resumed_reports[LEGACY_READING_ORDERS_MANIFEST]["already_migrated"] = True
    # Post-Step-23B live overlap no longer contains the deleted reader-order rows.
    live_overlap = resumed_reports[LEGACY_READING_ORDERS_MANIFEST]["dependency_overlap"]
    assert isinstance(live_overlap, list)
    resumed_reports[LEGACY_READING_ORDERS_MANIFEST]["dependency_overlap"] = [
        row
        for row in live_overlap
        if not (
            isinstance(row, dict) and row.get("step14_classification") == "reading_plan_order"
        )
    ]
    assert (
        manifest_reader_order_dependency_ids(
            resumed_reports[LEGACY_READING_ORDERS_MANIFEST]
        )
        == set()
    )
    # After Step 23B, raw explicit dry-runs are blocked (missing covered IDs).
    # Reconcile must not promote those; build_manifest_report recovers them first.
    blocked_resume = {
        key: dict(value) for key, value in resumed_reports.items()
    }
    for manifest in ("doctor-strange-epic-vol-10", "starman-compendiums", "starman-jsa-bridge"):
        covered = set(reconcile_batch_manifest_reports(_real_overlap_reports())[manifest][
            "covered_dependency_ids"
        ])
        blocked_resume[manifest]["status"] = "blocked-by-identity-or-source"
        blocked_resume[manifest]["ok"] = False
        blocked_resume[manifest]["errors"] = [
            f"classified reader-order dependencies missing: {sorted(covered)}"
        ]
    blocked_reconciled = reconcile_batch_manifest_reports(blocked_resume)
    assert "apply_mode" not in blocked_reconciled["starman-compendiums"]
    assert "apply_mode" not in blocked_reconciled["starman-jsa-bridge"]

    # Recovered residual-safe reports (status safe again) still schedule overlays.
    resumed = reconcile_batch_manifest_reports(resumed_reports)["starman-compendiums"]
    assert resumed["apply_mode"] == "existing-plan-overlay"
    assert resumed["covered_dependency_ids"] == [1832, 1846, 1847]
    assert resumed["remaining_dependency_ids"] == [32, 955, 1355, 1551, 1552]
    resumed_jsa = reconcile_batch_manifest_reports(resumed_reports)["starman-jsa-bridge"]
    assert resumed_jsa["overlay_added_issue_ids"] == [26360]


@pytest.mark.asyncio
async def test_explicit_migration_refuses_needs_review_intersection(
    async_db: AsyncSession,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A touching needs_review dependency fails closed before any apply."""
    user = await get_or_create_user_async(async_db)
    rows = [
        await _thread_issue(async_db, user_id=user.id, title=title, queue_position=i)
        for i, title in enumerate(("A", "B", "C"), start=1)
    ]
    issues = [row[1] for row in rows]
    group = DependencyGroup(
        user_id=user.id,
        name="Needs Review Family",
        created_at=datetime.now(UTC),
    )
    async_db.add(group)
    await async_db.flush()
    for issue in issues:
        async_db.add(DependencyGroupMembership(group_id=group.id, issue_id=issue.id))

    reader_order = Dependency(
        source_issue_id=issues[0].id,
        target_issue_id=issues[1].id,
        note="classified reader order",
        created_at=datetime.now(UTC),
    )
    needs_review = Dependency(
        source_issue_id=issues[2].id,
        target_issue_id=issues[1].id,
        note="needs human review",
        created_at=datetime.now(UTC),
    )
    async_db.add_all([reader_order, needs_review])
    await async_db.flush()
    await refresh_user_blocked_status(user.id, async_db)
    await async_db.commit()

    monkeypatch.setattr(
        "app.services.explicit_reader_order_migration._load_step14_index",
        lambda: {},
    )
    monkeypatch.setattr(
        "app.services.explicit_reader_order_migration._explicit_classifications",
        lambda _index: (
            {
                reader_order.id: "reading_plan_order",
                needs_review.id: "needs_review",
            },
            {"family": []},
        ),
    )
    monkeypatch.setattr(
        "app.services.explicit_reader_order_migration._generated_reader_order_patterns",
        lambda _index: (),
    )

    spec = ExplicitReaderOrderSpec(
        user_id=user.id,
        dependency_group_ids=(group.id,),
        expected_group_names=(group.name,),
        plan_name="Needs Review Family",
        reader_order_dependency_ids=(reader_order.id,),
    )
    snapshot = await build_explicit_reader_order_dry_run(async_db, spec)
    assert snapshot["ok"] is False
    assert any("needs_review dependencies touch this plan" in error for error in snapshot["errors"])
    assert [row["id"] for row in snapshot["needs_review_dependencies"]] == [needs_review.id]

    report = await build_manifest_report(
        async_db,
        manifest="needs-review-family",
        source_manifests={},
        explicit_manifests={"needs-review-family": spec},
    )
    assert report["status"] == "blocked-by-needs-review"
    assert report["ok"] is False

    with pytest.raises(MigrationInvariantError, match="needs_review"):
        await apply_explicit_reader_order_migration(
            async_db,
            snapshot=snapshot,
            spec=spec,
        )


@pytest.mark.asyncio
async def test_build_manifest_report_marks_already_migrated_explicit(
    async_db: AsyncSession,
) -> None:
    """Re-running a clean explicit migration reports already-migrated."""
    user = await get_or_create_user_async(async_db)
    rows = [
        await _thread_issue(
            async_db,
            user_id=user.id,
            title=title,
            queue_position=i,
            status=status,
        )
        for i, (title, status) in enumerate(
            (("A", "unread"), ("B", "read"), ("C", "unread")),
            start=1,
        )
    ]
    issues = [row[1] for row in rows]
    group = DependencyGroup(
        user_id=user.id,
        name="Already Migrated Family",
        created_at=datetime.now(UTC),
    )
    async_db.add(group)
    await async_db.flush()
    for issue in issues:
        async_db.add(DependencyGroupMembership(group_id=group.id, issue_id=issue.id))
    reader_order = [
        Dependency(
            source_issue_id=issues[0].id,
            target_issue_id=issues[2].id,
            note="classified reader order A->C",
            created_at=datetime.now(UTC),
        ),
        Dependency(
            source_issue_id=issues[1].id,
            target_issue_id=issues[2].id,
            note="classified reader order B->C",
            created_at=datetime.now(UTC),
        ),
    ]
    async_db.add_all(reader_order)
    await async_db.flush()
    await refresh_user_blocked_status(user.id, async_db)
    await async_db.commit()

    spec = ExplicitReaderOrderSpec(
        user_id=user.id,
        dependency_group_ids=(group.id,),
        expected_group_names=(group.name,),
        plan_name="Already Migrated Family",
        reader_order_dependency_ids=tuple(dependency.id for dependency in reader_order),
    )
    snapshot = await build_explicit_reader_order_dry_run(async_db, spec)
    assert snapshot["ok"] is True, snapshot["errors"]
    await apply_explicit_reader_order_migration(async_db, snapshot=snapshot, spec=spec)
    await async_db.commit()

    report = await build_manifest_report(
        async_db,
        manifest="already-migrated-family",
        source_manifests={},
        explicit_manifests={"already-migrated-family": spec},
    )
    assert report["status"] == "already-migrated"
    assert report["already_migrated"] is True


@pytest.mark.asyncio
async def test_build_manifest_report_marks_already_migrated_groupless_explicit(
    async_db: AsyncSession,
    auth_client: AsyncClient,
) -> None:
    """GET/PUT preserves proof so a group-less migration remains replay-safe."""
    user = await get_or_create_user_async(async_db)
    rows = [
        await _thread_issue(
            async_db,
            user_id=user.id,
            title=title,
            queue_position=i,
            status=status,
        )
        for i, (title, status) in enumerate(
            (("A", "unread"), ("B", "read"), ("C", "unread")),
            start=1,
        )
    ]
    issues = [row[1] for row in rows]
    reader_order = [
        Dependency(
            source_issue_id=issues[0].id,
            target_issue_id=issues[2].id,
            note="classified reader order A->C",
            created_at=datetime.now(UTC),
        ),
        Dependency(
            source_issue_id=issues[1].id,
            target_issue_id=issues[2].id,
            note="classified reader order B->C",
            created_at=datetime.now(UTC),
        ),
    ]
    async_db.add_all(reader_order)
    await async_db.flush()
    await refresh_user_blocked_status(user.id, async_db)
    await async_db.commit()

    spec = ExplicitReaderOrderSpec(
        user_id=user.id,
        dependency_group_ids=(),
        expected_group_names=(),
        plan_name="Groupless Already Migrated",
        reader_order_dependency_ids=tuple(dependency.id for dependency in reader_order),
    )
    snapshot = await build_explicit_reader_order_dry_run(async_db, spec)
    assert snapshot["ok"] is True, snapshot["errors"]
    await apply_explicit_reader_order_migration(async_db, snapshot=snapshot, spec=spec)
    await async_db.commit()

    plan = await async_db.scalar(
        select(ContinuityPlan).where(ContinuityPlan.name == spec.plan_name)
    )
    assert plan is not None
    fetched = await auth_client.get(f"/api/v1/continuity-plans/{plan.id}")
    assert fetched.status_code == 200, fetched.text
    fetched_body = fetched.json()
    contract = fetched_body["lanes"][0]["migration_contract"]
    assert contract["selected_dependency_ids"] == [
        dependency.id for dependency in reader_order
    ]

    ordinary_payload = {
        "name": fetched_body["name"],
        "ordering_mode": fetched_body["ordering_mode"],
        "lanes": [
            {key: value for key, value in lane.items() if key != "migration_contract"}
            for lane in fetched_body["lanes"]
        ],
        "nodes": fetched_body["nodes"],
    }
    updated = await auth_client.put(
        f"/api/v1/continuity-plans/{plan.id}",
        json=ordinary_payload,
    )
    assert updated.status_code == 200, updated.text
    assert updated.json()["lanes"][0]["migration_contract"] == contract

    report = await build_manifest_report(
        async_db,
        manifest="groupless-already-migrated",
        source_manifests={},
        explicit_manifests={"groupless-already-migrated": spec},
    )
    assert report["status"] == "already-migrated"
    assert report["already_migrated"] is True


@pytest.mark.asyncio
async def test_partial_overlap_overlays_explicit_gates_on_existing_plan(
    async_db: AsyncSession,
) -> None:
    """A Step 23B plan absorbs residual exact edges without losing its full order."""
    user = await get_or_create_user_async(async_db)
    rows = [
        await _thread_issue(
            async_db,
            user_id=user.id,
            title=title,
            queue_position=position,
            status=status,
        )
        for position, (title, status) in enumerate(
            (("A", "unread"), ("B", "read"), ("C", "unread"), ("Extra", "unread")),
            start=1,
        )
    ]
    issues = [row[1] for row in rows]
    dependencies = [
        Dependency(
            source_issue_id=issues[0].id,
            target_issue_id=issues[2].id,
            note="covered by Step 23B",
            created_at=datetime.now(UTC),
        ),
        Dependency(
            source_issue_id=issues[1].id,
            target_issue_id=issues[2].id,
            note="residual explicit edge",
            created_at=datetime.now(UTC),
        ),
    ]
    async_db.add_all(dependencies)
    await async_db.flush()
    await refresh_user_blocked_status(user.id, async_db)
    await async_db.commit()

    spec = ExplicitReaderOrderSpec(
        user_id=user.id,
        dependency_group_ids=(),
        expected_group_names=(),
        plan_name="Legacy order projection",
        reader_order_dependency_ids=tuple(row.id for row in dependencies),
    )
    snapshot = await build_explicit_reader_order_dry_run(async_db, spec)
    assert snapshot["ok"] is True, snapshot["errors"]

    await async_db.execute(delete(Dependency).where(Dependency.id == dependencies[0].id))
    legacy_plan = ContinuityPlan(
        user_id=user.id,
        name=spec.plan_name,
        ordering_mode="informational",
        lanes_json=[{"id": "main", "name": "Full legacy order", "order": 0}],
        nodes_json=[
            {
                "id": f"legacy-position-{position}",
                "node_type": "issue",
                "ref_id": issue.id,
                "lane_id": "main",
                "position": position,
                "convergence_gate": [],
            }
            for position, issue in enumerate(issues[1:])
        ],
    )
    async_db.add(legacy_plan)
    await async_db.flush()

    receipt = await apply_explicit_reader_order_overlay(
        async_db,
        snapshot=snapshot,
        spec=spec,
        covered_dependency_ids={dependencies[0].id},
    )
    assert receipt["covered_dependency_ids"] == [dependencies[0].id]
    assert receipt["overlay_added_issue_ids"] == [issues[0].id]
    assert receipt["removed_reader_order_dependency_count"] == 1
    assert await async_db.get(Dependency, dependencies[1].id) is None
    assert len(legacy_plan.nodes_json) == 4
    target_node = next(node for node in legacy_plan.nodes_json if node["ref_id"] == issues[2].id)
    convergence_gate = target_node["convergence_gate"]
    assert isinstance(convergence_gate, list)
    assert {
        target["node_id"] for target in convergence_gate if isinstance(target, dict)
    } == {
        f"issue-{issues[0].id}",
        "legacy-position-0",
    }
    contract = legacy_plan.lanes_json[0]["migration_contract"]
    assert isinstance(contract, dict)
    assert contract["selected_dependency_ids"] == [
        dependency.id for dependency in dependencies
    ]
    await async_db.commit()

    report = await build_manifest_report(
        async_db,
        manifest="partial-overlay",
        source_manifests={},
        explicit_manifests={"partial-overlay": spec},
    )
    assert report["status"] == "already-migrated"


@pytest.mark.asyncio
async def test_batch_apply_refuses_token_mismatch(
    async_db: AsyncSession,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Batch apply refuses when a safe row's snapshot token no longer matches."""
    user = await get_or_create_user_async(async_db)
    rows = [
        await _thread_issue(
            async_db,
            user_id=user.id,
            title=title,
            queue_position=i,
            status=status,
        )
        for i, (title, status) in enumerate(
            (("A", "unread"), ("B", "read"), ("C", "unread")),
            start=1,
        )
    ]
    issues = [row[1] for row in rows]
    group = DependencyGroup(
        user_id=user.id,
        name="Batch Safe Family",
        created_at=datetime.now(UTC),
    )
    async_db.add(group)
    await async_db.flush()
    for issue in issues:
        async_db.add(DependencyGroupMembership(group_id=group.id, issue_id=issue.id))
    reader_order = Dependency(
        source_issue_id=issues[0].id,
        target_issue_id=issues[2].id,
        note="classified reader order",
        created_at=datetime.now(UTC),
    )
    async_db.add(reader_order)
    await async_db.flush()
    await refresh_user_blocked_status(user.id, async_db)
    await async_db.commit()

    spec = ExplicitReaderOrderSpec(
        user_id=user.id,
        dependency_group_ids=(group.id,),
        expected_group_names=(group.name,),
        plan_name="Batch Safe Family",
        reader_order_dependency_ids=(reader_order.id,),
    )
    snapshot = await build_explicit_reader_order_dry_run(async_db, spec)
    assert snapshot["ok"] is True, snapshot["errors"]
    snapshot = {**snapshot, "status": "safe-to-migrate"}

    output_dir = tmp_path / "reports"
    output_dir.mkdir()
    safe_path = output_dir / "safe-family.json"
    safe_path.write_text(
        json.dumps(snapshot, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    summary = {
        "manifests": [
            {
                "manifest": "safe-family",
                "status": "safe-to-migrate",
                "snapshot_token": "wrong-token",
                "output": str(safe_path),
            },
            {
                "manifest": "blocked-family",
                "status": "blocked-by-needs-review",
                "snapshot_token": "ignored",
                "output": str(output_dir / "blocked-family.json"),
            },
        ]
    }
    summary_path = tmp_path / "summary.json"
    summary_path.write_text(
        json.dumps(summary, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )

    class _SessionFactory:
        async def __aenter__(self) -> AsyncSession:
            return async_db

        async def __aexit__(self, *_args: object) -> None:
            return None

    monkeypatch.setattr(cli, "EXPLICIT_MANIFESTS", {"safe-family": spec})
    monkeypatch.setattr(cli, "SOURCE_MANIFESTS", {})
    monkeypatch.setattr(cli, "ALL_MANIFESTS", {"safe-family", "blocked-family"})
    monkeypatch.setattr(cli, "AsyncSessionLocal", lambda: _SessionFactory())
    monkeypatch.setattr(async_db, "commit", async_db.flush)
    monkeypatch.setattr(async_db, "rollback", async_db.flush)

    with pytest.raises(MigrationInvariantError, match="batch snapshot metadata changed"):
        await cli._batch_apply(summary_path, tmp_path / "receipt.json", cli.CONFIRMATION)

    assert await async_db.get(Dependency, reader_order.id) is not None


@pytest.mark.asyncio
async def test_batch_apply_refuses_reader_fact_drift_before_mutation(
    async_db: AsyncSession,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Batch apply rebuilds every clean snapshot before the first write."""
    user = await get_or_create_user_async(async_db)
    rows = [
        await _thread_issue(
            async_db,
            user_id=user.id,
            title=title,
            queue_position=i,
            status=status,
        )
        for i, (title, status) in enumerate(
            (("A", "unread"), ("B", "read"), ("C", "unread")),
            start=1,
        )
    ]
    issues = [row[1] for row in rows]
    group = DependencyGroup(
        user_id=user.id,
        name="Drift Family",
        created_at=datetime.now(UTC),
    )
    async_db.add(group)
    await async_db.flush()
    for issue in issues:
        async_db.add(DependencyGroupMembership(group_id=group.id, issue_id=issue.id))
    reader_order = Dependency(
        source_issue_id=issues[0].id,
        target_issue_id=issues[2].id,
        note="classified reader order",
        created_at=datetime.now(UTC),
    )
    async_db.add(reader_order)
    await async_db.flush()
    await refresh_user_blocked_status(user.id, async_db)
    await async_db.commit()

    spec = ExplicitReaderOrderSpec(
        user_id=user.id,
        dependency_group_ids=(group.id,),
        expected_group_names=(group.name,),
        plan_name="Drift Family",
        reader_order_dependency_ids=(reader_order.id,),
    )
    snapshot = await build_explicit_reader_order_dry_run(async_db, spec)
    assert snapshot["ok"] is True, snapshot["errors"]
    snapshot = {**snapshot, "status": "safe-to-migrate"}

    output_dir = tmp_path / "reports"
    output_dir.mkdir()
    safe_path = output_dir / "drift-family.json"
    safe_path.write_text(
        json.dumps(snapshot, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    summary = {
        "manifests": [
            {
                "manifest": "drift-family",
                "status": "safe-to-migrate",
                "snapshot_token": snapshot["snapshot_token"],
                "output": str(safe_path),
            }
        ]
    }
    summary_path = tmp_path / "summary.json"
    summary_path.write_text(
        json.dumps(summary, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )

    # Drift a selected dependency fact after the exact dry-run snapshot was sealed.
    reader_order.note = "mutated after dry-run"
    await async_db.flush()
    await async_db.commit()

    class _SessionFactory:
        async def __aenter__(self) -> AsyncSession:
            return async_db

        async def __aexit__(self, *_args: object) -> None:
            return None

    monkeypatch.setattr(cli, "EXPLICIT_MANIFESTS", {"drift-family": spec})
    monkeypatch.setattr(cli, "SOURCE_MANIFESTS", {})
    monkeypatch.setattr(cli, "ALL_MANIFESTS", {"drift-family"})
    monkeypatch.setattr(cli, "AsyncSessionLocal", lambda: _SessionFactory())
    monkeypatch.setattr(async_db, "commit", async_db.flush)
    monkeypatch.setattr(async_db, "rollback", async_db.flush)

    with pytest.raises(MigrationInvariantError, match="live state changed since dry-run"):
        await cli._batch_apply(summary_path, tmp_path / "receipt.json", cli.CONFIRMATION)

    assert await async_db.get(Dependency, reader_order.id) is not None


@pytest.mark.asyncio
async def test_batch_apply_refuses_group_membership_drift_before_mutation(
    async_db: AsyncSession,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Batch apply refuses when sequence_order appears after the sealed dry-run."""
    user = await get_or_create_user_async(async_db)
    rows = [
        await _thread_issue(
            async_db,
            user_id=user.id,
            title=title,
            queue_position=i,
            status=status,
        )
        for i, (title, status) in enumerate(
            (("A", "unread"), ("B", "read"), ("C", "unread")),
            start=1,
        )
    ]
    issues = [row[1] for row in rows]
    group = DependencyGroup(
        user_id=user.id,
        name="Membership Drift Family",
        created_at=datetime.now(UTC),
    )
    async_db.add(group)
    await async_db.flush()
    memberships = [
        DependencyGroupMembership(group_id=group.id, issue_id=issue.id)
        for issue in issues
    ]
    async_db.add_all(memberships)
    reader_order = Dependency(
        source_issue_id=issues[0].id,
        target_issue_id=issues[2].id,
        note="classified reader order",
        created_at=datetime.now(UTC),
    )
    async_db.add(reader_order)
    await async_db.flush()
    await refresh_user_blocked_status(user.id, async_db)
    await async_db.commit()

    spec = ExplicitReaderOrderSpec(
        user_id=user.id,
        dependency_group_ids=(group.id,),
        expected_group_names=(group.name,),
        plan_name="Membership Drift Family",
        reader_order_dependency_ids=(reader_order.id,),
    )
    snapshot = await build_explicit_reader_order_dry_run(async_db, spec)
    assert snapshot["ok"] is True, snapshot["errors"]
    snapshot = {**snapshot, "status": "safe-to-migrate"}

    output_dir = tmp_path / "reports"
    output_dir.mkdir()
    safe_path = output_dir / "membership-drift-family.json"
    safe_path.write_text(
        json.dumps(snapshot, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    summary_path = tmp_path / "summary.json"
    summary_path.write_text(
        json.dumps(
            {
                "manifests": [
                    {
                        "manifest": "membership-drift-family",
                        "status": "safe-to-migrate",
                        "snapshot_token": snapshot["snapshot_token"],
                        "output": str(safe_path),
                    }
                ]
            },
            indent=2,
            sort_keys=True,
        )
        + "\n",
        encoding="utf-8",
    )

    memberships[0].sequence_order = 1
    await async_db.flush()
    await async_db.commit()

    class _SessionFactory:
        async def __aenter__(self) -> AsyncSession:
            return async_db

        async def __aexit__(self, *_args: object) -> None:
            return None

    monkeypatch.setattr(
        cli, "EXPLICIT_MANIFESTS", {"membership-drift-family": spec}
    )
    monkeypatch.setattr(cli, "SOURCE_MANIFESTS", {})
    monkeypatch.setattr(cli, "ALL_MANIFESTS", {"membership-drift-family"})
    monkeypatch.setattr(cli, "AsyncSessionLocal", lambda: _SessionFactory())
    monkeypatch.setattr(async_db, "commit", async_db.flush)
    monkeypatch.setattr(async_db, "rollback", async_db.flush)

    with pytest.raises(MigrationInvariantError, match="live state changed since dry-run"):
        await cli._batch_apply(summary_path, tmp_path / "receipt.json", cli.CONFIRMATION)

    assert await async_db.get(Dependency, reader_order.id) is not None


@pytest.mark.asyncio
async def test_batch_dry_run_summary_buckets_non_safe_manifests(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Batch dry-run summary categorizes blocked and already-migrated manifests."""

    async def _fake_build_report(manifest: str) -> dict[str, object]:
        reports: dict[str, dict[str, object]] = {
            "safe-family": {
                "status": "safe-to-migrate",
                "ok": True,
                "errors": [],
                "snapshot_token": "safe-token",
                "preserved_standalone_dependencies": [{"id": 1}],
            },
            "review-family": {
                "status": "blocked-by-needs-review",
                "ok": False,
                "errors": ["needs_review dependencies touch this plan: [9]"],
                "snapshot_token": "review-token",
                "preserved_standalone_dependencies": [],
            },
            "done-family": {
                "status": "already-migrated",
                "ok": True,
                "errors": [],
                "snapshot_token": "done-token",
                "preserved_standalone_dependencies": [],
            },
        }
        return reports[manifest]

    monkeypatch.setattr(cli, "_build_report", _fake_build_report)
    summary_path = tmp_path / "summary.json"
    exit_code = await cli._batch_dry_run(
        ["safe-family", "review-family", "done-family"],
        tmp_path / "reports",
        summary_path,
    )
    assert exit_code == 2
    summary = json.loads(summary_path.read_text(encoding="utf-8"))
    assert summary["safe_to_migrate"] == ["safe-family"]
    assert summary["blocked_by_needs_review"] == ["review-family"]
    assert summary["already_migrated"] == ["done-family"]
    assert summary["blocked"] == ["review-family"]
    assert summary["standalone_prerequisite_state"]["safe-family"] == 1


@pytest.mark.asyncio
async def test_batch_dry_run_preserves_partial_overlap_for_overlay(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """All-unmigrated planning retains Starman's five-row residual migration."""
    reports = _real_overlap_reports()

    async def _fake_build_report(manifest: str) -> dict[str, object]:
        return reports[manifest]

    monkeypatch.setattr(cli, "_build_report", _fake_build_report)
    summary_path = tmp_path / "summary.json"
    manifests = [
        "doctor-strange-epic-vol-10",
        LEGACY_READING_ORDERS_MANIFEST,
        "starman-compendiums",
        "starman-jsa-bridge",
    ]
    exit_code = await cli._batch_dry_run(manifests, tmp_path / "reports", summary_path)
    assert exit_code == 0
    summary = json.loads(summary_path.read_text(encoding="utf-8"))
    assert summary["safe_to_migrate"] == [
        LEGACY_READING_ORDERS_MANIFEST,
        "doctor-strange-epic-vol-10",
        "starman-compendiums",
        "starman-jsa-bridge",
    ]
    assert summary["already_migrated"] == []
    assert summary["manifests"][0]["manifest"] == LEGACY_READING_ORDERS_MANIFEST
    starman = next(
        row for row in summary["manifests"] if row["manifest"] == "starman-compendiums"
    )
    assert starman["covered_dependency_ids"] == [1832, 1846, 1847]
    assert starman["remaining_dependency_ids"] == [32, 955, 1355, 1551, 1552]


@pytest.mark.asyncio
async def test_batch_apply_real_overlap_sets_reach_zero_reader_order_debt(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The real Step 23B/explicit sets leave the final cutover audit debt-free."""
    reports = reconcile_batch_manifest_reports(_real_overlap_reports())
    output_dir = tmp_path / "reports"
    output_dir.mkdir()
    rows: list[dict[str, object]] = []
    for manifest, report in reports.items():
        output = output_dir / f"{manifest}.json"
        output.write_text(json.dumps(report), encoding="utf-8")
        rows.append(
            {
                "manifest": manifest,
                "status": report["status"],
                "snapshot_token": report["snapshot_token"],
                "output": str(output),
                "apply_mode": report.get("apply_mode"),
                "covered_dependency_ids": report.get("covered_dependency_ids", []),
            }
        )
    summary_path = tmp_path / "summary.json"
    summary_path.write_text(json.dumps({"manifests": rows}), encoding="utf-8")

    debt = set().union(
        *(manifest_reader_order_dependency_ids(report) for report in reports.values())
    )

    class _Session:
        async def commit(self) -> None:
            return None

        async def rollback(self) -> None:
            return None

    class _SessionFactory:
        async def __aenter__(self) -> _Session:
            return _Session()

        async def __aexit__(self, *_args: object) -> None:
            return None

    async def _apply_legacy(*_args: object, **_kwargs: object) -> dict[str, object]:
        debt.difference_update(
            manifest_reader_order_dependency_ids(reports[LEGACY_READING_ORDERS_MANIFEST])
        )
        return {"ok": True}

    async def _apply_overlay(
        *_args: object,
        spec: ExplicitReaderOrderSpec,
        **_kwargs: object,
    ) -> dict[str, object]:
        manifest = next(
            key for key, candidate in PRODUCTION_EXPLICIT_READER_ORDER_SPECS.items()
            if candidate is spec
        )
        debt.difference_update(manifest_reader_order_dependency_ids(reports[manifest]))
        return {"ok": True}

    async def _cutover(*_args: object, **_kwargs: object) -> dict[str, object]:
        remaining = sorted(debt)
        return {
            "remaining_reading_plan_order_dependency_ids": remaining,
            "runtime_cutover_safe": not remaining,
        }

    overlap_manifests = set(reports) - {LEGACY_READING_ORDERS_MANIFEST}
    monkeypatch.setattr(cli, "AsyncSessionLocal", lambda: _SessionFactory())
    monkeypatch.setattr(cli, "SOURCE_MANIFESTS", {})
    monkeypatch.setattr(
        cli,
        "EXPLICIT_MANIFESTS",
        {key: PRODUCTION_EXPLICIT_READER_ORDER_SPECS[key] for key in overlap_manifests},
    )
    monkeypatch.setattr(cli, "ALL_MANIFESTS", set(reports))
    monkeypatch.setattr(cli, "apply_legacy_reading_order_migration", _apply_legacy)
    monkeypatch.setattr(cli, "apply_explicit_reader_order_overlay", _apply_overlay)
    monkeypatch.setattr(cli, "build_reader_order_cutover_audit", _cutover)

    async def _verify(*_args: object, **_kwargs: object) -> None:
        return None

    monkeypatch.setattr(cli, "_verify_clean_batch_snapshots", _verify)

    receipt_path = tmp_path / "receipt.json"
    exit_code = await cli._batch_apply(summary_path, receipt_path, cli.CONFIRMATION)
    assert exit_code == 0
    receipt = json.loads(receipt_path.read_text(encoding="utf-8"))
    assert receipt["cutover_audit"]["remaining_reading_plan_order_dependency_ids"] == []
    assert receipt["cutover_audit"]["runtime_cutover_safe"] is True


@pytest.mark.asyncio
async def test_batch_apply_commits_safe_subset_when_cutover_remains_blocked(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Clean manifests commit even when unrelated needs_review debt remains."""
    output_dir = tmp_path / "reports"
    output_dir.mkdir()
    safe_report = {
        "status": "safe-to-migrate",
        "ok": True,
        "errors": [],
        "snapshot_token": "safe-token",
    }
    safe_path = output_dir / "safe-family.json"
    safe_path.write_text(json.dumps(safe_report), encoding="utf-8")
    summary = {
        "manifests": [
            {
                "manifest": "safe-family",
                "status": "safe-to-migrate",
                "snapshot_token": "safe-token",
                "output": str(safe_path),
            },
            {
                "manifest": "blocked-family",
                "status": "blocked-by-needs-review",
                "snapshot_token": "blocked-token",
                "output": str(output_dir / "blocked-family.json"),
            },
        ]
    }
    summary_path = tmp_path / "summary.json"
    summary_path.write_text(json.dumps(summary), encoding="utf-8")

    class _Session:
        async def commit(self) -> None:
            return None

        async def rollback(self) -> None:
            return None

    class _SessionFactory:
        async def __aenter__(self) -> _Session:
            return _Session()

        async def __aexit__(self, *_args: object) -> None:
            return None

    async def _apply_explicit(*_args: object, **_kwargs: object) -> dict[str, object]:
        return {"ok": True, "plan_id": 11}

    async def _cutover(*_args: object, **_kwargs: object) -> dict[str, object]:
        return {
            "remaining_reading_plan_order_dependency_ids": [999],
            "runtime_cutover_safe": False,
        }

    async def _verify(*_args: object, **_kwargs: object) -> None:
        return None

    monkeypatch.setattr(cli, "AsyncSessionLocal", lambda: _SessionFactory())
    monkeypatch.setattr(cli, "SOURCE_MANIFESTS", {})
    monkeypatch.setattr(
        cli,
        "EXPLICIT_MANIFESTS",
        {"safe-family": PRODUCTION_EXPLICIT_READER_ORDER_SPECS["doctor-strange-epic-vol-10"]},
    )
    monkeypatch.setattr(cli, "ALL_MANIFESTS", {"safe-family", "blocked-family"})
    monkeypatch.setattr(cli, "apply_explicit_reader_order_migration", _apply_explicit)
    monkeypatch.setattr(cli, "build_reader_order_cutover_audit", _cutover)
    monkeypatch.setattr(cli, "_verify_clean_batch_snapshots", _verify)

    receipt_path = tmp_path / "receipt.json"
    exit_code = await cli._batch_apply(summary_path, receipt_path, cli.CONFIRMATION)
    assert exit_code == 0
    receipt = json.loads(receipt_path.read_text(encoding="utf-8"))
    assert [row["manifest"] for row in receipt["applied"]] == ["safe-family"]
    assert receipt["skipped"] == [
        {"manifest": "blocked-family", "status": "blocked-by-needs-review"}
    ]
    assert receipt["cutover_audit"]["runtime_cutover_safe"] is False
    assert receipt["cutover_audit"]["remaining_reading_plan_order_dependency_ids"] == [999]


def test_stage_durable_json_writes_pending_before_publish(tmp_path: Path) -> None:
    """Receipt staging fsyncs a pending file that can be atomically published."""
    target = tmp_path / "batch-receipt.json"
    pending = cli._stage_durable_json(target, {"ok": True, "applied": []})
    assert pending.exists()
    assert pending.suffix == ".pending"
    assert not target.exists()
    payload = json.loads(pending.read_text(encoding="utf-8"))
    assert payload == {"ok": True, "applied": []}
    pending.replace(target)
    assert target.exists()


@pytest.mark.asyncio
async def test_post_step23b_rebuild_schedules_residual_starman_overlays(
    async_db: AsyncSession,
) -> None:
    """Seed → apply Step 23B → rebuild reports schedules residual Starman overlays."""
    await seed_step23a_shape(async_db)
    pre_apply = await build_legacy_reading_order_dry_run(async_db)
    assert pre_apply["ok"] is True, pre_apply["errors"]
    token = str(pre_apply["snapshot_token"])
    await apply_legacy_reading_order_migration(
        async_db,
        accepted_snapshot_token=token,
        require_reviewed_token=False,
    )
    await async_db.commit()

    evidence = load_reviewed_step23a_contract()
    legacy_orders = evidence.get("legacy_reading_orders")
    if not isinstance(legacy_orders, list):
        raise AssertionError("Step 23A evidence is missing legacy_reading_orders")
    starman_order = next(
        order
        for order in legacy_orders
        if isinstance(order, dict) and order.get("title") == "Starman Compendiums 1-2"
    )
    if not isinstance(starman_order, dict):
        raise AssertionError("Starman legacy reading order missing from Step 23A evidence")
    starman_items = starman_order.get("items")
    if not isinstance(starman_items, list):
        raise AssertionError("Starman legacy reading order has no items")
    starman_issue_ids = [
        int(item["resolved_canonical_issue_id"])
        for item in starman_items
        if isinstance(item, dict) and isinstance(item.get("resolved_canonical_issue_id"), int)
    ]
    residual_pairs = [
        (starman_issue_ids[0], starman_issue_ids[1]),
        (starman_issue_ids[1], starman_issue_ids[2]),
        (starman_issue_ids[3], starman_issue_ids[4]),
        (starman_issue_ids[4], starman_issue_ids[5]),
        (starman_issue_ids[6], starman_issue_ids[7]),
    ]
    residual_ids = (32, 955, 1355, 1551, 1552)
    for dependency_id, (source_id, target_id) in zip(residual_ids, residual_pairs, strict=True):
        async_db.add(
            Dependency(
                id=dependency_id,
                source_issue_id=source_id,
                target_issue_id=target_id,
                note=f"starman residual {dependency_id}",
                created_at=datetime.now(UTC),
            )
        )
    await async_db.flush()
    await async_db.execute(
        text(
            "SELECT setval(pg_get_serial_sequence('dependencies', 'id'), "
            "COALESCE((SELECT MAX(id) FROM dependencies), 1), true)"
        )
    )
    await refresh_user_blocked_status(1, async_db)
    await async_db.commit()

    reports: dict[str, dict[str, object]] = {}
    for manifest in (
        LEGACY_READING_ORDERS_MANIFEST,
        "doctor-strange-epic-vol-10",
        "starman-compendiums",
        "starman-jsa-bridge",
    ):
        reports[manifest] = await build_manifest_report(
            async_db,
            manifest=manifest,
            source_manifests={},
            explicit_manifests={
                key: PRODUCTION_EXPLICIT_READER_ORDER_SPECS[key]
                for key in (
                    "doctor-strange-epic-vol-10",
                    "starman-compendiums",
                    "starman-jsa-bridge",
                )
            },
        )

    assert reports[LEGACY_READING_ORDERS_MANIFEST]["status"] == "already-migrated"
    # Raw explicit dry-runs would be blocked; coordinator recovery must make them safe.
    assert reports["starman-compendiums"]["status"] == "safe-to-migrate"
    assert reports["starman-compendiums"].get("recovered_after_step23b") is True
    assert reports["starman-jsa-bridge"]["status"] == "safe-to-migrate"
    assert reports["starman-jsa-bridge"].get("recovered_after_step23b") is True

    reconciled = reconcile_batch_manifest_reports(reports)
    starman = reconciled["starman-compendiums"]
    assert starman["apply_mode"] == "existing-plan-overlay"
    assert starman["covered_dependency_ids"] == [1832, 1846, 1847]
    assert starman["remaining_dependency_ids"] == [32, 955, 1355, 1551, 1552]

    jsa = reconciled["starman-jsa-bridge"]
    assert jsa["apply_mode"] == "existing-plan-overlay"
    assert jsa["covered_dependency_ids"] == [1833]
    assert jsa["remaining_dependency_ids"] == []
    assert jsa["overlay_added_issue_ids"] == [26360]

    doctor = reconciled["doctor-strange-epic-vol-10"]
    assert doctor["apply_mode"] == "existing-plan-overlay"
    assert doctor["covered_dependency_ids"] == [1806, 1807, 1808, 1810, 1811]
    assert doctor["remaining_dependency_ids"] == []
