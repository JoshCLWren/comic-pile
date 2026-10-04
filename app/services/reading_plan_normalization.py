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

from fastapi import HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.custom_cbl import CustomCBLList
from app.models.dependency import Dependency
from app.models.reading_plan_membership import (
    ReadingPlanIssue,
    ReadingPlanSource,
    ReadingPlanSourcePlacement,
)
from app.repositories import continuity_repository, reading_plan_repository
from app.schemas.continuity_plan import ContinuityPlanNode
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

    Duplicate issue_id occurrences are deduplicated: the first occurrence
    (by display_position, then occurrence_id) is kept and context from
    subsequent duplicates is merged (source metadata and placements).

    Args:
        db: Database session.
        plan_id: Plan whose normalized rows are replaced.
        nodes: Canonical node set just persisted to the plan.
    """
    # Collect issue nodes, deduplicating by issue_id.
    # Keep the first occurrence (by position, then occurrence_id) and merge
    # context from duplicates into it.
    issue_nodes_by_id: dict[int, list[ContinuityPlanNode]] = {}
    for node in nodes:
        if node.node_type != "issue":
            continue
        issue_nodes_by_id.setdefault(node.ref_id, []).append(node)

    issue_rows: list[ReadingPlanIssue] = []
    snapshots: dict[str, ReadingPlanSource] = {}
    # (occurrence_id, raw_path, source_position) triples, deduplicated.
    placement_keys: set[tuple[str, str, int | None]] = set()

    for _issue_id, issue_nodes in issue_nodes_by_id.items():
        # Sort by display_position, then occurrence_id for deterministic ordering.
        issue_nodes.sort(key=lambda n: (n.position, n.id))
        primary_node = issue_nodes[0]
        duplicate_nodes = issue_nodes[1:]

        # Merge source metadata from duplicates into primary.
        merged_metadata = _source_metadata_for_node(primary_node)
        for dup in duplicate_nodes:
            dup_metadata = _source_metadata_for_node(dup)
            if dup_metadata:
                if merged_metadata is None:
                    merged_metadata = dup_metadata
                else:
                    # Merge keys, preferring primary's values.
                    for k, v in dup_metadata.items():
                        merged_metadata.setdefault(k, v)

        # Collect all source paths and placements from primary and duplicates.
        positioned: dict[str, list[int]] = {}
        bare_paths: list[str] = []

        for n in (primary_node, *duplicate_nodes):
            if n.source_cbl_placements:
                for placement in n.source_cbl_placements:
                    if placement.source_path:
                        positioned.setdefault(placement.source_path, []).append(
                            placement.position
                        )
            if n.source_paths:
                for raw_path in n.source_paths:
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

        # Use primary node's occurrence_id for the membership row.
        issue_rows.append(
            ReadingPlanIssue(
                plan_id=plan_id,
                occurrence_id=primary_node.id,
                issue_id=primary_node.ref_id,
                lane_id=primary_node.lane_id,
                display_position=primary_node.position,
                label=primary_node.label,
                reader_role=primary_node.reader_role,
                reader_optional=primary_node.reader_optional,
                is_checkpoint=primary_node.is_checkpoint,
                source_metadata_json=merged_metadata,
            )
        )

        # Collect placements for all occurrences (primary + duplicates)
        # so provenance is preserved even when membership is deduplicated.
        for raw_path, positions in positioned.items():
            for position in sorted(set(positions)):
                # Associate with primary occurrence_id for deduplicated membership.
                placement_keys.add((primary_node.id, raw_path, position))
        for raw_path in bare_paths:
            placement_keys.add((primary_node.id, raw_path, None))

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
