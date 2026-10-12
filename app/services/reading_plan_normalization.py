"""Normalized Reading Plan membership orchestration.

Single home for rebuilding plan-to-Issue membership and plan source
provenance from canonical plan nodes, for explicit plan-to-Dependency
provenance links, and for progress derived from global Issue read state.

Scope notes (``docs/READING_GRAPH_PERSISTENCE_DESIGN.md``, Chunk 1):

- membership rebuild touches only rows owned by the saved plan; shared
  Issues, canonical Dependencies, and other plans' links are never modified;
- linking a Dependency never creates, modifies, or deletes the canonical
  edge and never changes Roll eligibility;
- Issue read state stays canonical and global; progress is derived, never
  separately persisted.
"""

from __future__ import annotations

from collections.abc import Collection
from copy import deepcopy
from dataclasses import dataclass
from datetime import UTC, datetime

from fastapi import HTTPException
from pydantic import ValidationError
from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.continuity_plan import ContinuityPlan
from app.models.continuity_rule import ContinuityRule
from app.models.custom_cbl import CustomCBLList
from app.models.dependency import Dependency
from app.models.issue import Issue
from app.models.reading_plan_membership import (
    ReadingPlanDependency,
    ReadingPlanIssue,
    ReadingPlanSource,
    ReadingPlanSourcePlacement,
)
from app.models.thread import Thread
from app.repositories import continuity_repository, reading_plan_repository
from app.schemas.continuity_plan import ContinuityPlanNode
from app.services.cbl_source_public import public_cbl_repository, public_cbl_source_path
from app.schemas.reading_plan_membership import (
    ReadingPlanDependencyLink,
    ReadingPlanMemberIssue,
    ReadingPlanMembershipResponse,
    ReadingPlanProgress,
    ReadingPlanSourcePlacementView,
    ReadingPlanSourceSnapshot,
)


def ensure_plan_issue_uniqueness(nodes: list[ContinuityPlanNode]) -> None:
    """Enforce the one-membership-per-canonical-issue invariant (#3037).

    Within one Reading Plan a canonical issue may appear at most once;
    repeated occurrences create ambiguous progress, ordering, dependency,
    inheritance, and editing semantics. This is the service-level gate all
    membership write paths funnel through (API, CBL adoption, migrations,
    prune flows) via :func:`rebuild_plan_membership`.

    Raises:
        HTTPException: 422 ``duplicate_plan_issue`` naming the first
            repeated issue reference, so callers get a domain error instead
            of an opaque database failure.
    """
    seen: set[int] = set()
    for node in nodes:
        if node.node_type != "issue":
            continue
        if node.ref_id in seen:
            raise HTTPException(
                status_code=422,
                detail={
                    "code": "duplicate_plan_issue",
                    "issue_id": node.ref_id,
                    "node_id": node.id,
                },
            )
        seen.add(node.ref_id)


@dataclass(frozen=True, slots=True)
class PlanConstraintSnapshot:
    """Membership and blocker identity for one plan at one moment.

    ``roll_blocking_pairs`` are canonical (non-``cbl-order``) Dependencies
    whose unread source currently blocks a member Thread's next unread issue.
    Plan-owned ContinuityRules are authoring records; after the Roll cutover
    they do not block unless compiled to a Dependency.
    """

    membership_issue_ids: tuple[int, ...]
    plan_owned_item_read_pairs: tuple[tuple[int, int], ...]
    plan_linked_dependency_pairs: tuple[tuple[int, int], ...]
    roll_blocking_pairs: tuple[tuple[int, int], ...]


@dataclass(frozen=True, slots=True)
class DroppedPlanSeries:
    """One series whose leftover JSON issues are trimmed to membership."""

    thread_id: int
    title: str
    issue_ids: tuple[int, ...]
    issue_numbers: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class PlanRecordBackup:
    """Pre-trim ``nodes_json`` and source rows for a documented rollback.

    Membership rows are not included because the membership-authoritative
    repair never mutates ``reading_plan_issues``. Rollback restores the plan
    record and source order only.
    """

    nodes_json: list[dict[str, object]]
    sources: tuple[dict[str, object], ...]
    placements: tuple[dict[str, object], ...]


@dataclass(frozen=True, slots=True)
class MembershipReconcileReport:
    """Outcome of aligning the plan record to ``reading_plan_issues``.

    ``reading_plan_issues`` is the intended membership (#3486). Extra issue
    nodes in ``nodes_json`` are stale leftovers from series removals. This
    repair trims the plan record and its source order to that table and never
    calls the strict compiler, so leftovers are not restored or compiled.

    Production apply of this report is a separate authorization gate.
    """

    plan_id: int
    membership_count: int
    json_issue_count_before: int
    json_issue_count_after: int
    skipped_missing_issue_ids: tuple[int, ...]
    skipped_non_issue_nodes: int
    invalid_node_count: int
    inserted_issue_ids: tuple[int, ...]
    removed_issue_ids: tuple[int, ...]
    dropped_json_issue_ids: tuple[int, ...]
    dropped_json_node_ids: tuple[str, ...]
    dropped_series: tuple[DroppedPlanSeries, ...]
    before: PlanConstraintSnapshot
    after: PlanConstraintSnapshot
    projected_thread_entry_pairs: tuple[tuple[int, int], ...]
    backup: PlanRecordBackup


def _snapshot_to_dict(snapshot: PlanConstraintSnapshot) -> dict[str, object]:
    """Serialize one constraint snapshot for dry-run reports."""
    return {
        "membership_issue_ids": list(snapshot.membership_issue_ids),
        "plan_owned_item_read_pairs": [list(pair) for pair in snapshot.plan_owned_item_read_pairs],
        "plan_linked_dependency_pairs": [
            list(pair) for pair in snapshot.plan_linked_dependency_pairs
        ],
        "roll_blocking_pairs": [list(pair) for pair in snapshot.roll_blocking_pairs],
    }


def _iso(value: datetime | None) -> str | None:
    """Serialize an optional datetime as ISO-8601."""
    if value is None:
        return None
    return value.isoformat()


def _parse_dt(value: object) -> datetime | None:
    """Parse an optional ISO-8601 datetime from a backup payload."""
    if value is None:
        return None
    if isinstance(value, datetime):
        return value
    if isinstance(value, str) and value:
        return datetime.fromisoformat(value)
    raise TypeError(f"expected datetime string, got {type(value)!r}")


def _backup_int(value: object, field: str) -> int:
    """Require a JSON integer field from a rollback payload."""
    if isinstance(value, bool) or not isinstance(value, int):
        raise TypeError(f"backup {field} must be an int")
    return value


def _source_row_to_dict(source: ReadingPlanSource) -> dict[str, object]:
    """Serialize one source snapshot for rollback."""
    return {
        "id": source.id,
        "plan_id": source.plan_id,
        "raw_source_path": source.raw_source_path,
        "repository": source.repository,
        "source_path": source.source_path,
        "revision_sha": source.revision_sha,
        "content_hash": source.content_hash,
        "cbl_source_list_id": source.cbl_source_list_id,
        "custom_cbl_list_id": source.custom_cbl_list_id,
        "adopted_at": _iso(source.adopted_at),
        "recorded_at": source.recorded_at.isoformat(),
        "metadata_json": source.metadata_json,
    }


def _placement_row_to_dict(
    placement: ReadingPlanSourcePlacement,
) -> dict[str, object]:
    """Serialize one source placement for rollback."""
    return {
        "id": placement.id,
        "plan_id": placement.plan_id,
        "occurrence_id": placement.occurrence_id,
        "plan_source_id": placement.plan_source_id,
        "source_position": placement.source_position,
    }


def backup_to_dict(backup: PlanRecordBackup) -> dict[str, object]:
    """Serialize a plan-record backup as JSON-ready data.

    Args:
        backup: Captured pre-trim plan record and source rows.

    Returns:
        Plain mapping suitable for a rollback receipt.
    """
    return {
        "nodes_json": backup.nodes_json,
        "sources": [dict(row) for row in backup.sources],
        "placements": [dict(row) for row in backup.placements],
    }


def backup_from_dict(payload: dict[str, object]) -> PlanRecordBackup:
    """Rehydrate a plan-record backup from a rollback receipt.

    Args:
        payload: Mapping produced by :func:`backup_to_dict`.

    Returns:
        Frozen backup matching the original capture.
    """
    nodes_raw = payload.get("nodes_json")
    sources_raw = payload.get("sources")
    placements_raw = payload.get("placements")
    nodes = [
        dict(node)
        for node in nodes_raw
        if isinstance(nodes_raw, list) and isinstance(node, dict)
    ] if isinstance(nodes_raw, list) else []
    sources = tuple(
        dict(row)
        for row in sources_raw
        if isinstance(sources_raw, list) and isinstance(row, dict)
    ) if isinstance(sources_raw, list) else ()
    placements = tuple(
        dict(row)
        for row in placements_raw
        if isinstance(placements_raw, list) and isinstance(row, dict)
    ) if isinstance(placements_raw, list) else ()
    return PlanRecordBackup(nodes_json=nodes, sources=sources, placements=placements)


def membership_report_to_dict(
    report: MembershipReconcileReport,
    *,
    include_backup: bool = False,
) -> dict[str, object]:
    """Serialize a membership reconcile report as JSON-ready data.

    Args:
        report: Apply or dry-run result.
        include_backup: When True, include the pre-trim plan record so apply
            receipts can roll back without a Neon branch.

    Returns:
        Plain mapping with list-encoded tuples.
    """
    payload: dict[str, object] = {
        "plan_id": report.plan_id,
        "membership_is_authoritative": True,
        "membership_count": report.membership_count,
        "json_issue_count_before": report.json_issue_count_before,
        "json_issue_count_after": report.json_issue_count_after,
        "skipped_missing_issue_ids": list(report.skipped_missing_issue_ids),
        "skipped_non_issue_nodes": report.skipped_non_issue_nodes,
        "invalid_node_count": report.invalid_node_count,
        "inserted_issue_ids": list(report.inserted_issue_ids),
        "removed_issue_ids": list(report.removed_issue_ids),
        "dropped_json_issue_ids": list(report.dropped_json_issue_ids),
        "dropped_json_node_ids": list(report.dropped_json_node_ids),
        "dropped_series": [
            {
                "thread_id": series.thread_id,
                "title": series.title,
                "issue_ids": list(series.issue_ids),
                "issue_numbers": list(series.issue_numbers),
            }
            for series in report.dropped_series
        ],
        "before": _snapshot_to_dict(report.before),
        "after": _snapshot_to_dict(report.after),
        "projected_thread_entry_pairs": [
            list(pair) for pair in report.projected_thread_entry_pairs
        ],
        "compiled_rules": False,
        "rollback": (
            "restore backup.nodes_json, reading_plan_sources, and "
            "reading_plan_source_placements; reading_plan_issues is unchanged"
        ),
    }
    if include_backup:
        payload["backup"] = backup_to_dict(report.backup)
    return payload


def parse_plan_nodes_json(nodes_json: object) -> tuple[list[ContinuityPlanNode], int]:
    """Parse persisted plan JSON nodes, counting rows that cannot validate.

    Args:
        nodes_json: Raw ``ContinuityPlan.nodes_json`` value.

    Returns:
        Validated nodes and the count of entries that could not be parsed.
    """
    if not isinstance(nodes_json, list):
        return [], 0
    nodes: list[ContinuityPlanNode] = []
    invalid = 0
    for raw in nodes_json:
        try:
            nodes.append(ContinuityPlanNode.model_validate(raw))
        except ValidationError:
            invalid += 1
    return nodes, invalid


def drop_issue_nodes_from_plan_json(
    nodes: list[dict[str, object]],
    *,
    drop_issue_ids: Collection[int],
    drop_node_ids: Collection[str] = (),
    drop_source_path: str | None = None,
    drop_source_positions: Collection[int] = (),
) -> list[dict[str, object]]:
    """Remove issue nodes for a series (or CBL exclude) from the plan record.

    Live series removal must update ``nodes_json`` in the same write that
    rebuilds membership and source order so the two representations cannot
    diverge again (#3486).

    Args:
        nodes: Stored plan node dicts.
        drop_issue_ids: Canonical issue ids being removed from the plan.
        drop_node_ids: Plan node ids to drop even when ``ref_id`` is missing.
        drop_source_path: Optional CBL source path whose excluded positions
            should also drop matching nodes.
        drop_source_positions: CBL source positions excluded from this commit.

    Returns:
        Remaining node dicts, preserving relative order.
    """
    drop_ids = {issue_id for issue_id in drop_issue_ids if issue_id > 0}
    drop_nodes = {node_id for node_id in drop_node_ids if node_id}
    drop_positions = set(drop_source_positions)
    kept: list[dict[str, object]] = []
    for node in nodes:
        node_id = str(node.get("id") or "")
        if node_id in drop_nodes:
            continue
        if str(node.get("node_type")) == "issue":
            ref_id = node.get("ref_id")
            if isinstance(ref_id, int) and ref_id in drop_ids:
                continue
        if drop_source_path is not None and drop_positions:
            placements = node.get("source_cbl_placements")
            matches_excluded = False
            if isinstance(placements, list):
                for placement in placements:
                    if not isinstance(placement, dict):
                        continue
                    position = placement.get("position")
                    if (
                        str(placement.get("source_path")) == drop_source_path
                        and isinstance(position, int)
                        and position in drop_positions
                    ):
                        matches_excluded = True
                        break
            if matches_excluded:
                continue
        kept.append(node)
    return kept


def trim_plan_nodes_json_to_membership(
    nodes_json: object,
    *,
    keep_issue_ids: Collection[int],
) -> tuple[list[dict[str, object]], tuple[int, ...], tuple[str, ...], int, int]:
    """Keep non-issue nodes and issue nodes whose ref is in membership.

    Args:
        nodes_json: Raw ``ContinuityPlan.nodes_json`` value.
        keep_issue_ids: Intended membership issue ids.

    Returns:
        Kept nodes, dropped issue ids, dropped node ids, skipped non-issue
        count, and invalid row count.
    """
    keep_ids = {issue_id for issue_id in keep_issue_ids if issue_id > 0}
    if not isinstance(nodes_json, list):
        return [], (), (), 0, 0
    kept: list[dict[str, object]] = []
    dropped_ids: list[int] = []
    dropped_node_ids: list[str] = []
    skipped_non_issue = 0
    invalid = 0
    for raw in nodes_json:
        if not isinstance(raw, dict):
            invalid += 1
            continue
        node_type = str(raw.get("node_type") or "")
        if node_type != "issue":
            skipped_non_issue += 1
            kept.append(raw)
            continue
        ref_id = raw.get("ref_id")
        node_id = str(raw.get("id") or "")
        if isinstance(ref_id, int) and ref_id in keep_ids:
            kept.append(raw)
            continue
        if isinstance(ref_id, int):
            dropped_ids.append(ref_id)
        else:
            invalid += 1
        if node_id:
            dropped_node_ids.append(node_id)
    unique_dropped = tuple(sorted(set(dropped_ids)))
    return kept, unique_dropped, tuple(dropped_node_ids), skipped_non_issue, invalid


async def _existing_issue_ids(
    db: AsyncSession, issue_ids: Collection[int]
) -> set[int]:
    """Return the subset of ``issue_ids`` that exist as Issue rows."""
    unique_ids = sorted({issue_id for issue_id in issue_ids if issue_id > 0})
    if not unique_ids:
        return set()
    return set(
        (await db.execute(select(Issue.id).where(Issue.id.in_(unique_ids)))).scalars().all()
    )


async def _roll_blocking_pairs_for_issues(
    db: AsyncSession,
    issue_ids: Collection[int],
) -> tuple[tuple[int, int], ...]:
    """Return live Roll-blocking pairs for Threads that own the given Issues."""
    if not issue_ids:
        return ()
    thread_ids = set(
        (
            await db.execute(
                select(Issue.thread_id).where(Issue.id.in_(list(issue_ids))).distinct()
            )
        ).scalars().all()
    )
    if not thread_ids:
        return ()
    rows = (
        await db.execute(
            select(Dependency.source_issue_id, Dependency.target_issue_id)
            .join(Thread, Thread.next_unread_issue_id == Dependency.target_issue_id)
            .join(Issue, Issue.id == Dependency.source_issue_id)
            .where(
                Thread.id.in_(list(thread_ids)),
                Issue.status != "read",
                or_(Dependency.note.is_(None), Dependency.note.not_like("cbl-order:%")),
            )
            .distinct()
        )
    ).all()
    return tuple(sorted((int(source_id), int(target_id)) for source_id, target_id in rows))


async def snapshot_plan_constraint_sets(
    db: AsyncSession,
    *,
    plan: ContinuityPlan,
    membership_issue_ids: Collection[int] | None = None,
) -> PlanConstraintSnapshot:
    """Snapshot membership and blocker identity for one plan.

    Args:
        db: Async database session.
        plan: Plan to inspect.
        membership_issue_ids: Override the membership set (dry-run of an
            intended membership without writing ``reading_plan_issues``).

    Returns:
        Frozen membership and blocker tuples.
    """
    if membership_issue_ids is None:
        member_ids = tuple(
            await reading_plan_repository.distinct_plan_issue_ids(db, plan_id=plan.id)
        )
    else:
        member_ids = tuple(sorted(membership_issue_ids))
    marker = f"continuity-plan:{plan.id}"
    owned = tuple(
        sorted(
            (int(rule.source_id), int(rule.target_id))
            for rule in (
                await db.execute(
                    select(ContinuityRule).where(
                        ContinuityRule.note == marker,
                        ContinuityRule.satisfaction_type == "item_read",
                    )
                )
            ).scalars().all()
        )
    )
    linked = tuple(
        sorted(
            (int(source_id), int(target_id))
            for source_id, target_id in (
                await db.execute(
                    select(Dependency.source_issue_id, Dependency.target_issue_id)
                    .join(
                        ReadingPlanDependency,
                        ReadingPlanDependency.dependency_id == Dependency.id,
                    )
                    .where(ReadingPlanDependency.plan_id == plan.id)
                )
            ).all()
        )
    )
    return PlanConstraintSnapshot(
        membership_issue_ids=member_ids,
        plan_owned_item_read_pairs=owned,
        plan_linked_dependency_pairs=linked,
        roll_blocking_pairs=await _roll_blocking_pairs_for_issues(db, member_ids),
    )


async def _projected_thread_entry_pairs(
    db: AsyncSession,
    nodes: list[ContinuityPlanNode],
) -> tuple[tuple[int, int], ...]:
    """Return inferred strict pairs JSON would compile, without compiling them."""
    from app.services.strict_plan_constraints import (
        load_issue_thread_index,
        strict_plan_item_read_pairs,
    )

    issue_ids = [node.ref_id for node in nodes if node.node_type == "issue"]
    index = await load_issue_thread_index(db, issue_ids)
    return tuple(strict_plan_item_read_pairs(nodes, index))


async def _capture_plan_record_backup(
    db: AsyncSession,
    *,
    plan: ContinuityPlan,
) -> PlanRecordBackup:
    """Snapshot the plan record and source order for rollback."""
    sources = await reading_plan_repository.list_plan_sources(db, plan_id=plan.id)
    placements = await reading_plan_repository.list_plan_source_placements(
        db, plan_id=plan.id
    )
    nodes = deepcopy(list(plan.nodes_json or []))
    return PlanRecordBackup(
        nodes_json=nodes,
        sources=tuple(_source_row_to_dict(source) for source in sources),
        placements=tuple(_placement_row_to_dict(placement) for placement in placements),
    )


def _source_from_backup(row: dict[str, object]) -> ReadingPlanSource:
    """Rehydrate one source snapshot from a rollback receipt."""
    metadata = row.get("metadata_json")
    cbl_source_list_id = row.get("cbl_source_list_id")
    custom_cbl_list_id = row.get("custom_cbl_list_id")
    return ReadingPlanSource(
        id=_backup_int(row["id"], "id"),
        plan_id=_backup_int(row["plan_id"], "plan_id"),
        raw_source_path=str(row["raw_source_path"]),
        repository=str(row["repository"]) if row.get("repository") is not None else None,
        source_path=str(row["source_path"]) if row.get("source_path") is not None else None,
        revision_sha=(
            str(row["revision_sha"]) if row.get("revision_sha") is not None else None
        ),
        content_hash=(
            str(row["content_hash"]) if row.get("content_hash") is not None else None
        ),
        cbl_source_list_id=(
            cbl_source_list_id
            if isinstance(cbl_source_list_id, int) and not isinstance(cbl_source_list_id, bool)
            else None
        ),
        custom_cbl_list_id=(
            custom_cbl_list_id
            if isinstance(custom_cbl_list_id, int) and not isinstance(custom_cbl_list_id, bool)
            else None
        ),
        adopted_at=_parse_dt(row.get("adopted_at")),
        recorded_at=_parse_dt(row.get("recorded_at")) or datetime.now(UTC),
        metadata_json=metadata if isinstance(metadata, dict) else None,
    )


def _placement_from_backup(row: dict[str, object]) -> ReadingPlanSourcePlacement:
    """Rehydrate one source placement from a rollback receipt."""
    position = row.get("source_position")
    return ReadingPlanSourcePlacement(
        id=_backup_int(row["id"], "id"),
        plan_id=_backup_int(row["plan_id"], "plan_id"),
        occurrence_id=str(row["occurrence_id"]),
        plan_source_id=_backup_int(row["plan_source_id"], "plan_source_id"),
        source_position=(
            position if isinstance(position, int) and not isinstance(position, bool) else None
        ),
    )


async def restore_plan_record_from_backup(
    db: AsyncSession,
    *,
    plan: ContinuityPlan,
    backup: PlanRecordBackup,
) -> None:
    """Restore ``nodes_json`` and source order from a captured backup.

    Membership is not rewritten. Strict rules are not compiled.

    Args:
        db: Async database session.
        plan: Plan whose record should be restored.
        backup: Capture taken before the membership-authoritative trim.
    """
    plan.nodes_json = deepcopy(backup.nodes_json)
    plan.updated_at = datetime.now(UTC)
    await reading_plan_repository.replace_plan_sources(
        db,
        plan_id=plan.id,
        sources=[_source_from_backup(row) for row in backup.sources],
        placements=[_placement_from_backup(row) for row in backup.placements],
    )


async def _group_dropped_series(
    db: AsyncSession,
    issue_ids: Collection[int],
) -> tuple[DroppedPlanSeries, ...]:
    """Group leftover JSON issues by owning series for operator review."""
    unique_ids = sorted({issue_id for issue_id in issue_ids if issue_id > 0})
    if not unique_ids:
        return ()
    rows = (
        await db.execute(
            select(Thread.id, Thread.title, Issue.id, Issue.issue_number, Issue.position)
            .join(Issue, Issue.thread_id == Thread.id)
            .where(Issue.id.in_(unique_ids))
            .order_by(Thread.title, Issue.position, Issue.id)
        )
    ).all()
    grouped: dict[int, DroppedPlanSeries] = {}
    order: list[int] = []
    for thread_id, title, issue_id, issue_number, _position in rows:
        series = grouped.get(int(thread_id))
        if series is None:
            grouped[int(thread_id)] = DroppedPlanSeries(
                thread_id=int(thread_id),
                title=str(title),
                issue_ids=(int(issue_id),),
                issue_numbers=(str(issue_number),),
            )
            order.append(int(thread_id))
        else:
            grouped[int(thread_id)] = DroppedPlanSeries(
                thread_id=series.thread_id,
                title=series.title,
                issue_ids=(*series.issue_ids, int(issue_id)),
                issue_numbers=(*series.issue_numbers, str(issue_number)),
            )
    return tuple(grouped[thread_id] for thread_id in order)


def _json_issue_count(nodes_json: object) -> int:
    """Count issue-typed nodes in a raw plan record."""
    if not isinstance(nodes_json, list):
        return 0
    count = 0
    for raw in nodes_json:
        if isinstance(raw, dict) and str(raw.get("node_type")) == "issue":
            count += 1
    return count


def _build_membership_report(
    *,
    plan_id: int,
    before: PlanConstraintSnapshot,
    after: PlanConstraintSnapshot,
    json_issue_count_before: int,
    json_issue_count_after: int,
    skipped_missing: tuple[int, ...],
    skipped_non_issue: int,
    invalid_node_count: int,
    dropped_json_issue_ids: tuple[int, ...],
    dropped_json_node_ids: tuple[str, ...],
    dropped_series: tuple[DroppedPlanSeries, ...],
    projected_thread_entry_pairs: tuple[tuple[int, int], ...],
    backup: PlanRecordBackup,
) -> MembershipReconcileReport:
    """Assemble a before/after membership report from two snapshots."""
    before_set = set(before.membership_issue_ids)
    after_set = set(after.membership_issue_ids)
    return MembershipReconcileReport(
        plan_id=plan_id,
        membership_count=len(after.membership_issue_ids),
        json_issue_count_before=json_issue_count_before,
        json_issue_count_after=json_issue_count_after,
        skipped_missing_issue_ids=skipped_missing,
        skipped_non_issue_nodes=skipped_non_issue,
        invalid_node_count=invalid_node_count,
        inserted_issue_ids=tuple(sorted(after_set - before_set)),
        removed_issue_ids=tuple(sorted(before_set - after_set)),
        dropped_json_issue_ids=dropped_json_issue_ids,
        dropped_json_node_ids=dropped_json_node_ids,
        dropped_series=dropped_series,
        before=before,
        after=after,
        projected_thread_entry_pairs=projected_thread_entry_pairs,
        backup=backup,
    )


async def _plan_record_trim_projection(
    db: AsyncSession,
    *,
    plan: ContinuityPlan,
    before: PlanConstraintSnapshot,
    backup: PlanRecordBackup,
) -> MembershipReconcileReport:
    """Build the membership-authoritative trim report without compiling."""
    keep_ids = set(before.membership_issue_ids)
    kept, dropped_ids, dropped_node_ids, skipped_non_issue, invalid = (
        trim_plan_nodes_json_to_membership(plan.nodes_json, keep_issue_ids=keep_ids)
    )
    existing_dropped = await _existing_issue_ids(db, dropped_ids)
    skipped_missing = tuple(
        issue_id for issue_id in dropped_ids if issue_id not in existing_dropped
    )
    kept_models, _invalid_kept = parse_plan_nodes_json(kept)
    projected = await _projected_thread_entry_pairs(db, kept_models)
    dropped_series = await _group_dropped_series(db, existing_dropped)
    after = await snapshot_plan_constraint_sets(
        db,
        plan=plan,
        membership_issue_ids=keep_ids,
    )
    return _build_membership_report(
        plan_id=plan.id,
        before=before,
        after=after,
        json_issue_count_before=_json_issue_count(plan.nodes_json),
        json_issue_count_after=_json_issue_count(kept),
        skipped_missing=skipped_missing,
        skipped_non_issue=skipped_non_issue,
        invalid_node_count=invalid,
        dropped_json_issue_ids=dropped_ids,
        dropped_json_node_ids=dropped_node_ids,
        dropped_series=dropped_series,
        projected_thread_entry_pairs=projected,
        backup=backup,
    )


async def dry_run_plan_membership_reconcile(
    db: AsyncSession,
    *,
    plan: ContinuityPlan,
) -> MembershipReconcileReport:
    """Report leftover JSON issues without writing any rows.

    Args:
        db: Async database session.
        plan: Persisted plan to inspect.

    Returns:
        The same report shape as apply, with membership unchanged.
    """
    before = await snapshot_plan_constraint_sets(db, plan=plan)
    backup = await _capture_plan_record_backup(db, plan=plan)
    return await _plan_record_trim_projection(
        db, plan=plan, before=before, backup=backup
    )


async def reconcile_plan_record_to_membership(
    db: AsyncSession,
    *,
    plan: ContinuityPlan,
) -> MembershipReconcileReport:
    """Trim one plan's JSON and source order to the membership table.

    ``reading_plan_issues`` is not rewritten and strict rules are not compiled.
    Leftover JSON issue nodes (including dangling refs) are dropped so a later
    re-save cannot compile restrictions from series the owner already removed.

    Args:
        db: Async database session.
        plan: Persisted plan whose JSON record may have drifted.

    Returns:
        Before/after membership and blocker sets plus the dropped leftovers.
    """
    before = await snapshot_plan_constraint_sets(db, plan=plan)
    backup = await _capture_plan_record_backup(db, plan=plan)
    report = await _plan_record_trim_projection(
        db, plan=plan, before=before, backup=backup
    )
    kept, _dropped_ids, dropped_node_ids, _skipped, _invalid = (
        trim_plan_nodes_json_to_membership(
            plan.nodes_json, keep_issue_ids=before.membership_issue_ids
        )
    )
    plan.nodes_json = kept
    plan.updated_at = datetime.now(UTC)
    await reading_plan_repository.delete_plan_source_placements_for_occurrences(
        db, plan_id=plan.id, occurrence_ids=dropped_node_ids
    )
    await reading_plan_repository.delete_orphan_plan_sources(db, plan_id=plan.id)
    after = await snapshot_plan_constraint_sets(db, plan=plan)
    return _build_membership_report(
        plan_id=report.plan_id,
        before=report.before,
        after=after,
        json_issue_count_before=report.json_issue_count_before,
        json_issue_count_after=_json_issue_count(kept),
        skipped_missing=report.skipped_missing_issue_ids,
        skipped_non_issue=report.skipped_non_issue_nodes,
        invalid_node_count=report.invalid_node_count,
        dropped_json_issue_ids=report.dropped_json_issue_ids,
        dropped_json_node_ids=report.dropped_json_node_ids,
        dropped_series=report.dropped_series,
        projected_thread_entry_pairs=report.projected_thread_entry_pairs,
        backup=backup,
    )


async def drop_threads_from_plan_record(
    db: AsyncSession,
    *,
    plan: ContinuityPlan,
    thread_ids: Collection[int],
) -> tuple[tuple[int, ...], list[ContinuityPlanNode]]:
    """Remove every issue of the given series from the plan record.

    Updates ``nodes_json`` and rebuilds membership plus source order from the
    remaining nodes in one write so the two cannot diverge. Does not compile
    strict rules; live CBL/planner saves call the canonical writer afterwards.

    Args:
        db: Async database session.
        plan: Plan to edit.
        thread_ids: Series to drop from the plan.

    Returns:
        Dropped issue ids and the remaining validated nodes.
    """
    unique_thread_ids = sorted({thread_id for thread_id in thread_ids if thread_id > 0})
    if not unique_thread_ids:
        nodes, _invalid = parse_plan_nodes_json(plan.nodes_json)
        return (), nodes
    drop_ids = tuple(
        (
            await db.execute(
                select(Issue.id).where(Issue.thread_id.in_(unique_thread_ids))
            )
        ).scalars().all()
    )
    kept_raw = drop_issue_nodes_from_plan_json(
        list(plan.nodes_json or []),
        drop_issue_ids=drop_ids,
    )
    plan.nodes_json = kept_raw
    plan.updated_at = datetime.now(UTC)
    nodes, _invalid = parse_plan_nodes_json(kept_raw)
    await rebuild_plan_membership(db, plan_id=plan.id, nodes=nodes)
    return tuple(sorted(drop_ids)), nodes


def _source_metadata_for_node(node: ContinuityPlanNode) -> dict[str, object] | None:
    """Collect advisory source annotations from one plan node.

    Args:
        node: Canonical plan node.

    Returns:
        Advisory metadata mapping, or None when the node carries none.
    """
    metadata: dict[str, object] = {}
    if node.source_role is not None:
        metadata["source_role"] = node.source_role
    if node.source_confidence is not None:
        metadata["source_confidence"] = node.source_confidence
    if node.source_explanation is not None:
        metadata["source_explanation"] = node.source_explanation
    if node.source_story_arc_ids is not None:
        metadata["source_story_arc_ids"] = list(node.source_story_arc_ids)
    if node.source_target_story_arc_id is not None:
        metadata["source_target_story_arc_id"] = node.source_target_story_arc_id
    return metadata or None


def _split_custom_cbl_reference(raw_path: str) -> int | None:
    """Parse an explicit ``custom-cbl:<id>`` source reference.

    Only the ``custom-cbl:<id>`` convention carries an unambiguous identity;
    bare paths and ``repository:path`` strings are preserved raw and left
    unresolved rather than split on a colon.

    Args:
        raw_path: Raw source path retained by the plan node.

    Returns:
        The custom CBL list ID, or None for any other convention.
    """
    prefix, separator, remainder = raw_path.partition(":")
    if not separator or prefix != "custom-cbl" or not remainder.isdigit():
        return None
    return int(remainder)


async def rebuild_plan_membership(
    db: AsyncSession,
    *,
    plan_id: int,
    nodes: list[ContinuityPlanNode],
) -> None:
    """Rebuild one plan's normalized membership and provenance from its nodes.

    Only issue-type nodes become membership rows; thread/crossover references
    keep no normalized membership until an explicit reviewed Issue mapping
    exists. Source paths and CBL placements are preserved raw with their
    original positions. The caller owns the surrounding transaction.

    Args:
        db: Database session.
        plan_id: Plan whose normalized rows are replaced.
        nodes: Canonical node set just persisted to the plan.
    """
    # Canonical membership invariant (#3037): fail closed with a domain error
    # before any row is replaced, so no write path can persist a duplicate.
    ensure_plan_issue_uniqueness(nodes)
    issue_rows: list[ReadingPlanIssue] = []
    snapshots: dict[str, ReadingPlanSource] = {}
    # (occurrence_id, raw_path, source_position) triples, deduplicated.
    placement_keys: set[tuple[str, str, int | None]] = set()

    for node in nodes:
        if node.node_type != "issue":
            continue
        positioned: dict[str, list[int]] = {}
        if node.source_cbl_placements:
            for placement in node.source_cbl_placements:
                if placement.source_path:
                    positioned.setdefault(placement.source_path, []).append(
                        placement.position
                    )
        bare_paths: list[str] = []
        if node.source_paths:
            for raw_path in node.source_paths:
                if raw_path and raw_path not in bare_paths:
                    bare_paths.append(raw_path)
        for raw_path in list(positioned) + bare_paths:
            if raw_path not in snapshots:
                custom_list_id = _split_custom_cbl_reference(raw_path)
                if custom_list_id is not None and (
                    await db.get(CustomCBLList, custom_list_id)
                ) is None:
                    custom_list_id = None
                snapshots[raw_path] = ReadingPlanSource(
                    plan_id=plan_id,
                    raw_source_path=raw_path,
                    custom_cbl_list_id=custom_list_id,
                )
        issue_rows.append(
            ReadingPlanIssue(
                plan_id=plan_id,
                occurrence_id=node.id,
                issue_id=node.ref_id,
                lane_id=node.lane_id,
                display_position=node.position,
                label=node.label,
                reader_role=node.reader_role,
                reader_optional=node.reader_optional,
                is_checkpoint=node.is_checkpoint,
                source_metadata_json=_source_metadata_for_node(node),
            )
        )
        for raw_path, positions in positioned.items():
            for position in sorted(set(positions)):
                placement_keys.add((node.id, raw_path, position))
        for raw_path in bare_paths:
            placement_keys.add((node.id, raw_path, None))

    ordered_snapshots = [snapshots[key] for key in sorted(snapshots)]
    await reading_plan_repository.replace_plan_issues(
        db, plan_id=plan_id, rows=issue_rows
    )
    await reading_plan_repository.replace_plan_sources(
        db, plan_id=plan_id, sources=ordered_snapshots, placements=[]
    )
    snapshot_ids = {source.raw_source_path: source.id for source in ordered_snapshots}
    placements = [
        ReadingPlanSourcePlacement(
            plan_id=plan_id,
            occurrence_id=occurrence_id,
            plan_source_id=snapshot_ids[raw_path],
            source_position=position,
        )
        for occurrence_id, raw_path, position in sorted(
            placement_keys, key=lambda key: (key[0], key[1], key[2] is None, key[2] or 0)
        )
    ]
    if placements:
        await reading_plan_repository.add_plan_source_placements(
            db, plan_id=plan_id, placements=placements
        )


async def link_dependency_to_plan(
    db: AsyncSession,
    *,
    user_id: int,
    plan_id: int,
    dependency_id: int,
    explanation: str | None = None,
) -> tuple[int, int, int, int, str | None]:
    """Reference one canonical Dependency edge from one owned plan.

    Args:
        db: Database session.
        user_id: Authenticated plan owner.
        plan_id: Plan referencing the edge.
        dependency_id: Canonical edge to reference.
        explanation: Optional human explanation, never an ownership marker.

    Raises:
        HTTPException: 404 when the plan or edge is not owned; 422 when
            either edge endpoint is not owned by the user.

    Returns:
        The ``(plan_id, dependency_id, source_issue_id, target_issue_id,
        explanation)`` tuple for response use.
    """
    plan = await continuity_repository.get_continuity_plan(
        db, user_id=user_id, plan_id=plan_id
    )
    if plan is None:
        raise HTTPException(status_code=404, detail=f"Continuity plan {plan_id} not found")
    dependency = await db.get(Dependency, dependency_id)
    if dependency is None:
        raise HTTPException(status_code=404, detail=f"Dependency {dependency_id} not found")
    owned = await continuity_repository.owned_issue_ids_for_user(
        db,
        user_id,
        [dependency.source_issue_id, dependency.target_issue_id],
    )
    if len(owned) != 2:
        raise HTTPException(
            status_code=422,
            detail={
                "code": "dangling_plan_reference",
                "dependency_id": dependency_id,
            },
        )
    link = await reading_plan_repository.link_plan_dependency(
        db, plan_id=plan.id, dependency_id=dependency.id, explanation=explanation
    )
    # Extract before the caller's commit to avoid expired-attribute access.
    plan_id_value = link.plan_id
    dependency_id_value = link.dependency_id
    source_issue_id = dependency.source_issue_id
    target_issue_id = dependency.target_issue_id
    explanation_value = link.explanation
    return plan_id_value, dependency_id_value, source_issue_id, target_issue_id, explanation_value


async def unlink_dependency_from_plan(
    db: AsyncSession,
    *,
    user_id: int,
    plan_id: int,
    dependency_id: int,
) -> bool:
    """Remove one plan's reference to a Dependency edge.

    Args:
        db: Database session.
        user_id: Authenticated plan owner.
        plan_id: Plan to unlink.
        dependency_id: Canonical edge to stop referencing.

    Raises:
        HTTPException: 404 when the plan is not owned.

    Returns:
        True when a link existed and was removed.
    """
    plan = await continuity_repository.get_continuity_plan(
        db, user_id=user_id, plan_id=plan_id
    )
    if plan is None:
        raise HTTPException(status_code=404, detail=f"Continuity plan {plan_id} not found")
    return await reading_plan_repository.unlink_plan_dependency(
        db, plan_id=plan.id, dependency_id=dependency_id
    )


async def get_plan_membership(
    db: AsyncSession,
    *,
    user_id: int,
    plan_id: int,
) -> ReadingPlanMembershipResponse:
    """Return the normalized membership view for one owned plan.

    Existing production plans are readable through this representation:
    membership, dependency provenance, source snapshots, placements, and
    progress derived from global Issue read state.

    Args:
        db: Database session.
        user_id: Authenticated plan owner.
        plan_id: Plan to inspect.

    Raises:
        HTTPException: 404 when the plan is not owned.

    Returns:
        Normalized membership response.
    """
    plan = await continuity_repository.get_continuity_plan(
        db, user_id=user_id, plan_id=plan_id
    )
    if plan is None:
        raise HTTPException(status_code=404, detail=f"Continuity plan {plan_id} not found")
    plan_id_value = plan.id
    issues = await reading_plan_repository.list_plan_issues(db, plan_id=plan.id)
    edges = await reading_plan_repository.list_plan_dependency_edges(db, plan_id=plan.id)
    links = await reading_plan_repository.list_plan_dependencies(db, plan_id=plan.id)
    sources = await reading_plan_repository.list_plan_sources(db, plan_id=plan.id)
    placements = await reading_plan_repository.list_plan_source_placements(
        db, plan_id=plan.id
    )
    explanations = {link.dependency_id: link.explanation for link in links}
    total, read = await get_plan_progress(db, plan_id=plan.id)
    return ReadingPlanMembershipResponse(
        plan_id=plan_id_value,
        issues=[
            ReadingPlanMemberIssue(
                occurrence_id=row.occurrence_id,
                issue_id=row.issue_id,
                lane_id=row.lane_id,
                display_position=row.display_position,
                label=row.label,
                reader_role=row.reader_role,
                reader_optional=row.reader_optional,
                is_checkpoint=row.is_checkpoint,
                source_metadata=row.source_metadata_json,
            )
            for row in issues
        ],
        dependencies=[
            ReadingPlanDependencyLink(
                dependency_id=edge.id,
                source_issue_id=edge.source_issue_id,
                target_issue_id=edge.target_issue_id,
                explanation=explanations.get(edge.id),
            )
            for edge in edges
        ],
        sources=[
            ReadingPlanSourceSnapshot(
                id=source.id,
                raw_source_path=public_cbl_source_path(source.raw_source_path),
                repository=(
                    public_cbl_repository(source.repository)
                    if source.repository
                    else None
                ),
                source_path=(
                    public_cbl_source_path(source.source_path)
                    if source.source_path
                    else None
                ),
                revision_sha=source.revision_sha,
                content_hash=source.content_hash,
                adopted_at=source.adopted_at,
                recorded_at=source.recorded_at,
            )
            for source in sources
        ],
        placements=[
            ReadingPlanSourcePlacementView(
                id=placement.id,
                occurrence_id=placement.occurrence_id,
                plan_source_id=placement.plan_source_id,
                source_position=placement.source_position,
            )
            for placement in placements
        ],
        progress=ReadingPlanProgress(total_issues=total, read_issues=read),
    )


async def get_plan_progress(
    db: AsyncSession,
    *,
    plan_id: int,
) -> tuple[int, int]:
    """Derive one plan's progress from global Issue read state.

    Args:
        db: Database session.
        plan_id: Plan to measure.

    Returns:
        ``(total_distinct_issues, read_distinct_issues)``.
    """
    issue_ids = await reading_plan_repository.distinct_plan_issue_ids(
        db, plan_id=plan_id
    )
    read_count = await reading_plan_repository.count_distinct_read_issues(
        db, plan_id=plan_id
    )
    return len(issue_ids), read_count
