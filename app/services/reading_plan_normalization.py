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

Membership uniqueness (``uq_reading_plan_issue_plan_issue``): Reading Plan
membership is set membership, so one canonical Issue appears at most once per
plan. ``normalize_plan_nodes`` is the single deterministic rule that collapses
repeated Issue nodes; the database constraint is the backstop that makes the
invariant unbreakable through any other write path.
"""

from __future__ import annotations

from fastapi import HTTPException
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.custom_cbl import CustomCBLList
from app.models.dependency import Dependency
from app.models.reading_plan_membership import (
    ReadingPlanIssue,
    ReadingPlanSource,
    ReadingPlanSourcePlacement,
)
from app.repositories import continuity_repository, reading_plan_repository
from app.schemas.continuity_plan import (
    CBLPlacement,
    ContinuityPlanNode,
    ConvergenceGateTarget,
)
from app.schemas.reading_plan_membership import (
    ReadingPlanDependencyLink,
    ReadingPlanMemberIssue,
    ReadingPlanMembershipResponse,
    ReadingPlanProgress,
    ReadingPlanSourcePlacementView,
    ReadingPlanSourceSnapshot,
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


def _merge_issue_occurrences(
    primary: ContinuityPlanNode,
    duplicates: list[ContinuityPlanNode],
) -> ContinuityPlanNode:
    """Fold every duplicate occurrence of one Issue into its primary occurrence.

    The primary occurrence keeps its identity, lane, position, and reader
    overrides because those are the values the reader actually sees. Provenance
    is unioned so collapsing membership never discards import evidence, and
    plan-level gates are unioned so collapsing membership never silently
    unblocks or un-waits a node.

    Args:
        primary: Surviving occurrence, chosen as the lowest ``(position, id)``.
        duplicates: Additional occurrences of the same canonical Issue.

    Returns:
        One node carrying the primary's identity plus the merged evidence.
    """
    ordered = [primary, *duplicates]

    def _first_present(field: str) -> object | None:
        for node in ordered:
            value: object | None = getattr(node, field)
            if value is not None:
                return value
        return None

    source_paths: list[str] = []
    for node in ordered:
        for raw_path in node.source_paths or ():
            if raw_path not in source_paths:
                source_paths.append(raw_path)

    placements: list[CBLPlacement] = []
    seen_placements: set[tuple[str, int]] = set()
    for node in ordered:
        for placement in node.source_cbl_placements or ():
            key = (placement.source_path, placement.position)
            if key in seen_placements:
                continue
            seen_placements.add(key)
            placements.append(placement)

    updates: dict[str, object] = {
        "source_paths": tuple(source_paths) or None,
        "source_cbl_placements": tuple(placements) or None,
        "source_role": _first_present("source_role"),
        "source_confidence": _first_present("source_confidence"),
        "source_explanation": _first_present("source_explanation"),
        "source_story_arc_ids": _first_present("source_story_arc_ids"),
        "source_target_story_arc_id": _first_present("source_target_story_arc_id"),
        "is_checkpoint": any(node.is_checkpoint for node in ordered),
        "convergence_gate": _merged_convergence_gates(primary, duplicates),
    }
    return primary.model_copy(update=updates)


def _merged_convergence_gates(
    primary: ContinuityPlanNode,
    duplicates: list[ContinuityPlanNode],
) -> list[ConvergenceGateTarget]:
    """Return the union of every occurrence's convergence gate, in stable order."""
    gates: list[ConvergenceGateTarget] = []
    seen: set[str] = set()
    for node in [primary, *duplicates]:
        for target in node.convergence_gate:
            if target.node_id in seen:
                continue
            seen.add(target.node_id)
            gates.append(target)
    return gates


def _remap_convergence_gates(
    nodes: list[ContinuityPlanNode],
    removed_node_ids: dict[str, str],
) -> list[ContinuityPlanNode]:
    """Re-point convergence gates at surviving occurrences after a collapse.

    A gate that waited on a removed occurrence now waits on that occurrence's
    surviving primary. A gate that becomes a wait on its own node is dropped,
    because a canonical Issue can never usefully wait for itself.

    Args:
        nodes: Post-collapse node set.
        removed_node_ids: Removed occurrence ID to surviving occurrence ID.

    Returns:
        Nodes whose convergence gates reference only surviving nodes.
    """
    remapped: list[ContinuityPlanNode] = []
    for node in nodes:
        if not node.convergence_gate:
            remapped.append(node)
            continue
        gates: list[ConvergenceGateTarget] = []
        seen: set[str] = set()
        for target in node.convergence_gate:
            node_id = removed_node_ids.get(target.node_id, target.node_id)
            if node_id == node.id or node_id in seen:
                continue
            seen.add(node_id)
            gates.append(target.model_copy(update={"node_id": node_id}))
        if gates == node.convergence_gate:
            remapped.append(node)
        else:
            remapped.append(node.model_copy(update={"convergence_gate": gates}))
    return remapped


def _compact_lane_positions(nodes: list[ContinuityPlanNode]) -> list[ContinuityPlanNode]:
    """Renumber every lane's positions contiguously while preserving node order."""
    next_position: dict[str, int] = {}
    compacted: list[ContinuityPlanNode] = []
    for node in nodes:
        position = next_position.get(node.lane_id, 0)
        next_position[node.lane_id] = position + 1
        if node.position == position:
            compacted.append(node)
        else:
            compacted.append(node.model_copy(update={"position": position}))
    return compacted


def normalize_plan_nodes(
    nodes: list[ContinuityPlanNode],
    *,
    compact_positions: bool = False,
) -> list[ContinuityPlanNode]:
    """Collapse repeated canonical Issue nodes so one plan holds each Issue once.

    Reading Plan membership is set membership: within one plan a canonical
    Issue appears at most once. A canonical writer (``replace_compiled_rules``)
    calls this before persisting ``nodes_json``, compiling plan rules, and
    rebuilding membership so those three representations cannot disagree.

    The surviving occurrence is the lowest ``(position, id)`` pair, which is the
    deterministic reading-order winner. Provenance from every other occurrence
    is merged into it, and a convergence gate pointing at a removed occurrence is
    re-pointed at the survivor. Non-issue nodes are never collapsed.

    Args:
        nodes: Canonical plan node set about to be written.
        compact_positions: Renumber each lane contiguously after collapsing.
            Required for ``strict_sequential`` plans, whose validator demands
            contiguous positions, and a no-op when nothing was collapsed.

    Returns:
        The node set with at most one occurrence per canonical Issue.
    """
    grouped: dict[int, list[ContinuityPlanNode]] = {}
    for node in nodes:
        if node.node_type != "issue":
            continue
        grouped.setdefault(node.ref_id, []).append(node)

    collapsed_duplicates: dict[int, list[ContinuityPlanNode]] = {
        issue_id: sorted(occurrences, key=lambda item: (item.position, item.id))
        for issue_id, occurrences in grouped.items()
        if len(occurrences) > 1
    }
    removed_node_ids: dict[str, str] = {}
    for occurrences in collapsed_duplicates.values():
        survivor = occurrences[0].id
        for node in occurrences[1:]:
            removed_node_ids[node.id] = survivor
    if not removed_node_ids:
        return list(nodes)

    survivors: dict[int, ContinuityPlanNode] = {
        issue_id: occurrences[0]
        for issue_id, occurrences in grouped.items()
        if len(occurrences) == 1
    }
    for issue_id, occurrences in collapsed_duplicates.items():
        survivors[issue_id] = _merge_issue_occurrences(occurrences[0], occurrences[1:])

    collapsed: list[ContinuityPlanNode] = []
    for node in nodes:
        if node.node_type != "issue":
            collapsed.append(node)
            continue
        if node.id in removed_node_ids:
            continue
        collapsed.append(survivors[node.ref_id])

    normalized = _remap_convergence_gates(collapsed, removed_node_ids)
    if compact_positions:
        normalized = _compact_lane_positions(normalized)
    return normalized


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

    Duplicate canonical Issues are collapsed by ``normalize_plan_nodes`` before
    any row is built, so a plan can never persist one canonical Issue twice.
    A concurrent writer that loses the race on
    ``uq_reading_plan_issue_plan_issue`` receives a stable domain response
    instead of an opaque database failure.

    Args:
        db: Database session.
        plan_id: Plan whose normalized rows are replaced.
        nodes: Canonical node set just persisted to the plan.

    Raises:
        HTTPException: 409 ``reading_plan_membership_conflict`` when a
            concurrent plan write already persisted this membership.
    """
    normalized = normalize_plan_nodes(nodes)

    issue_rows: list[ReadingPlanIssue] = []
    snapshots: dict[str, ReadingPlanSource] = {}
    # (occurrence_id, raw_path, source_position) triples, deduplicated.
    placement_keys: set[tuple[str, str, int | None]] = set()

    for node in normalized:
        if node.node_type != "issue":
            continue

        positioned: dict[str, list[int]] = {}
        bare_paths: list[str] = []
        if node.source_cbl_placements:
            for placement in node.source_cbl_placements:
                if placement.source_path:
                    positioned.setdefault(placement.source_path, []).append(
                        placement.position
                    )
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
    try:
        await reading_plan_repository.replace_plan_issues(
            db, plan_id=plan_id, rows=issue_rows
        )
        await reading_plan_repository.replace_plan_sources(
            db, plan_id=plan_id, sources=ordered_snapshots, placements=[]
        )
        if placements:
            await reading_plan_repository.add_plan_source_placements(
                db, plan_id=plan_id, placements=placements
            )
    except IntegrityError as exc:
        if getattr(exc.orig, "sqlstate", None) != "23505":
            raise
        raise HTTPException(
            status_code=409,
            detail={
                "code": "reading_plan_membership_conflict",
                "plan_id": plan_id,
            },
        ) from exc


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
                raw_source_path=source.raw_source_path,
                repository=source.repository,
                source_path=source.source_path,
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
