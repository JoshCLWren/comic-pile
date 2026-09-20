"""Shared scaffolding for reader-order / universe production migrations.

Centralizes the duplicated clean/snapshot gates, blocked-refresh helpers,
and safe id coercion that was previously copied across six migration services.
"""

from __future__ import annotations

from datetime import datetime
from hashlib import sha256
import json

from sqlalchemy.ext.asyncio import AsyncSession

from app.models.continuity_plan import ContinuityPlan
from app.models.continuity_rule import ContinuityRule
from app.models.dependency import Dependency
from comic_pile.dependencies import (
    _get_blocked_thread_ids_uncached,
    _invalidate_continuity_snapshot,
    refresh_user_blocked_status,
)
from comic_pile.queue import get_roll_pool


class MigrationInvariantError(RuntimeError):
    """Raised when live state no longer matches the reviewed migration contract."""


_DEPENDENCY_ID_BATCH_SIZE = 10_000


def json_value(value: object) -> object:
    """Convert datetime values to ISO-8601 for stable hashing."""
    if isinstance(value, datetime):
        return value.isoformat()
    return value


def stable_hash(value: object) -> str:
    """Fingerprint one JSON-serializable payload deterministically."""
    payload = json.dumps(
        value,
        sort_keys=True,
        separators=(",", ":"),
        default=json_value,
    )
    return sha256(payload.encode("utf-8")).hexdigest()


def legacy_prefix(content_hash: str) -> str:
    """Return the cbl-order source prefix for one content hash."""
    return f"cbl-order:source:{content_hash}:"


def dependency_id_batches(
    dependency_ids: set[int] | list[int],
) -> tuple[tuple[int, ...], ...]:
    """Split dependency IDs below asyncpg's 32,767 bind-argument limit."""
    ordered = sorted(set(dependency_ids))
    return tuple(
        tuple(ordered[offset : offset + _DEPENDENCY_ID_BATCH_SIZE])
        for offset in range(0, len(ordered), _DEPENDENCY_ID_BATCH_SIZE)
    )


def dep_snapshot(dependency: Dependency) -> dict[str, object]:
    """Return the stable dependency row snapshot used in dry-run receipts."""
    return {
        "id": dependency.id,
        "source_issue_id": dependency.source_issue_id,
        "target_issue_id": dependency.target_issue_id,
        "note": dependency.note,
        "created_at": json_value(dependency.created_at),
    }


def rule_snapshot(rule: ContinuityRule) -> dict[str, object]:
    """Return the stable continuity-rule row snapshot."""
    return {
        "id": rule.id,
        "legacy_dependency_id": rule.legacy_dependency_id,
        "source_type": rule.source_type,
        "source_id": rule.source_id,
        "target_type": rule.target_type,
        "target_id": rule.target_id,
        "satisfaction_type": rule.satisfaction_type,
        "checkpoint_issue_id": rule.checkpoint_issue_id,
        "convergence_targets": rule.convergence_targets,
        "note": rule.note,
        "created_at": json_value(rule.created_at),
        "updated_at": json_value(rule.updated_at),
    }


def plan_fingerprint(plan: ContinuityPlan) -> str:
    """Return the exact storage fingerprint of one Reading Plan."""
    return stable_hash(
        {
            "name": plan.name,
            "ordering_mode": plan.ordering_mode,
            "nodes": plan.nodes_json,
            "lanes": plan.lanes_json,
        }
    )


def plan_fingerprint_with_id(plan: ContinuityPlan) -> str:
    """Return the legacy fingerprint that includes plan.id (for 23B)."""
    return stable_hash(
        {
            "id": plan.id,
            "name": plan.name,
            "ordering_mode": plan.ordering_mode,
            "nodes": plan.nodes_json,
            "lanes": plan.lanes_json,
        }
    )


def plan_fingerprint_from_payload(payload: dict[str, object]) -> str:
    """Return the fingerprint a snapshot expects the migrated plan to store."""
    return stable_hash(
        {
            "name": payload["name"],
            "ordering_mode": payload["ordering_mode"],
            "nodes": payload["nodes"],
            "lanes": payload["lanes"],
        }
    )


def rule_descriptor(rule: ContinuityRule) -> dict[str, object]:
    """Return the blocking semantics of one compiled rule for fingerprinting."""
    return {
        "source_type": rule.source_type,
        "source_id": rule.source_id,
        "target_type": rule.target_type,
        "target_id": rule.target_id,
        "satisfaction_type": rule.satisfaction_type,
        "checkpoint_issue_id": rule.checkpoint_issue_id,
        "convergence_targets": rule.convergence_targets,
    }


def rules_fingerprint(rules: list[ContinuityRule]) -> str:
    """Return a stable fingerprint over an ordered set of compiled rules."""
    return stable_hash(
        [rule_descriptor(rule) for rule in sorted(rules, key=lambda row: row.id)]
    )


def planned_rule_descriptor(rule: dict[str, object]) -> dict[str, object]:
    """Project a dry-run planned rule into the compiled rule descriptor space."""
    return {
        "source_type": rule["source_type"],
        "source_id": coerce_int(rule["source_id"]),
        "target_type": rule["target_type"],
        "target_id": coerce_int(rule["target_id"]),
        "satisfaction_type": rule["satisfaction_type"],
        "checkpoint_issue_id": None,
        "convergence_targets": rule.get("convergence_targets"),
    }


def require_clean_snapshot(snapshot: dict[str, object]) -> None:
    """Validate snapshot is clean; raise MigrationInvariantError otherwise."""
    if snapshot.get("ok") is not True or not snapshot.get("snapshot_token"):
        raise MigrationInvariantError(
            f"snapshot is not clean: {snapshot.get('errors')!r}"
        )


def require_snapshot_token(snapshot: dict[str, object]) -> str:
    """Validate snapshot has token and clean ok; return token."""
    token = snapshot.get("snapshot_token")
    if not isinstance(token, str) or not token:
        raise MigrationInvariantError("dry-run snapshot is missing snapshot_token")
    if snapshot.get("ok") is not True:
        raise MigrationInvariantError(
            f"dry-run snapshot was not clean: {snapshot.get('errors')!r}"
        )
    return token


def coerce_int(value: object, *, label: str = "value") -> int:
    """Coerce an object to int, rejecting bool and non-int."""
    if isinstance(value, bool) or not isinstance(value, int):
        raise MigrationInvariantError(f"{label} must be an integer, got {value!r}")
    return value


def coerce_int_from_mapping(
    mapping: dict[str, object], key: str, *, label: str | None = None
) -> int:
    """Coerce mapping[key] to int."""
    value = mapping.get(key)
    return coerce_int(value, label=label or key)


def coerce_optional_int(value: object) -> int | None:
    """Coerce optional int, returning None for None."""
    if value is None:
        return None
    if isinstance(value, bool) or not isinstance(value, int):
        raise MigrationInvariantError(f"expected int or None, got {value!r}")
    return value


def invalidate_continuity_snapshot(user_id: int, db: AsyncSession) -> None:
    """Invalidate continuity snapshot for user (sync helper)."""
    _invalidate_continuity_snapshot(user_id, db)


async def current_roll_eligible(
    user_id: int, db: AsyncSession, affected_ids: set[int]
) -> tuple[set[int], list[int]]:
    """Return (blocked_ids, eligible_sorted) for affected threads."""
    blocked = await _get_blocked_thread_ids_uncached(user_id, db)
    roll_ids = {thread.id for thread in await get_roll_pool(user_id, db)}
    eligible = sorted(roll_ids & affected_ids)
    return blocked, eligible


async def refresh_blocked_status(user_id: int, db: AsyncSession) -> None:
    """Refresh persisted blocked status and flush."""
    await refresh_user_blocked_status(user_id, db)
    await db.flush()


async def assert_roll_eligibility_parity(
    user_id: int, db: AsyncSession, affected_ids: set[int]
) -> list[int]:
    """Assert persisted Roll eligibility matches uncached blocking.

    Returns the current eligible list or raises MigrationInvariantError.
    """
    blocked, eligible = await current_roll_eligible(user_id, db, affected_ids)
    derived = sorted(affected_ids - blocked)
    if eligible != derived:
        raise MigrationInvariantError(
            "persisted Roll eligibility differs from uncached unified blocking: "
            f"roll={eligible}, derived={derived}"
        )
    return eligible


# Re-export for snapshot equivalence checks that need get_blocked directly
get_blocked_thread_ids_uncached = _get_blocked_thread_ids_uncached
