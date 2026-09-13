"""Guarded Step 23B apply and rollback for the three surviving legacy Reading Orders.

This module migrates the reviewed user-1 Reading Orders into informational
canonical Reading Plans. Dry-run is read-only and reuses the Step 23A preflight
contract. Apply refuses unless a fresh preflight produces the exact reviewed
Step 23A snapshot token. Rollback restores the captured compatibility rows and
refuses after protected structural edits.

Production apply is not authorized from this module. Callers must supply an
explicit database session and the reviewed token; nothing here discovers a
production URL.
"""

from __future__ import annotations

from datetime import datetime
from hashlib import sha256
import importlib.util
import json
from pathlib import Path
from types import ModuleType
from typing import cast

from fastapi import HTTPException
from sqlalchemy import delete, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.continuity_plan import ContinuityPlan
from app.models.continuity_rule import ContinuityRule
from app.models.dependency import Dependency
from app.models.reading_order import ReadingOrder, ReadingOrderItem
from app.schemas.continuity_plan import ContinuityPlanLane, ContinuityPlanNode
from app.services.continuity_plan_writer import (
    plan_rule_marker,
    replace_compiled_rules,
    validate_node_ownership,
)
from comic_pile.dependencies import refresh_user_blocked_status

ROOT = Path(__file__).resolve().parents[2]
STEP23A_SCRIPT = ROOT / "scripts" / "audit_step23a_legacy_reading_order_preflight.py"
STEP23A_EVIDENCE = ROOT / "docs/recovery/step23a-legacy-reading-order-preflight-evidence.json"
CONTINUITY_LOCK_NAMESPACE = 1_129_274_964
REVIEWED_STEP23A_SNAPSHOT_TOKEN = (
    "6cfa01ccc82f33c4e0fc7a23d9b7d4e4b32a66a7aa13bbbfd50bc633e38bdf7c"
)
STALE_SNAPSHOT_MESSAGE = (
    "The reviewed Step 23A snapshot is stale and a new preflight/review is "
    "required. Apply refuses to accept a drifted or regenerated token."
)


class MigrationInvariantError(RuntimeError):
    """Raised when live state no longer matches the reviewed Step 23B contract."""


_STEP23A_MODULE: ModuleType | None = None


def _load_step23a_module() -> ModuleType:
    """Import the reviewed Step 23A preflight module without treating scripts as a package."""
    global _STEP23A_MODULE
    if _STEP23A_MODULE is not None:
        return _STEP23A_MODULE
    spec = importlib.util.spec_from_file_location(
        "audit_step23a_legacy_reading_order_preflight",
        STEP23A_SCRIPT,
    )
    if spec is None or spec.loader is None:
        raise MigrationInvariantError("unable to load the Step 23A preflight module")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    _STEP23A_MODULE = module
    return module


def _json_value(value: object) -> object:
    """Convert datetime values to ISO-8601 JSON values."""
    if isinstance(value, datetime):
        return value.isoformat()
    return value


def _stable_hash(value: object) -> str:
    """Fingerprint one JSON-serializable mutation-relevant payload."""
    payload = json.dumps(
        value,
        sort_keys=True,
        separators=(",", ":"),
        default=_json_value,
    )
    return sha256(payload.encode("utf-8")).hexdigest()


def _as_dict(value: object, *, label: str) -> dict[str, object]:
    """Return a JSON object or raise a contract error."""
    if not isinstance(value, dict):
        raise MigrationInvariantError(f"{label} must be a JSON object")
    return cast(dict[str, object], value)


def _as_list(value: object, *, label: str) -> list[object]:
    """Return a JSON array or raise a contract error."""
    if not isinstance(value, list):
        raise MigrationInvariantError(f"{label} must be a JSON array")
    return cast(list[object], value)


def _as_int(value: object, *, label: str) -> int:
    """Return an integer or raise a contract error."""
    if not isinstance(value, int) or isinstance(value, bool):
        raise MigrationInvariantError(f"{label} must be an integer")
    return value


def _as_str(value: object, *, label: str) -> str:
    """Return a string or raise a contract error."""
    if not isinstance(value, str) or not value:
        raise MigrationInvariantError(f"{label} must be a non-empty string")
    return value


def load_reviewed_step23a_contract() -> dict[str, object]:
    """Load the reviewed Step 23A evidence that defines the Step 23B contract."""
    payload = json.loads(STEP23A_EVIDENCE.read_text(encoding="utf-8"))
    evidence = _as_dict(payload, label="Step 23A evidence")
    reconciliation = _as_dict(evidence.get("reconciliation"), label="reconciliation")
    token = _as_str(reconciliation.get("snapshot_token"), label="reviewed snapshot token")
    if token != REVIEWED_STEP23A_SNAPSHOT_TOKEN:
        raise MigrationInvariantError(
            "checked-in Step 23A evidence token no longer matches the reviewed token"
        )
    return evidence


def reviewed_reading_plan_order_rows(evidence: dict[str, object]) -> list[dict[str, object]]:
    """Return the nine reviewed reading_plan_order dependency rows."""
    overlap = _as_list(evidence.get("dependency_overlap"), label="dependency_overlap")
    rows: list[dict[str, object]] = []
    for raw in overlap:
        row = _as_dict(raw, label="dependency overlap row")
        if row.get("step14_classification") == "reading_plan_order":
            rows.append(row)
    if len(rows) != 9:
        raise MigrationInvariantError(
            f"Step 23A evidence must contain exactly 9 reading_plan_order rows, found {len(rows)}"
        )
    return rows


def reviewed_standalone_rows(evidence: dict[str, object]) -> list[dict[str, object]]:
    """Return the four standalone prerequisites that must survive migration."""
    overlap = _as_list(evidence.get("dependency_overlap"), label="dependency_overlap")
    rows: list[dict[str, object]] = []
    for raw in overlap:
        row = _as_dict(raw, label="dependency overlap row")
        if row.get("step14_classification") == "standalone_prerequisite":
            rows.append(row)
    ids = [_as_int(row.get("dependency_id"), label="standalone dependency id") for row in rows]
    if ids != [18, 19, 20, 21]:
        raise MigrationInvariantError(
            f"Step 23A standalone prerequisite IDs drifted: {ids}"
        )
    return rows


def reviewed_rule_by_dependency(evidence: dict[str, object]) -> dict[int, dict[str, object]]:
    """Return linked ContinuityRule rows keyed by legacy dependency id."""
    overlap = _as_list(
        evidence.get("continuity_rule_overlap"),
        label="continuity_rule_overlap",
    )
    mapping: dict[int, dict[str, object]] = {}
    for raw in overlap:
        row = _as_dict(raw, label="continuity rule overlap row")
        dependency_id = _as_int(row.get("legacy_dependency_id"), label="legacy_dependency_id")
        mapping[dependency_id] = row
    return mapping


def _plan_fingerprint(plan: ContinuityPlan) -> str:
    """Fingerprint one persisted Reading Plan's migration-owned structure."""
    return _stable_hash(
        {
            "id": plan.id,
            "name": plan.name,
            "ordering_mode": plan.ordering_mode,
            "nodes": plan.nodes_json,
            "lanes": plan.lanes_json,
        }
    )


def _stale_snapshot_error(live_token: str, accepted_token: str) -> MigrationInvariantError:
    """Return the fail-closed snapshot-guard error."""
    return MigrationInvariantError(
        f"{STALE_SNAPSHOT_MESSAGE} "
        f"live_token={live_token} accepted_token={accepted_token} "
        f"reviewed_token={REVIEWED_STEP23A_SNAPSHOT_TOKEN}"
    )


def _factual_thread_rows(threads: list[object]) -> list[dict[str, object]]:
    """Return thread rows with persisted blocked flags removed."""
    factual: list[dict[str, object]] = []
    for raw in threads:
        row = _as_dict(raw, label="reader thread row")
        factual.append({key: value for key, value in row.items() if key != "is_blocked"})
    return factual


def _reader_hashes(reader_state: dict[str, object]) -> dict[str, str]:
    """Return protected factual hashes from a Step 23A reader-state object."""
    return {
        "issue_state_hash": _as_str(reader_state.get("issue_state_hash"), label="issue_state_hash"),
        "event_state_hash": _as_str(reader_state.get("event_state_hash"), label="event_state_hash"),
        "identity_state_hash": _as_str(
            reader_state.get("identity_state_hash"),
            label="identity_state_hash",
        ),
        "thread_factual_hash": _stable_hash(
            _factual_thread_rows(_as_list(reader_state.get("threads"), label="reader threads"))
        ),
    }


def _eligibility_projection(rows: list[object]) -> list[dict[str, object]]:
    """Return the eligibility fields compared across apply and rollback."""
    projected: list[dict[str, object]] = []
    for raw in rows:
        row = _as_dict(raw, label="eligibility row")
        blockers = _as_list(row.get("blockers"), label="eligibility blockers")
        projected.append(
            {
                "thread_id": row.get("thread_id"),
                "next_unread_issue_id": row.get("next_unread_issue_id"),
                "authoritative_derived_eligible": row.get("authoritative_derived_eligible"),
                "persisted_is_blocked": row.get("persisted_is_blocked"),
                "persisted_vs_derived_mismatch": row.get("persisted_vs_derived_mismatch"),
                "surviving_standalone_prerequisites_blocking": row.get(
                    "surviving_standalone_prerequisites_blocking"
                ),
                "blocker_rule_ids": [
                    _as_int(
                        _as_dict(blocker, label="blocker").get("rule_id"),
                        label="blocker rule_id",
                    )
                    for blocker in blockers
                ],
            }
        )
    return projected


def _compare_eligibility(
    *,
    before: list[object],
    after: list[object],
    retired_rule_ids: set[int],
) -> list[dict[str, object]]:
    """Prove informational migration did not introduce unexpected eligibility changes.

    The nine reviewed reading_plan_order ContinuityRules are expected to disappear.
    Next unread issue identity, standalone blockers, and any newly added blockers
    must stay exact. Persisted blocked state must agree with derived eligibility
    after reconciliation.
    """
    before_rows = {
        _as_int(row.get("thread_id"), label="before thread_id"): row
        for raw in before
        for row in [_as_dict(raw, label="before eligibility")]
    }
    after_rows = {
        _as_int(row.get("thread_id"), label="after thread_id"): row
        for raw in after
        for row in [_as_dict(raw, label="after eligibility")]
    }
    if set(before_rows) != set(after_rows):
        raise MigrationInvariantError(
            "eligibility thread set changed during migration: "
            f"before={sorted(before_rows)} after={sorted(after_rows)}"
        )
    expected_delta: list[dict[str, object]] = []
    for thread_id, before_row in before_rows.items():
        after_row = after_rows[thread_id]
        if before_row.get("next_unread_issue_id") != after_row.get("next_unread_issue_id"):
            raise MigrationInvariantError(
                f"thread {thread_id} next unread issue changed during migration"
            )
        if before_row.get("surviving_standalone_prerequisites_blocking") != after_row.get(
            "surviving_standalone_prerequisites_blocking"
        ):
            raise MigrationInvariantError(
                f"thread {thread_id} standalone blockers changed during migration"
            )
        if after_row.get("persisted_vs_derived_mismatch") is True:
            raise MigrationInvariantError(
                f"thread {thread_id} persisted blocked state disagrees with derived eligibility"
            )
        before_blockers = {
            _as_int(
                _as_dict(blocker, label="before blocker").get("rule_id"),
                label="before blocker rule_id",
            )
            for blocker in _as_list(before_row.get("blockers"), label="before blockers")
        }
        after_blockers = {
            _as_int(
                _as_dict(blocker, label="after blocker").get("rule_id"),
                label="after blocker rule_id",
            )
            for blocker in _as_list(after_row.get("blockers"), label="after blockers")
        }
        added = after_blockers - before_blockers
        if added:
            raise MigrationInvariantError(
                f"thread {thread_id} gained unexpected blockers {sorted(added)}"
            )
        removed = before_blockers - after_blockers
        unexpected_removed = removed - retired_rule_ids
        if unexpected_removed:
            raise MigrationInvariantError(
                f"thread {thread_id} lost unexpected blockers {sorted(unexpected_removed)}"
            )
        if removed:
            expected_delta.append(
                {
                    "thread_id": thread_id,
                    "removed_reading_plan_order_rule_ids": sorted(removed),
                    "next_unread_issue_id": after_row.get("next_unread_issue_id"),
                    "authoritative_derived_eligible_before": before_row.get(
                        "authoritative_derived_eligible"
                    ),
                    "authoritative_derived_eligible_after": after_row.get(
                        "authoritative_derived_eligible"
                    ),
                }
            )
    return expected_delta


async def run_step23a_preflight(db: AsyncSession) -> dict[str, object]:
    """Re-run the reviewed Step 23A read-only preflight against the current session."""
    module = _load_step23a_module()
    snapshot = await module.capture_snapshot(db, user_id=module.USER_ID)
    step14_index = module._load_json(module.STEP14_INDEX)
    return cast(
        dict[str, object],
        module.build_report(
            snapshot,
            step14_index=step14_index,
            base_main_sha=module._git_head(),
        ),
    )


async def build_legacy_reading_order_dry_run(db: AsyncSession) -> dict[str, object]:
    """Inspect the live Step 23A contract without performing writes."""
    evidence = load_reviewed_step23a_contract()
    report = await run_step23a_preflight(db)
    reconciliation = _as_dict(report.get("reconciliation"), label="live reconciliation")
    live_token = _as_str(reconciliation.get("snapshot_token"), label="live snapshot token")
    errors = [str(error) for error in _as_list(report.get("errors"), label="preflight errors")]
    ok = report.get("result") == "PASS" and not errors
    return {
        "ok": ok,
        "step": "23B",
        "mode": "dry-run",
        "read_only": True,
        "errors": errors,
        "snapshot_token": live_token,
        "reviewed_snapshot_token": REVIEWED_STEP23A_SNAPSHOT_TOKEN,
        "snapshot_guard_passed": live_token == REVIEWED_STEP23A_SNAPSHOT_TOKEN,
        "legacy_reading_orders": report.get("legacy_reading_orders"),
        "dependency_overlap": report.get("dependency_overlap"),
        "continuity_rule_overlap": report.get("continuity_rule_overlap"),
        "proposed_canonical_targets": report.get("proposed_canonical_targets"),
        "reader_state": report.get("reader_state"),
        "eligibility_baseline": report.get("eligibility_baseline"),
        "reconciliation": reconciliation,
        "safety": {
            "production_mutated": False,
            "legacy_reading_orders_retained_for_rollback": True,
            "canonical_authority_after_apply": "informational_reading_plans",
            "ultimate_universe_cutover_started": False,
            "architecture_hold_2363_lifted": False,
            "reviewed_evidence_path": str(STEP23A_EVIDENCE.relative_to(ROOT)),
            "reviewed_evidence_result": evidence.get("result"),
        },
    }


async def _acquire_migration_locks(
    db: AsyncSession,
    *,
    user_id: int,
    order_ids: tuple[int, ...],
    dependency_ids: tuple[int, ...],
) -> None:
    """Lock migration-owned rows and the canonical reader-plan advisory lock."""
    await db.execute(select(func.pg_advisory_xact_lock(CONTINUITY_LOCK_NAMESPACE, user_id)))
    if order_ids:
        await db.execute(
            select(ReadingOrder.id)
            .where(ReadingOrder.user_id == user_id, ReadingOrder.id.in_(order_ids))
            .with_for_update()
        )
        await db.execute(
            select(ReadingOrderItem.id)
            .where(ReadingOrderItem.reading_order_id.in_(order_ids))
            .with_for_update()
        )
    if dependency_ids:
        await db.execute(
            select(Dependency.id).where(Dependency.id.in_(dependency_ids)).with_for_update()
        )
        await db.execute(
            select(ContinuityRule.id)
            .where(ContinuityRule.legacy_dependency_id.in_(dependency_ids))
            .with_for_update()
        )
    await db.execute(
        select(ContinuityPlan.id).where(ContinuityPlan.user_id == user_id).with_for_update()
    )


def _validate_live_contract(
    report: dict[str, object],
    evidence: dict[str, object],
) -> tuple[list[dict[str, object]], list[dict[str, object]], set[int]]:
    """Validate live overlap rows against the exact reviewed Step 23A contract."""
    live_overlap = [
        _as_dict(row, label="live dependency overlap")
        for row in _as_list(report.get("dependency_overlap"), label="live dependency_overlap")
    ]
    live_rules = reviewed_rule_by_dependency(
        {"continuity_rule_overlap": report.get("continuity_rule_overlap")}
    )
    expected_order = reviewed_reading_plan_order_rows(evidence)
    expected_standalone = reviewed_standalone_rows(evidence)
    expected_rules = reviewed_rule_by_dependency(evidence)
    live_by_id = {
        _as_int(row.get("dependency_id"), label="live dependency_id"): row
        for row in live_overlap
    }
    retired_rule_ids: set[int] = set()
    for expected in expected_order:
        dependency_id = _as_int(expected.get("dependency_id"), label="reviewed dependency_id")
        live = live_by_id.get(dependency_id)
        if live is None:
            raise MigrationInvariantError(
                f"reviewed reading_plan_order dependency {dependency_id} is missing"
            )
        expected_edge = (
            expected.get("source_issue_id"),
            expected.get("target_issue_id"),
            expected.get("step14_classification"),
        )
        live_edge = (
            live.get("source_issue_id"),
            live.get("target_issue_id"),
            live.get("step14_classification"),
        )
        if live_edge != expected_edge:
            raise MigrationInvariantError(
                f"dependency {dependency_id} drifted: expected {expected_edge!r}, got {live_edge!r}"
            )
        expected_rule = expected_rules.get(dependency_id)
        live_rule = live_rules.get(dependency_id)
        if expected_rule is None or live_rule is None:
            raise MigrationInvariantError(
                f"dependency {dependency_id} is missing its linked ContinuityRule"
            )
        expected_rule_shape = (
            expected_rule.get("rule_id"),
            expected_rule.get("source_id"),
            expected_rule.get("target_id"),
            expected_rule.get("satisfaction_type"),
        )
        live_rule_shape = (
            live_rule.get("rule_id"),
            live_rule.get("source_id"),
            live_rule.get("target_id"),
            live_rule.get("satisfaction_type"),
        )
        if live_rule_shape != expected_rule_shape:
            raise MigrationInvariantError(
                f"linked ContinuityRule for dependency {dependency_id} drifted: "
                f"expected {expected_rule_shape!r}, got {live_rule_shape!r}"
            )
        retired_rule_ids.add(_as_int(expected_rule.get("rule_id"), label="retired rule id"))
    for expected in expected_standalone:
        dependency_id = _as_int(expected.get("dependency_id"), label="standalone dependency_id")
        live = live_by_id.get(dependency_id)
        if live is None:
            raise MigrationInvariantError(
                f"standalone prerequisite {dependency_id} is missing before apply"
            )
        if (
            live.get("source_issue_id"),
            live.get("target_issue_id"),
            live.get("step14_classification"),
        ) != (
            expected.get("source_issue_id"),
            expected.get("target_issue_id"),
            expected.get("step14_classification"),
        ):
            raise MigrationInvariantError(
                f"standalone prerequisite {dependency_id} changed before apply"
            )
    return expected_order, expected_standalone, retired_rule_ids


async def _row_snapshot(
    db: AsyncSession,
    *,
    order_ids: tuple[int, ...],
    dependency_ids: tuple[int, ...],
) -> dict[str, list[dict[str, object]]]:
    """Capture exact rollback rows for orders, items, dependencies, and rules."""
    orders = (
        await db.execute(
            select(ReadingOrder).where(ReadingOrder.id.in_(order_ids)).order_by(ReadingOrder.id)
        )
    ).scalars().all()
    items = (
        await db.execute(
            select(ReadingOrderItem)
            .where(ReadingOrderItem.reading_order_id.in_(order_ids))
            .order_by(ReadingOrderItem.reading_order_id, ReadingOrderItem.position)
        )
    ).scalars().all()
    dependencies = (
        await db.execute(
            select(Dependency).where(Dependency.id.in_(dependency_ids)).order_by(Dependency.id)
        )
    ).scalars().all()
    rules = (
        await db.execute(
            select(ContinuityRule)
            .where(ContinuityRule.legacy_dependency_id.in_(dependency_ids))
            .order_by(ContinuityRule.id)
        )
    ).scalars().all()
    return {
        "reading_orders": [
            {
                "id": order.id,
                "user_id": order.user_id,
                "name": order.name,
                "description": order.description,
            }
            for order in orders
        ],
        "reading_order_items": [
            {
                "id": item.id,
                "reading_order_id": item.reading_order_id,
                "thread_id": item.thread_id,
                "position": item.position,
                "issue_number": item.issue_number,
            }
            for item in items
        ],
        "dependencies": [
            {
                "id": dependency.id,
                "source_issue_id": dependency.source_issue_id,
                "target_issue_id": dependency.target_issue_id,
                "created_at": _json_value(dependency.created_at),
                "note": dependency.note,
            }
            for dependency in dependencies
        ],
        "continuity_rules": [
            {
                "id": rule.id,
                "user_id": rule.user_id,
                "legacy_dependency_id": rule.legacy_dependency_id,
                "source_type": rule.source_type,
                "source_id": rule.source_id,
                "target_type": rule.target_type,
                "target_id": rule.target_id,
                "satisfaction_type": rule.satisfaction_type,
                "checkpoint_issue_id": rule.checkpoint_issue_id,
                "convergence_targets": rule.convergence_targets,
                "note": rule.note,
                "created_at": _json_value(rule.created_at),
                "updated_at": _json_value(rule.updated_at),
            }
            for rule in rules
        ],
    }


def _writer_nodes(target: dict[str, object]) -> list[ContinuityPlanNode]:
    """Build canonical writer nodes from one Step 23A proposed plan."""
    payload = _as_dict(target.get("writer_payload"), label="writer_payload")
    nodes: list[ContinuityPlanNode] = []
    for raw in _as_list(payload.get("nodes"), label="writer nodes"):
        node_payload = _as_dict(raw, label="writer node")
        nodes.append(ContinuityPlanNode.model_validate(node_payload))
    return nodes


def _writer_lanes(target: dict[str, object]) -> list[ContinuityPlanLane]:
    """Build canonical writer lanes from one Step 23A proposed plan."""
    payload = _as_dict(target.get("writer_payload"), label="writer_payload")
    return [
        ContinuityPlanLane.model_validate(_as_dict(raw, label="writer lane"))
        for raw in _as_list(payload.get("lanes"), label="writer lanes")
    ]


def _parse_datetime(value: object) -> datetime:
    """Parse one captured ISO timestamp."""
    if not isinstance(value, str):
        raise MigrationInvariantError(f"expected ISO timestamp, got {value!r}")
    return datetime.fromisoformat(value)


async def apply_legacy_reading_order_migration(
    db: AsyncSession,
    *,
    accepted_snapshot_token: str,
    require_reviewed_token: bool = True,
) -> dict[str, object]:
    """Apply the reviewed three-order informational migration atomically.

    Args:
        db: Caller-owned transaction.
        accepted_snapshot_token: Token the operator claims matches the reviewed
            Step 23A snapshot. This is compared exactly to a fresh locked
            preflight; a new token is never generated and accepted.
        require_reviewed_token: When True (CLI/production-shaped apply), the
            accepted token must also equal the reviewed Step 23A token.

    Returns:
        Machine-readable apply receipt sufficient for exact rollback.

    Raises:
        MigrationInvariantError: Snapshot drift, contract mismatch, or an
            unexpected factual/eligibility change.
    """
    if not accepted_snapshot_token:
        raise MigrationInvariantError("apply requires an explicit accepted snapshot token")
    if require_reviewed_token and accepted_snapshot_token != REVIEWED_STEP23A_SNAPSHOT_TOKEN:
        raise _stale_snapshot_error("(not evaluated)", accepted_snapshot_token)

    evidence = load_reviewed_step23a_contract()
    expected_order_rows = reviewed_reading_plan_order_rows(evidence)
    expected_standalone_rows_ = reviewed_standalone_rows(evidence)
    contract_order_ids = tuple(
        _as_int(order.get("reading_order_id"), label="reviewed reading_order_id")
        for raw in _as_list(evidence.get("legacy_reading_orders"), label="legacy_reading_orders")
        for order in [_as_dict(raw, label="reviewed reading order")]
    )
    contract_dependency_ids = tuple(
        sorted(
            [
                *(_as_int(row.get("dependency_id"), label="retired id") for row in expected_order_rows),
                *(
                    _as_int(row.get("dependency_id"), label="standalone id")
                    for row in expected_standalone_rows_
                ),
            ]
        )
    )
    module = _load_step23a_module()
    user_id = int(module.USER_ID)
    await _acquire_migration_locks(
        db,
        user_id=user_id,
        order_ids=contract_order_ids,
        dependency_ids=contract_dependency_ids,
    )

    preflight = await build_legacy_reading_order_dry_run(db)
    live_token = _as_str(preflight.get("snapshot_token"), label="locked snapshot token")
    if live_token != accepted_snapshot_token:
        raise _stale_snapshot_error(live_token, accepted_snapshot_token)
    if require_reviewed_token and live_token != REVIEWED_STEP23A_SNAPSHOT_TOKEN:
        raise _stale_snapshot_error(live_token, accepted_snapshot_token)
    if preflight.get("ok") is not True:
        raise MigrationInvariantError(
            f"Step 23A preflight is not clean: {preflight.get('errors')!r}"
        )

    _validate_live_contract(preflight, evidence)
    retired_ids = tuple(
        _as_int(row.get("dependency_id"), label="retired dependency id")
        for row in expected_order_rows
    )
    standalone_ids = tuple(
        _as_int(row.get("dependency_id"), label="standalone dependency id")
        for row in expected_standalone_rows_
    )
    retired_rule_ids: set[int] = set()
    expected_rules = reviewed_rule_by_dependency(evidence)
    for dependency_id in retired_ids:
        rule = expected_rules[dependency_id]
        retired_rule_ids.add(_as_int(rule.get("rule_id"), label="retired rule id"))

    rollback_rows = await _row_snapshot(
        db,
        order_ids=contract_order_ids,
        dependency_ids=contract_dependency_ids,
    )
    before_reader = _as_dict(preflight.get("reader_state"), label="before reader_state")
    before_hashes = _reader_hashes(before_reader)
    before_eligibility = _as_list(
        preflight.get("eligibility_baseline"),
        label="before eligibility",
    )

    created_plans: list[dict[str, object]] = []
    total_nodes = 0
    targets = [
        _as_dict(target, label="proposed plan")
        for target in _as_list(
            preflight.get("proposed_canonical_targets"),
            label="proposed_canonical_targets",
        )
    ]
    if len(targets) != 3:
        raise MigrationInvariantError(f"expected three proposed plans, found {len(targets)}")
    for target in targets:
        nodes = _writer_nodes(target)
        lanes = _writer_lanes(target)
        if any(node.is_checkpoint or node.convergence_gate for node in nodes):
            raise MigrationInvariantError("Step 23A proposed checkpoints/convergence unexpectedly")
        try:
            await validate_node_ownership(db, user_id=user_id, nodes=nodes)
        except HTTPException as exc:
            raise MigrationInvariantError(
                f"canonical plan writer rejected node ownership: {exc.detail!r}"
            ) from exc
        plan = ContinuityPlan(
            user_id=user_id,
            name=_as_str(target.get("name"), label="plan name"),
            ordering_mode="informational",
            lanes_json=[lane.model_dump() for lane in lanes],
            nodes_json=[node.model_dump() for node in nodes],
        )
        db.add(plan)
        await db.flush()
        compiled = await replace_compiled_rules(
            db,
            user_id=user_id,
            plan=plan,
            nodes=nodes,
            ordering_mode="informational",
        )
        if compiled is not True:
            raise MigrationInvariantError("canonical informational rule compile failed")
        marker = plan_rule_marker(plan.id)
        plan_rules = (
            await db.execute(
                select(ContinuityRule.id).where(
                    ContinuityRule.user_id == user_id,
                    ContinuityRule.note == marker,
                )
            )
        ).scalars().all()
        if plan_rules:
            raise MigrationInvariantError(
                "informational migration created unexpected plan-owned hard constraints: "
                f"{list(plan_rules)}"
            )
        created_plans.append(
            {
                "plan_id": plan.id,
                "name": plan.name,
                "ordering_mode": plan.ordering_mode,
                "node_count": len(nodes),
                "node_ids": [node.id for node in nodes],
                "issue_ids": [node.ref_id for node in nodes],
                "lane_ids": [lane.id for lane in lanes],
                "plan_fingerprint": _plan_fingerprint(plan),
                "plan_marker": marker,
                "plan_owned_hard_constraint_count": 0,
            }
        )
        total_nodes += len(nodes)

    if total_nodes != 140:
        raise MigrationInvariantError(f"expected 140 canonical nodes, created {total_nodes}")

    delete_result = await db.execute(delete(Dependency).where(Dependency.id.in_(retired_ids)))
    deleted_count = getattr(delete_result, "rowcount", None)
    if deleted_count != len(retired_ids):
        raise MigrationInvariantError(
            f"expected to retire {len(retired_ids)} reading_plan_order dependencies, "
            f"removed {deleted_count}"
        )
    await db.flush()
    remaining_retired = (
        await db.execute(select(Dependency.id).where(Dependency.id.in_(retired_ids)))
    ).scalars().all()
    if remaining_retired:
        raise MigrationInvariantError(
            f"retired dependencies survived apply: {list(remaining_retired)}"
        )
    remaining_retired_rules = (
        await db.execute(
            select(ContinuityRule.id).where(ContinuityRule.legacy_dependency_id.in_(retired_ids))
        )
    ).scalars().all()
    if remaining_retired_rules:
        raise MigrationInvariantError(
            f"retired ContinuityRules survived apply: {list(remaining_retired_rules)}"
        )

    surviving_standalone = (
        await db.execute(select(Dependency.id).where(Dependency.id.in_(standalone_ids)))
    ).scalars().all()
    if set(surviving_standalone) != set(standalone_ids):
        raise MigrationInvariantError(
            f"standalone prerequisites changed during apply: {sorted(surviving_standalone)}"
        )

    await refresh_user_blocked_status(user_id, db)
    await db.flush()

    after_report = await run_step23a_preflight(db)
    after_reader = _as_dict(after_report.get("reader_state"), label="after reader_state")
    after_hashes = _reader_hashes(after_reader)
    for key, before_hash in before_hashes.items():
        if after_hashes[key] != before_hash:
            raise MigrationInvariantError(
                f"migration changed protected factual reader state: {key}"
            )
    eligibility_delta = _compare_eligibility(
        before=before_eligibility,
        after=_as_list(after_report.get("eligibility_baseline"), label="after eligibility"),
        retired_rule_ids=retired_rule_ids,
    )
    rollback_guard_token = _stable_hash(
        {
            "plans": [
                {
                    "plan_id": plan["plan_id"],
                    "plan_fingerprint": plan["plan_fingerprint"],
                    "node_ids": plan["node_ids"],
                    "issue_ids": plan["issue_ids"],
                }
                for plan in created_plans
            ],
            "retired_dependency_ids": list(retired_ids),
            "preserved_standalone_ids": list(standalone_ids),
            "accepted_snapshot_token": accepted_snapshot_token,
        }
    )
    return {
        "ok": True,
        "step": "23B",
        "mode": "apply",
        "accepted_step23a_snapshot_token": accepted_snapshot_token,
        "reviewed_step23a_snapshot_token": REVIEWED_STEP23A_SNAPSHOT_TOKEN,
        "snapshot_guard_passed": True,
        "migration_timestamp": datetime.now().astimezone().isoformat(),
        "original_reading_order_ids": list(contract_order_ids),
        "legacy_reading_orders_retained": True,
        "canonical_authority": "informational_reading_plans",
        "original_reading_order_state": rollback_rows,
        "created_reading_plans": created_plans,
        "created_plan_ids": [plan["plan_id"] for plan in created_plans],
        "total_nodes_created": total_nodes,
        "retired_reading_plan_order_dependency_ids": list(retired_ids),
        "retired_continuity_rule_ids": sorted(retired_rule_ids),
        "preserved_standalone_prerequisite_ids": list(standalone_ids),
        "plan_owned_hard_constraints_created": 0,
        "protected_reader_state_hashes_before": before_hashes,
        "protected_reader_state_hashes_after": after_hashes,
        "eligibility_baseline": _eligibility_projection(before_eligibility),
        "eligibility_result": _eligibility_projection(
            _as_list(after_report.get("eligibility_baseline"), label="after eligibility")
        ),
        "eligibility_constraint_model_delta": eligibility_delta,
        "eligibility_baseline_hash": _stable_hash(_eligibility_projection(before_eligibility)),
        "eligibility_result_hash": _stable_hash(
            _eligibility_projection(
                _as_list(after_report.get("eligibility_baseline"), label="after eligibility")
            )
        ),
        "post_apply_canonical_plan_fingerprint": _stable_hash(
            [plan["plan_fingerprint"] for plan in created_plans]
        ),
        "rollback_guard_token": rollback_guard_token,
        "safety": {
            "production_apply_authorized": False,
            "legacy_reading_orders_deleted": False,
            "ultimate_universe_cutover_started": False,
            "architecture_hold_2363_lifted": False,
        },
    }


async def _restore_legacy_rules(
    db: AsyncSession,
    *,
    legacy_rules: list[object],
    dependency_ids: tuple[int, ...],
) -> set[int]:
    """Restore captured ContinuityRules, cooperating with the legacy mirror trigger."""
    restored_rule_ids: set[int] = set()
    for raw in legacy_rules:
        row = _as_dict(raw, label="legacy continuity rule")
        legacy_dependency_id = _as_int(
            row.get("legacy_dependency_id"),
            label="restored legacy_dependency_id",
        )
        rule = (
            await db.execute(
                select(ContinuityRule).where(
                    ContinuityRule.legacy_dependency_id == legacy_dependency_id
                )
            )
        ).scalar_one_or_none()
        if rule is None:
            rule = ContinuityRule(
                id=_as_int(row.get("id"), label="restored rule id"),
                user_id=_as_int(row.get("user_id"), label="restored rule user_id"),
                legacy_dependency_id=legacy_dependency_id,
                source_type=_as_str(row.get("source_type"), label="source_type"),
                source_id=_as_int(row.get("source_id"), label="source_id"),
                target_type=_as_str(row.get("target_type"), label="target_type"),
                target_id=_as_int(row.get("target_id"), label="target_id"),
                satisfaction_type=_as_str(
                    row.get("satisfaction_type"),
                    label="satisfaction_type",
                ),
                checkpoint_issue_id=row.get("checkpoint_issue_id"),
                convergence_targets=row.get("convergence_targets"),
                note=row.get("note") if row.get("note") is None or isinstance(row.get("note"), str) else None,
                created_at=_parse_datetime(row.get("created_at")),
                updated_at=_parse_datetime(row.get("updated_at")),
            )
            db.add(rule)
        else:
            expected_edge = (
                _as_int(row.get("user_id"), label="expected rule user_id"),
                _as_str(row.get("source_type"), label="expected source_type"),
                _as_int(row.get("source_id"), label="expected source_id"),
                _as_str(row.get("target_type"), label="expected target_type"),
                _as_int(row.get("target_id"), label="expected target_id"),
            )
            actual_edge = (
                rule.user_id,
                rule.source_type,
                rule.source_id,
                rule.target_type,
                rule.target_id,
            )
            if actual_edge != expected_edge:
                raise MigrationInvariantError(
                    "legacy dependency trigger restored an unexpected rule edge: "
                    f"expected {expected_edge!r}, got {actual_edge!r}"
                )
            rule.id = _as_int(row.get("id"), label="reconciled rule id")
            rule.satisfaction_type = _as_str(
                row.get("satisfaction_type"),
                label="reconciled satisfaction_type",
            )
            rule.checkpoint_issue_id = row.get("checkpoint_issue_id") if isinstance(
                row.get("checkpoint_issue_id"), int
            ) or row.get("checkpoint_issue_id") is None else None
            rule.convergence_targets = row.get("convergence_targets")
            note = row.get("note")
            rule.note = note if note is None or isinstance(note, str) else None
            rule.created_at = _parse_datetime(row.get("created_at"))
            rule.updated_at = _parse_datetime(row.get("updated_at"))
        restored_rule_ids.add(_as_int(row.get("id"), label="restored rule id"))
    await db.flush()
    actual_restored = set(
        (
            await db.execute(
                select(ContinuityRule.id).where(
                    ContinuityRule.legacy_dependency_id.in_(dependency_ids)
                )
            )
        ).scalars().all()
    )
    if actual_restored != restored_rule_ids:
        raise MigrationInvariantError(
            "rollback failed to restore exact legacy continuity rules: "
            f"{sorted(actual_restored)}"
        )
    return restored_rule_ids


async def rollback_legacy_reading_order_migration(
    db: AsyncSession,
    *,
    receipt: dict[str, object],
) -> dict[str, object]:
    """Restore the exact pre-migration compatibility state captured in the receipt."""
    accepted_token = _as_str(
        receipt.get("accepted_step23a_snapshot_token") or receipt.get("accepted_snapshot_token"),
        label="receipt snapshot token",
    )
    expected_guard = _as_str(receipt.get("rollback_guard_token"), label="rollback_guard_token")
    created_plans = [
        _as_dict(plan, label="receipt plan")
        for plan in _as_list(receipt.get("created_reading_plans"), label="created_reading_plans")
    ]
    if len(created_plans) != 3:
        raise MigrationInvariantError("apply receipt is missing the three created plans")
    original_state = _as_dict(
        receipt.get("original_reading_order_state"),
        label="original_reading_order_state",
    )
    retired_ids = tuple(
        _as_int(dependency_id, label="retired dependency id")
        for dependency_id in _as_list(
            receipt.get("retired_reading_plan_order_dependency_ids"),
            label="retired dependency ids",
        )
    )
    standalone_ids = tuple(
        _as_int(dependency_id, label="preserved standalone id")
        for dependency_id in _as_list(
            receipt.get("preserved_standalone_prerequisite_ids"),
            label="preserved standalone ids",
        )
    )
    module = _load_step23a_module()
    user_id = int(module.USER_ID)
    order_ids = tuple(
        _as_int(order_id, label="original reading order id")
        for order_id in _as_list(
            receipt.get("original_reading_order_ids"),
            label="original_reading_order_ids",
        )
    )
    await _acquire_migration_locks(
        db,
        user_id=user_id,
        order_ids=order_ids,
        dependency_ids=(*retired_ids, *standalone_ids),
    )

    live_plans: list[ContinuityPlan] = []
    for plan_row in created_plans:
        plan_id = _as_int(plan_row.get("plan_id"), label="receipt plan_id")
        plan = (
            await db.execute(
                select(ContinuityPlan).where(
                    ContinuityPlan.id == plan_id,
                    ContinuityPlan.user_id == user_id,
                )
            )
        ).scalar_one_or_none()
        if plan is None:
            raise MigrationInvariantError(
                f"migrated Reading Plan {plan_id} no longer exists; "
                "refusing automatic rollback"
            )
        expected_fingerprint = _as_str(
            plan_row.get("plan_fingerprint"),
            label="receipt plan_fingerprint",
        )
        if _plan_fingerprint(plan) != expected_fingerprint:
            raise MigrationInvariantError(
                "migrated Reading Plan was edited after cutover; "
                "refusing automatic rollback"
            )
        if plan.ordering_mode != "informational":
            raise MigrationInvariantError(
                "plan ordering mode changed after cutover; refusing automatic rollback"
            )
        marker = plan_rule_marker(plan.id)
        plan_rules = (
            await db.execute(
                select(ContinuityRule.id).where(
                    ContinuityRule.user_id == user_id,
                    ContinuityRule.note == marker,
                )
            )
        ).scalars().all()
        if plan_rules:
            raise MigrationInvariantError(
                "migration-owned rule state changed after cutover; "
                "refusing automatic rollback"
            )
        live_plans.append(plan)

    current_standalone = set(
        (
            await db.execute(select(Dependency.id).where(Dependency.id.in_(standalone_ids)))
        ).scalars().all()
    )
    if current_standalone != set(standalone_ids):
        raise MigrationInvariantError(
            "standalone prerequisites changed after migration; refusing automatic rollback"
        )
    conflicting = (
        await db.execute(select(Dependency.id).where(Dependency.id.in_(retired_ids)))
    ).scalars().all()
    if conflicting:
        raise MigrationInvariantError(
            "retired reading_plan_order dependency IDs are no longer free; "
            "refusing automatic rollback"
        )

    live_guard = _stable_hash(
        {
            "plans": [
                {
                    "plan_id": plan.id,
                    "plan_fingerprint": _plan_fingerprint(plan),
                    "node_ids": [
                        node.get("id")
                        for node in plan.nodes_json
                    ],
                    "issue_ids": [
                        node.get("ref_id")
                        for node in plan.nodes_json
                    ],
                }
                for plan in live_plans
            ],
            "retired_dependency_ids": list(retired_ids),
            "preserved_standalone_ids": list(standalone_ids),
            "accepted_snapshot_token": accepted_token,
        }
    )
    if live_guard != expected_guard:
        raise MigrationInvariantError(
            "protected migration-owned metadata no longer matches the receipt; "
            "refusing automatic rollback"
        )

    for plan in live_plans:
        await db.delete(plan)
    await db.flush()
    remaining_plans = (
        await db.execute(
            select(ContinuityPlan.id).where(
                ContinuityPlan.id.in_(
                    [_as_int(plan.get("plan_id"), label="removed plan id") for plan in created_plans]
                )
            )
        )
    ).scalars().all()
    if remaining_plans:
        raise MigrationInvariantError(
            f"migration-created plans survived rollback: {list(remaining_plans)}"
        )

    restored_dependencies = _as_list(original_state.get("dependencies"), label="captured dependencies")
    retired_dependency_rows = [
        _as_dict(row, label="captured dependency")
        for row in restored_dependencies
        if _as_int(
            _as_dict(row, label="captured dependency").get("id"),
            label="captured dependency id",
        )
        in set(retired_ids)
    ]
    for row in retired_dependency_rows:
        db.add(
            Dependency(
                id=_as_int(row.get("id"), label="restored dependency id"),
                source_issue_id=_as_int(row.get("source_issue_id"), label="source_issue_id"),
                target_issue_id=_as_int(row.get("target_issue_id"), label="target_issue_id"),
                created_at=_parse_datetime(row.get("created_at")),
                note=row.get("note") if row.get("note") is None or isinstance(row.get("note"), str) else None,
            )
        )
    await db.flush()

    restored_rule_ids = await _restore_legacy_rules(
        db,
        legacy_rules=[
            row
            for row in _as_list(
                original_state.get("continuity_rules"),
                label="captured continuity rules",
            )
            if _as_int(
                _as_dict(row, label="captured rule").get("legacy_dependency_id"),
                label="captured rule dependency id",
            )
            in set(retired_ids)
        ],
        dependency_ids=retired_ids,
    )
    await refresh_user_blocked_status(user_id, db)
    await db.flush()

    restored_ids = set(
        (await db.execute(select(Dependency.id).where(Dependency.id.in_(retired_ids)))).scalars().all()
    )
    if restored_ids != set(retired_ids):
        raise MigrationInvariantError(
            f"rollback failed to restore legacy dependencies: {sorted(restored_ids)}"
        )
    surviving_standalone = set(
        (
            await db.execute(select(Dependency.id).where(Dependency.id.in_(standalone_ids)))
        ).scalars().all()
    )
    if surviving_standalone != set(standalone_ids):
        raise MigrationInvariantError(
            f"rollback mutated standalone prerequisites: {sorted(surviving_standalone)}"
        )

    after_report = await run_step23a_preflight(db)
    after_reader = _as_dict(after_report.get("reader_state"), label="rollback reader_state")
    after_hashes = _reader_hashes(after_reader)
    before_hashes = {
        key: _as_str(value, label=key)
        for key, value in _as_dict(
            receipt.get("protected_reader_state_hashes_before"),
            label="receipt before hashes",
        ).items()
    }
    factual_unchanged = after_hashes == before_hashes
    eligibility_restored = None
    if factual_unchanged:
        eligibility_restored = _eligibility_projection(
            _as_list(after_report.get("eligibility_baseline"), label="rollback eligibility")
        )
        expected_eligibility = receipt.get("eligibility_baseline")
        if eligibility_restored != expected_eligibility:
            raise MigrationInvariantError(
                "eligibility after rollback does not match the captured pre-apply baseline"
            )

    return {
        "ok": True,
        "step": "23B",
        "mode": "rollback",
        "removed_plan_ids": [plan.id for plan in live_plans],
        "restored_dependency_ids": sorted(restored_ids),
        "restored_continuity_rule_ids": sorted(restored_rule_ids),
        "preserved_standalone_prerequisite_ids": list(standalone_ids),
        "legacy_reading_orders_retained": True,
        "protected_reader_state_hashes": after_hashes,
        "factual_reader_state_unchanged": factual_unchanged,
        "eligibility_restored_to_pre_apply_baseline": (
            factual_unchanged and eligibility_restored == receipt.get("eligibility_baseline")
        ),
        "rollback_guard_token": expected_guard,
    }
