"""PostgreSQL integration coverage for the guarded Step 23B migration."""

from __future__ import annotations

from datetime import UTC, datetime
import json
from pathlib import Path

import pytest
from sqlalchemy import func, select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.continuity_plan import ContinuityPlan
from app.models.continuity_rule import ContinuityRule
from app.models.dependency import Dependency
from app.models.issue import Issue
from app.models.reading_order import ReadingOrder, ReadingOrderItem
from app.models.thread import Thread
from app.models.user import User
from app.services.legacy_reading_order_production_migration import (
    REVIEWED_STEP23A_SNAPSHOT_TOKEN,
    MigrationInvariantError,
    apply_legacy_reading_order_migration,
    build_legacy_reading_order_dry_run,
    rollback_legacy_reading_order_migration,
)
from comic_pile.dependencies import refresh_user_blocked_status
from scripts.legacy_reading_order_step23b_migration import (
    CONFIRMATION,
    _require_confirmation,
)

ROOT = Path(__file__).resolve().parents[1]
EVIDENCE_PATH = ROOT / "docs/recovery/step23a-legacy-reading-order-preflight-evidence.json"
RETIRED_DEPENDENCY_IDS = (1806, 1807, 1808, 1810, 1811, 1832, 1833, 1846, 1847)
STANDALONE_DEPENDENCY_IDS = (18, 19, 20, 21)


def _evidence() -> dict[str, object]:
    """Load the reviewed Step 23A evidence object."""
    payload = json.loads(EVIDENCE_PATH.read_text(encoding="utf-8"))
    assert isinstance(payload, dict)
    return payload


def _object_dict(value: object, *, label: str) -> dict[str, object]:
    """Narrow one JSON object for ty."""
    assert isinstance(value, dict), label
    return {str(key): item for key, item in value.items()}


def _object_list(value: object, *, label: str) -> list[object]:
    """Narrow one JSON array for ty."""
    assert isinstance(value, list), label
    return [item for item in value]


def _dict_list(value: object, *, label: str) -> list[dict[str, object]]:
    """Narrow a JSON array of objects for ty."""
    return [_object_dict(row, label=f"{label} row") for row in _object_list(value, label=label)]


def _parse_time(value: object) -> datetime | None:
    """Parse an optional ISO timestamp from the evidence file."""
    if value is None:
        return None
    if not isinstance(value, str):
        raise TypeError(f"expected ISO timestamp, got {value!r}")
    return datetime.fromisoformat(value)


async def _setval(db: AsyncSession, table: str) -> None:
    """Advance a serial sequence past explicitly inserted primary keys."""
    await db.execute(
        text(
            f"SELECT setval(pg_get_serial_sequence('{table}', 'id'), "
            f"COALESCE((SELECT MAX(id) FROM {table}), 1), true)"
        )
    )


async def seed_step23a_shape(db: AsyncSession) -> dict[str, object]:
    """Insert production-shaped Step 23A rows derived from the reviewed evidence."""
    evidence = _evidence()
    user = User(id=1, username="step23b-owner", created_at=datetime.now(UTC))
    db.add(user)
    await db.flush()

    orders = _dict_list(evidence["legacy_reading_orders"], label="legacy_reading_orders")
    reader_state = _object_dict(evidence["reader_state"], label="reader_state")
    thread_meta = {
        int(row["thread_id"]): row
        for row in _dict_list(reader_state["threads"], label="reader threads")
    }
    issues_by_id: dict[int, dict[str, object]] = {}
    threads_needed: dict[int, dict[str, object]] = {}
    for order in orders:
        assert isinstance(order, dict)
        for item in _dict_list(order["items"], label="order items"):
            thread_id = int(item["legacy_thread_id"])
            issue_id = int(item["resolved_canonical_issue_id"])
            threads_needed.setdefault(
                thread_id,
                {
                    "title": item["title"],
                    "thread_id": thread_id,
                },
            )
            issues_by_id[issue_id] = {
                "issue_id": issue_id,
                "thread_id": thread_id,
                "issue_number": item["issue_number"],
                "status": item["current_read_status"],
                "read_at": item["read_at"],
            }

    overlap = _dict_list(evidence["dependency_overlap"], label="dependency_overlap")
    extra_queue = 400
    for row in overlap:
        assert isinstance(row, dict)
        for role in ("source", "target"):
            issue_id = int(row[f"{role}_issue_id"])
            if issue_id in issues_by_id:
                continue
            title = str(row[f"{role}_title"])
            thread_id = next(
                (
                    existing_id
                    for existing_id, meta in threads_needed.items()
                    if meta["title"] == title
                ),
                None,
            )
            if thread_id is None:
                extra_queue += 1
                thread_id = 900000 + extra_queue
                threads_needed[thread_id] = {"title": title, "thread_id": thread_id}
            issues_by_id[issue_id] = {
                "issue_id": issue_id,
                "thread_id": thread_id,
                "issue_number": row[f"{role}_issue_number"],
                "status": row[f"{role}_status"],
                "read_at": None,
            }

    eligibility = _dict_list(evidence["eligibility_baseline"], label="eligibility_baseline")
    for row in eligibility:
        assert isinstance(row, dict)
        next_unread = row.get("next_unread_issue_id")
        if isinstance(next_unread, int) and next_unread not in issues_by_id:
            thread_id = int(row["thread_id"])
            threads_needed.setdefault(
                thread_id,
                {"title": row["title"], "thread_id": thread_id},
            )
            issues_by_id[next_unread] = {
                "issue_id": next_unread,
                "thread_id": thread_id,
                "issue_number": row.get("next_unread_issue_number") or "1",
                "status": "unread",
                "read_at": None,
            }
        for blocker in _dict_list(row["blockers"], label="eligibility blockers"):
            source_id = int(blocker["source_id"])
            if source_id in issues_by_id:
                continue
            label = str(blocker["source_label"])
            title, _, number = label.rpartition(" #")
            extra_queue += 1
            thread_id = 900000 + extra_queue
            threads_needed[thread_id] = {
                "title": title or label,
                "thread_id": thread_id,
            }
            issues_by_id[source_id] = {
                "issue_id": source_id,
                "thread_id": thread_id,
                "issue_number": number or "1",
                "status": blocker["source_status"],
                "read_at": None,
            }

    created_threads: dict[int, Thread] = {}
    for thread_id, meta in sorted(threads_needed.items()):
        info = thread_meta.get(thread_id, {})
        thread = Thread(
            id=thread_id,
            title=str(info.get("title") or meta["title"]),
            format="Comic",
            issues_remaining=int(info.get("issues_remaining") or 0),
            queue_position=int(info.get("queue_position") or thread_id),
            status=str(info.get("status") or "active"),
            user_id=1,
            total_issues=0,
            reading_progress=(
                None
                if info.get("reading_progress") is None
                else str(info.get("reading_progress"))
            ),
            last_rating=info.get("last_rating") if isinstance(info.get("last_rating"), float) else None,
            last_activity_at=_parse_time(info.get("last_activity_at")),
            is_blocked=bool(info.get("is_blocked", False)),
            created_at=datetime.now(UTC),
        )
        db.add(thread)
        created_threads[thread_id] = thread
    await db.flush()

    positions: dict[int, int] = {}
    for issue_id, payload in sorted(issues_by_id.items()):
        thread_id = int(payload["thread_id"])
        positions[thread_id] = positions.get(thread_id, 0) + 1
        issue = Issue(
            id=issue_id,
            thread_id=thread_id,
            issue_number=str(payload["issue_number"]),
            position=positions[thread_id],
            status=str(payload["status"]),
            read_at=_parse_time(payload["read_at"]),
            created_at=datetime.now(UTC),
        )
        db.add(issue)
        thread = created_threads[thread_id]
        thread.total_issues = (thread.total_issues or 0) + 1
    await db.flush()

    for thread_id, info in thread_meta.items():
        thread = created_threads[thread_id]
        next_unread = info.get("next_unread_issue_id")
        thread.next_unread_issue_id = int(next_unread) if isinstance(next_unread, int) else None
        thread.issues_remaining = int(info.get("issues_remaining") or 0)
    await db.flush()

    for order in orders:
        assert isinstance(order, dict)
        db.add(
            ReadingOrder(
                id=int(order["reading_order_id"]),
                name=str(order["title"]),
                description=None if order["description"] is None else str(order["description"]),
                user_id=1,
            )
        )
    await db.flush()
    for order in orders:
        assert isinstance(order, dict)
        for item in _dict_list(order["items"], label="reading order items"):
            db.add(
                ReadingOrderItem(
                    id=int(item["legacy_item_id"]),
                    reading_order_id=int(order["reading_order_id"]),
                    thread_id=int(item["legacy_thread_id"]),
                    position=int(item["legacy_order_position"]),
                    issue_number=None if item["issue_number"] is None else str(item["issue_number"]),
                )
            )
    await db.flush()

    rules = {
        int(row["legacy_dependency_id"]): row
        for row in _dict_list(
            evidence["continuity_rule_overlap"],
            label="continuity_rule_overlap",
        )
    }
    for row in overlap:
        assert isinstance(row, dict)
        dependency_id = int(row["dependency_id"])
        db.add(
            Dependency(
                id=dependency_id,
                source_issue_id=int(row["source_issue_id"]),
                target_issue_id=int(row["target_issue_id"]),
                created_at=datetime.now(UTC),
                note=None if row["note"] is None else str(row["note"]),
            )
        )
    await db.flush()
    for row in overlap:
        dependency_id = int(row["dependency_id"])
        rule = rules[dependency_id]
        db.add(
            ContinuityRule(
                id=int(rule["rule_id"]),
                user_id=1,
                legacy_dependency_id=dependency_id,
                source_type=str(rule["source_type"]),
                source_id=int(rule["source_id"]),
                target_type=str(rule["target_type"]),
                target_id=int(rule["target_id"]),
                satisfaction_type=str(rule["satisfaction_type"]),
                note=None,
            )
        )

    for row in eligibility:
        assert isinstance(row, dict)
        for blocker in _dict_list(row["blockers"], label="unrelated blockers"):
            dependency_id = blocker["legacy_dependency_id"]
            if not isinstance(dependency_id, int) or dependency_id in rules:
                continue
            db.add(
                Dependency(
                    id=dependency_id,
                    source_issue_id=int(blocker["source_id"]),
                    target_issue_id=int(row["next_unread_issue_id"]),
                    created_at=datetime.now(UTC),
                    note="unrelated-starlin-cbl-order",
                )
            )
            await db.flush()
            db.add(
                ContinuityRule(
                    id=int(blocker["rule_id"]),
                    user_id=1,
                    legacy_dependency_id=dependency_id,
                    source_type="issue",
                    source_id=int(blocker["source_id"]),
                    target_type="issue",
                    target_id=int(row["next_unread_issue_id"]),
                    satisfaction_type="item_read",
                    note="unrelated-starlin-cbl-order",
                )
            )
    await db.flush()
    for table in (
        "users",
        "threads",
        "issues",
        "reading_orders",
        "reading_order_items",
        "dependencies",
        "continuity_rules",
    ):
        await _setval(db, table)
    await refresh_user_blocked_status(1, db)
    await db.flush()
    return evidence


async def _apply_clean(db: AsyncSession) -> tuple[dict[str, object], dict[str, object]]:
    """Seed, dry-run, and apply using the live fixture token."""
    await seed_step23a_shape(db)
    snapshot = await build_legacy_reading_order_dry_run(db)
    assert snapshot["ok"] is True, snapshot["errors"]
    token = snapshot["snapshot_token"]
    assert isinstance(token, str)
    receipt = await apply_legacy_reading_order_migration(
        db,
        accepted_snapshot_token=token,
        require_reviewed_token=False,
    )
    return snapshot, receipt


@pytest.mark.asyncio
async def test_step23b_dry_run_is_read_only_on_clean_shape(async_db: AsyncSession) -> None:
    """Clean Step 23A-shaped state passes dry-run without writes."""
    await seed_step23a_shape(async_db)
    plan_count = await async_db.scalar(select(func.count()).select_from(ContinuityPlan))
    dependency_count = await async_db.scalar(select(func.count()).select_from(Dependency))
    report = await build_legacy_reading_order_dry_run(async_db)
    assert report["ok"] is True, report["errors"]
    assert report["read_only"] is True
    assert report["reviewed_snapshot_token"] == REVIEWED_STEP23A_SNAPSHOT_TOKEN
    assert len(report["proposed_canonical_targets"]) == 3
    assert (
        await async_db.scalar(select(func.count()).select_from(ContinuityPlan))
        == plan_count
    )
    assert (
        await async_db.scalar(select(func.count()).select_from(Dependency))
        == dependency_count
    )


@pytest.mark.asyncio
async def test_step23b_exact_snapshot_token_allows_apply(async_db: AsyncSession) -> None:
    """The token produced by a fresh matching preflight allows apply."""
    snapshot, receipt = await _apply_clean(async_db)
    assert receipt["ok"] is True
    assert receipt["accepted_step23a_snapshot_token"] == snapshot["snapshot_token"]
    assert receipt["snapshot_guard_passed"] is True
    assert receipt["total_nodes_created"] == 140


@pytest.mark.asyncio
async def test_step23b_stale_snapshot_token_refuses_apply(async_db: AsyncSession) -> None:
    """A stale snapshot token fails closed and does not mutate state."""
    await seed_step23a_shape(async_db)
    with pytest.raises(MigrationInvariantError, match="stale"):
        await apply_legacy_reading_order_migration(
            async_db,
            accepted_snapshot_token="0" * 64,
            require_reviewed_token=False,
        )
    assert await async_db.scalar(select(func.count()).select_from(ContinuityPlan)) == 0


@pytest.mark.asyncio
async def test_step23b_reviewed_token_guard_refuses_non_reviewed_token(
    async_db: AsyncSession,
) -> None:
    """CLI-style apply refuses any token other than the reviewed Step 23A token."""
    await seed_step23a_shape(async_db)
    snapshot = await build_legacy_reading_order_dry_run(async_db)
    token = snapshot["snapshot_token"]
    assert isinstance(token, str)
    assert token != REVIEWED_STEP23A_SNAPSHOT_TOKEN
    with pytest.raises(MigrationInvariantError, match="stale"):
        await apply_legacy_reading_order_migration(
            async_db,
            accepted_snapshot_token=token,
            require_reviewed_token=True,
        )


@pytest.mark.asyncio
async def test_step23b_drift_after_preflight_refuses_apply(async_db: AsyncSession) -> None:
    """Mutation-relevant drift after preflight refuses apply."""
    await seed_step23a_shape(async_db)
    snapshot = await build_legacy_reading_order_dry_run(async_db)
    token = snapshot["snapshot_token"]
    assert isinstance(token, str)
    order = await async_db.get(ReadingOrder, 1)
    assert order is not None
    order.name = "Drifted Reading Order Name"
    await async_db.flush()
    with pytest.raises(MigrationInvariantError, match="stale"):
        await apply_legacy_reading_order_migration(
            async_db,
            accepted_snapshot_token=token,
            require_reviewed_token=False,
        )


@pytest.mark.asyncio
async def test_step23b_apply_creates_three_informational_plans(
    async_db: AsyncSession,
) -> None:
    """Apply creates exactly three informational plans with exact item order."""
    snapshot, receipt = await _apply_clean(async_db)
    plans = (
        await async_db.execute(select(ContinuityPlan).order_by(ContinuityPlan.id))
    ).scalars().all()
    assert len(plans) == 3
    targets = _dict_list(snapshot["proposed_canonical_targets"], label="proposed targets")
    assert {plan.name for plan in plans} == {target["name"] for target in targets}
    assert {plan.ordering_mode for plan in plans} == {"informational"}
    created = {
        str(plan["name"]): plan
        for plan in _dict_list(receipt["created_reading_plans"], label="created plans")
    }
    for target in targets:
        created_plan = created[str(target["name"])]
        payload = _object_dict(target["writer_payload"], label="writer_payload")
        expected_ids = [
            node["ref_id"] for node in _dict_list(payload["nodes"], label="writer nodes")
        ]
        assert created_plan["issue_ids"] == expected_ids
        assert created_plan["node_count"] == len(expected_ids)
        assert created_plan["plan_owned_hard_constraint_count"] == 0
    assert receipt["total_nodes_created"] == 140
    assert receipt["plan_owned_hard_constraints_created"] == 0


@pytest.mark.asyncio
async def test_step23b_apply_creates_zero_strict_adjacency_rules(
    async_db: AsyncSession,
) -> None:
    """Informational order does not compile adjacency ContinuityRules."""
    _, receipt = await _apply_clean(async_db)
    markers = [
        plan["plan_marker"]
        for plan in _dict_list(receipt["created_reading_plans"], label="created plans")
    ]
    plan_rules = (
        await async_db.execute(
            select(ContinuityRule).where(ContinuityRule.note.in_(markers))
        )
    ).scalars().all()
    assert plan_rules == []
    assert receipt["plan_owned_hard_constraints_created"] == 0


@pytest.mark.asyncio
async def test_step23b_apply_retires_only_reviewed_reading_plan_order_rows(
    async_db: AsyncSession,
) -> None:
    """Exactly the nine reviewed reading_plan_order constraints are retired."""
    _, receipt = await _apply_clean(async_db)
    remaining_retired = (
        await async_db.execute(
            select(Dependency.id).where(Dependency.id.in_(RETIRED_DEPENDENCY_IDS))
        )
    ).scalars().all()
    assert remaining_retired == []
    assert receipt["retired_reading_plan_order_dependency_ids"] == list(
        RETIRED_DEPENDENCY_IDS
    )
    leftover_unrelated = await async_db.get(Dependency, 2778)
    assert leftover_unrelated is not None


@pytest.mark.asyncio
async def test_step23b_apply_preserves_standalone_prerequisites(
    async_db: AsyncSession,
) -> None:
    """Dependencies #18-#21 survive apply with the same endpoints."""
    evidence = _evidence()
    _, receipt = await _apply_clean(async_db)
    surviving = (
        await async_db.execute(
            select(Dependency).where(Dependency.id.in_(STANDALONE_DEPENDENCY_IDS))
        )
    ).scalars().all()
    assert {row.id for row in surviving} == set(STANDALONE_DEPENDENCY_IDS)
    expected = {
        int(row["dependency_id"]): (int(row["source_issue_id"]), int(row["target_issue_id"]))
        for row in _dict_list(evidence["dependency_overlap"], label="dependency_overlap")
        if int(row["dependency_id"]) in STANDALONE_DEPENDENCY_IDS
    }
    actual = {row.id: (row.source_issue_id, row.target_issue_id) for row in surviving}
    assert actual == expected
    assert receipt["preserved_standalone_prerequisite_ids"] == list(
        STANDALONE_DEPENDENCY_IDS
    )


@pytest.mark.asyncio
async def test_step23b_apply_preserves_factual_reader_state(
    async_db: AsyncSession,
) -> None:
    """Protected factual hashes are unchanged by apply."""
    snapshot, receipt = await _apply_clean(async_db)
    assert (
        receipt["protected_reader_state_hashes_before"]
        == receipt["protected_reader_state_hashes_after"]
    )
    reader_state = _object_dict(snapshot["reader_state"], label="reader_state")
    before_hashes = _object_dict(
        receipt["protected_reader_state_hashes_before"],
        label="before hashes",
    )
    assert before_hashes["issue_state_hash"] == reader_state["issue_state_hash"]


@pytest.mark.asyncio
async def test_step23b_apply_keeps_roll_eligibility_invariants(
    async_db: AsyncSession,
) -> None:
    """Next unread issues and standalone blockers stay the same after apply."""
    snapshot, receipt = await _apply_clean(async_db)
    before = {
        row["thread_id"]: row
        for row in _dict_list(receipt["eligibility_baseline"], label="eligibility before")
    }
    after = {
        row["thread_id"]: row
        for row in _dict_list(receipt["eligibility_result"], label="eligibility after")
    }
    assert set(before) == set(after)
    for thread_id, before_row in before.items():
        after_row = after[thread_id]
        assert after_row["next_unread_issue_id"] == before_row["next_unread_issue_id"]
        assert (
            after_row["surviving_standalone_prerequisites_blocking"]
            == before_row["surviving_standalone_prerequisites_blocking"]
        )
        assert after_row["persisted_vs_derived_mismatch"] is False
    assert receipt["eligibility_constraint_model_delta"]
    snapshot_eligibility = _dict_list(
        snapshot["eligibility_baseline"],
        label="snapshot eligibility",
    )
    assert any(
        any(
            blocker.get("legacy_dependency_id") == 1808
            for blocker in _dict_list(row["blockers"], label="snapshot blockers")
        )
        for row in snapshot_eligibility
    )


@pytest.mark.asyncio
async def test_step23b_receipt_contains_exact_rollback_information(
    async_db: AsyncSession,
) -> None:
    """The apply receipt captures exact identities required for rollback."""
    _, receipt = await _apply_clean(async_db)
    state = _object_dict(receipt["original_reading_order_state"], label="original state")
    assert {row["id"] for row in _dict_list(state["reading_orders"], label="orders")} == {1, 2, 3}
    assert len(_object_list(state["reading_order_items"], label="items")) == 140
    assert {row["id"] for row in _dict_list(state["dependencies"], label="deps")} >= set(
        RETIRED_DEPENDENCY_IDS
    )
    assert receipt["rollback_guard_token"]
    assert receipt["created_plan_ids"]
    assert receipt["retired_continuity_rule_ids"]


@pytest.mark.asyncio
async def test_step23b_rollback_restores_legacy_identity_and_removes_plans(
    async_db: AsyncSession,
) -> None:
    """Rollback restores exact legacy IDs and deletes the created plans."""
    snapshot, receipt = await _apply_clean(async_db)
    result = await rollback_legacy_reading_order_migration(async_db, receipt=receipt)
    assert result["ok"] is True
    assert set(result["restored_dependency_ids"]) == set(RETIRED_DEPENDENCY_IDS)
    assert await async_db.scalar(select(func.count()).select_from(ContinuityPlan)) == 0
    restored = (
        await async_db.execute(
            select(Dependency.id).where(Dependency.id.in_(RETIRED_DEPENDENCY_IDS))
        )
    ).scalars().all()
    assert set(restored) == set(RETIRED_DEPENDENCY_IDS)
    restored_rules = (
        await async_db.execute(
            select(ContinuityRule).where(
                ContinuityRule.legacy_dependency_id.in_(RETIRED_DEPENDENCY_IDS)
            )
        )
    ).scalars().all()
    expected_rules = {
        int(row["legacy_dependency_id"]): int(row["rule_id"])
        for row in _dict_list(snapshot["continuity_rule_overlap"], label="rule overlap")
        if int(row["legacy_dependency_id"]) in RETIRED_DEPENDENCY_IDS
    }
    assert {rule.legacy_dependency_id: rule.id for rule in restored_rules} == expected_rules
    standalone = (
        await async_db.execute(
            select(Dependency.id).where(Dependency.id.in_(STANDALONE_DEPENDENCY_IDS))
        )
    ).scalars().all()
    assert set(standalone) == set(STANDALONE_DEPENDENCY_IDS)
    assert result["eligibility_restored_to_pre_apply_baseline"] is True


@pytest.mark.asyncio
async def test_step23b_rollback_refuses_after_protected_structural_edits(
    async_db: AsyncSession,
) -> None:
    """Rollback fails closed after a reader edits a migrated Reading Plan."""
    _, receipt = await _apply_clean(async_db)
    created_plan_ids = _object_list(receipt["created_plan_ids"], label="created_plan_ids")
    plan_id = created_plan_ids[0]
    assert isinstance(plan_id, int)
    plan = await async_db.get(ContinuityPlan, plan_id)
    assert plan is not None
    plan.name = "Reader edited this migrated plan"
    await async_db.flush()
    with pytest.raises(MigrationInvariantError, match="edited after cutover"):
        await rollback_legacy_reading_order_migration(async_db, receipt=receipt)
    assert await async_db.get(ContinuityPlan, plan_id) is not None


@pytest.mark.asyncio
async def test_step23b_rollback_handles_legacy_dependency_sync_trigger(
    async_db: AsyncSession,
) -> None:
    """Trigger-aware restore does not create duplicate ContinuityRules."""
    trigger_function = "test_step23b_sync_legacy_dependency"
    trigger_name = "trg_test_step23b_sync_legacy_dependency"
    _, receipt = await _apply_clean(async_db)
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
    try:
        result = await rollback_legacy_reading_order_migration(async_db, receipt=receipt)
        restored_rules = (
            await async_db.execute(
                select(ContinuityRule).where(
                    ContinuityRule.legacy_dependency_id.in_(RETIRED_DEPENDENCY_IDS)
                )
            )
        ).scalars().all()
        assert len(restored_rules) == 9
        assert {rule.legacy_dependency_id for rule in restored_rules} == set(
            RETIRED_DEPENDENCY_IDS
        )
        assert {rule.id for rule in restored_rules} == set(result["restored_continuity_rule_ids"])
    finally:
        await async_db.execute(text(f"DROP TRIGGER IF EXISTS {trigger_name} ON dependencies"))
        await async_db.execute(text(f"DROP FUNCTION IF EXISTS {trigger_function}()"))


def test_step23b_cli_requires_unique_confirmation() -> None:
    """Apply/rollback refuse anything except the Step 23B confirmation string."""
    _require_confirmation(CONFIRMATION)
    with pytest.raises(MigrationInvariantError, match="STEP23B-LEGACY-READING-ORDERS"):
        _require_confirmation("STEP22-BPRD")
