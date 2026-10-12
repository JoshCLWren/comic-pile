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

from collections.abc import Collection, Sequence
from dataclasses import dataclass

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
class MembershipReconcileReport:
    """Outcome of aligning membership to ``nodes_json`` without compiling rules.

    ``nodes_json`` is the intended membership and presentation order (#3486).
    ``reading_plan_issues`` is the derived membership table. This repair
    copies existing Issue refs from JSON into the table and never calls the
    strict compiler, so a drifted strict plan is not re-saved into a blanket
    of adjacent blockers.

    Production apply of this report is a separate authorization gate.
    """

    plan_id: int
    membership_count: int
    skipped_missing_issue_ids: tuple[int, ...]
    skipped_non_issue_nodes: int
    invalid_node_count: int
    inserted_issue_ids: tuple[int, ...]
    removed_issue_ids: tuple[int, ...]
    before: PlanConstraintSnapshot
    after: PlanConstraintSnapshot
    projected_thread_entry_pairs: tuple[tuple[int, int], ...]


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


def membership_report_to_dict(report: MembershipReconcileReport) -> dict[str, object]:
    """Serialize a membership reconcile report as JSON-ready data.

    Args:
        report: Apply or dry-run result.

    Returns:
        Plain mapping with list-encoded tuples.
    """
    return {
        "plan_id": report.plan_id,
        "json_is_authoritative": True,
        "membership_count": report.membership_count,
        "skipped_missing_issue_ids": list(report.skipped_missing_issue_ids),
        "skipped_non_issue_nodes": report.skipped_non_issue_nodes,
        "invalid_node_count": report.invalid_node_count,
        "inserted_issue_ids": list(report.inserted_issue_ids),
        "removed_issue_ids": list(report.removed_issue_ids),
        "before": _snapshot_to_dict(report.before),
        "after": _snapshot_to_dict(report.after),
        "projected_thread_entry_pairs": [
            list(pair) for pair in report.projected_thread_entry_pairs
        ],
        "compiled_rules": False,
    }


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


def _dedupe_existing_issue_nodes(
    nodes: Sequence[ContinuityPlanNode],
    existing_ids: set[int],
) -> list[ContinuityPlanNode]:
    """Keep first occurrence of each existing Issue; drop dangling issue refs."""
    deduped: list[ContinuityPlanNode] = []
    seen_issue_ids: set[int] = set()
    for node in nodes:
        if node.node_type == "issue":
            if node.ref_id not in existing_ids or node.ref_id in seen_issue_ids:
                continue
            seen_issue_ids.add(node.ref_id)
        deduped.append(node)
    return deduped


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
            intended JSON membership without writing ``reading_plan_issues``).

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
    """Return thread-entry pairs JSON would compile, without compiling them."""
    from app.services.strict_plan_constraints import (
        load_issue_thread_index,
        strict_plan_item_read_pairs,
    )

    issue_ids = [node.ref_id for node in nodes if node.node_type == "issue"]
    index = await load_issue_thread_index(db, issue_ids)
    return tuple(strict_plan_item_read_pairs(nodes, index))


async def _membership_reconcile_inputs(
    db: AsyncSession,
    *,
    plan: ContinuityPlan,
) -> tuple[list[ContinuityPlanNode], set[int], tuple[int, ...], int, int]:
    """Parse JSON membership intent and classify missing Issue refs.

    Returns:
        Deduped nodes for existing Issues, those Issue ids, dangling refs,
        skipped non-issue node count, and invalid JSON row count.
    """
    nodes, invalid_node_count = parse_plan_nodes_json(plan.nodes_json)
    skipped_non_issue = sum(1 for node in nodes if node.node_type != "issue")
    issue_ids = sorted({node.ref_id for node in nodes if node.node_type == "issue"})
    existing_ids = await _existing_issue_ids(db, issue_ids)
    skipped_missing = tuple(
        issue_id for issue_id in issue_ids if issue_id not in existing_ids
    )
    deduped = _dedupe_existing_issue_nodes(nodes, existing_ids)
    return (
        deduped,
        existing_ids,
        skipped_missing,
        skipped_non_issue,
        invalid_node_count,
    )


def _build_membership_report(
    *,
    plan_id: int,
    before: PlanConstraintSnapshot,
    after: PlanConstraintSnapshot,
    skipped_missing: tuple[int, ...],
    skipped_non_issue: int,
    invalid_node_count: int,
    projected_thread_entry_pairs: tuple[tuple[int, int], ...],
) -> MembershipReconcileReport:
    """Assemble a before/after membership report from two snapshots."""
    before_set = set(before.membership_issue_ids)
    after_set = set(after.membership_issue_ids)
    return MembershipReconcileReport(
        plan_id=plan_id,
        membership_count=len(after.membership_issue_ids),
        skipped_missing_issue_ids=skipped_missing,
        skipped_non_issue_nodes=skipped_non_issue,
        invalid_node_count=invalid_node_count,
        inserted_issue_ids=tuple(sorted(after_set - before_set)),
        removed_issue_ids=tuple(sorted(before_set - after_set)),
        before=before,
        after=after,
        projected_thread_entry_pairs=projected_thread_entry_pairs,
    )


async def dry_run_plan_membership_reconcile(
    db: AsyncSession,
    *,
    plan: ContinuityPlan,
) -> MembershipReconcileReport:
    """Report the JSON-vs-membership gap without writing any rows.

    Args:
        db: Async database session.
        plan: Persisted plan to inspect.

    Returns:
        The same report shape as apply, with ``after`` projected from JSON.
    """
    before = await snapshot_plan_constraint_sets(db, plan=plan)
    deduped, existing_ids, skipped_missing, skipped_non_issue, invalid = (
        await _membership_reconcile_inputs(db, plan=plan)
    )
    after = await snapshot_plan_constraint_sets(
        db,
        plan=plan,
        membership_issue_ids=existing_ids,
    )
    projected = await _projected_thread_entry_pairs(db, deduped)
    return _build_membership_report(
        plan_id=plan.id,
        before=before,
        after=after,
        skipped_missing=skipped_missing,
        skipped_non_issue=skipped_non_issue,
        invalid_node_count=invalid,
        projected_thread_entry_pairs=projected,
    )


async def reconcile_plan_membership_from_nodes(
    db: AsyncSession,
    *,
    plan: ContinuityPlan,
) -> MembershipReconcileReport:
    """Rebuild one plan's membership from persisted nodes, skipping missing Issues.

    ``nodes_json`` is not rewritten and strict rules are not compiled. Issue
    nodes whose ``ref_id`` does not exist cannot become membership rows (the
    Issue FK would fail) and are reported so an authorized production repair
    can drop or rematerialize them separately.

    Args:
        db: Async database session.
        plan: Persisted plan whose JSON membership may have drifted.

    Returns:
        Before/after membership and blocker sets plus dangling node refs.
    """
    before = await snapshot_plan_constraint_sets(db, plan=plan)
    deduped, _existing_ids, skipped_missing, skipped_non_issue, invalid = (
        await _membership_reconcile_inputs(db, plan=plan)
    )
    await rebuild_plan_membership(db, plan_id=plan.id, nodes=deduped)
    after = await snapshot_plan_constraint_sets(db, plan=plan)
    projected = await _projected_thread_entry_pairs(db, deduped)
    return _build_membership_report(
        plan_id=plan.id,
        before=before,
        after=after,
        skipped_missing=skipped_missing,
        skipped_non_issue=skipped_non_issue,
        invalid_node_count=invalid,
        projected_thread_entry_pairs=projected,
    )


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
