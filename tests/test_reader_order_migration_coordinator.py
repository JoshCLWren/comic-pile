"""Coordinator and batch-receipt edge coverage for Step 27 migrations."""

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.dependency import Dependency
from app.models.dependency_group import DependencyGroup, DependencyGroupMembership
from app.models.issue import Issue
from app.models.thread import Thread
from app.services.explicit_reader_order_migration import (
    ExplicitReaderOrderSpec,
    apply_explicit_reader_order_migration,
    build_explicit_reader_order_dry_run,
)
from app.services.reader_order_migration_coordinator import (
    build_manifest_report,
    migration_report_status,
)
from app.services.ultimate_universe_production_migration import MigrationInvariantError
from comic_pile.dependencies import refresh_user_blocked_status
from scripts import reader_order_migration as cli
from tests.conftest import get_or_create_user_async


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
