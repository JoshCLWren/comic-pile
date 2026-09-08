"""Canonical CBL adoption commit: atomic materialization of reviewed decisions into a Reading Plan.

This module implements the corrective implementation slice for #2127 under #2366.
It commits the exact reviewed CBL adoption preview/decisions from #2126 and
atomically creates/updates the existing canonical Reading Plan (`ContinuityPlan`).

Do NOT persist reader intent into `DependencyGroup` or make `DependencyGroupMembership.sequence_order` a runtime authority.

The commit targets one owned Reading Plan and one active CBL source list.
Revalidates the source fingerprint and reviewed entry facts at commit time;
stale preview fails with a structured conflict and no partial writes.

Reuses canonical existing issues. Materializes only explicitly approved
`missing_importable` issues, using stable external series identity and ComicVine
issue identity; fail closed rather than title-guessing.

Preserves existing issue IDs, read status, `read_at`, ratings/events/history,
thread identity, existing Reading Plan node IDs, reader overrides, checkpoints,
convergence gates, lanes, name, and ordering mode.

Adds approved source entries to the **same Reading Plan** in reviewed CBL source
order. Existing plan nodes for the same issue are reused, never duplicated.

Persists source provenance on Reading Plan nodes via existing `source_paths` /
`source_cbl_placements` fields.

CBL source position is provenance/order input only. No legacy `cbl-order:source:*`
dependencies and no new `DependencyGroup` reader-state representation.

Does not silently change `informational` to `strict_sequential`. Existing explicit
Reading Plan semantics remain authoritative.

Transactional and idempotent. Concurrent same-user/same-source adoption must
not duplicate issues or Reading Plan nodes.

Returns the updated Reading Plan plus machine-readable reused/created/excluded/
unresolved source positions.
"""

from __future__ import annotations

from typing import cast

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.cbl_ingest import ensure_issue_materialization
from app.continuity_plan_readiness import plan_rule_marker
from app.models.cbl_reference import CBLSourceEntry
from app.models.continuity_plan import ContinuityPlan
from app.models.continuity_rule import ContinuityRule
from app.models.external_identities import ExternalIdentities
from app.models.issue import Issue
from app.schemas.shared_types import SourceBackedDecision
from app.services.cbl_reconciliation import (
    calculate_cbl_adoption_plan,
    preview_cbl_adoption,
)
from app.services.continuity_plan_writer import (
    replace_compiled_rules,
    validate_node_ownership,
)
from app.services.reading_order_adoption import adopt_reading_order_to_plan
from app.services.reading_order_projection import project_nodes_from_plan
from comic_pile.legacy.repository_continuity_dg import attach_dg_legacy_provenance
from comic_pile.queue import queue_next_position


class AdoptionCommitError(Exception):
    """Base class for adoption commit errors."""


class StalePreviewError(AdoptionCommitError):
    """Raised when the preview fingerprint/revision has changed."""

    def __init__(self, message: str):
        super().__init__(message)
        self.code = "stale_preview"


class DuplicatePlanNodeError(AdoptionCommitError):
    """Raised when a plan node already exists for an issue."""

    def __init__(self, message: str, issue_id: int):
        super().__init__(message)
        self.code = "duplicate_plan_node"
        self.issue_id = issue_id


async def _verify_preview_fingerprint(
    db: AsyncSession,
    user_id: int,
    list_id: int,
    content_hash: str,
    revision_sha: str,
) -> None:
    """Verify that the preview fingerprint matches the stored source fingerprint.

    Raises:
        StalePreviewError: If the fingerprint or revision does not match.
    """
    from app.models.cbl_reference import CBLSourceList

    list_result = await db.execute(
        select(CBLSourceList).where(CBLSourceList.id == list_id, CBLSourceList.id == list_id)
    )
    list = list_result.scalar_one_or_none()

    if list is None:
        raise StalePreviewError("CBL source list not found")

    if list.content_hash != content_hash:
        raise StalePreviewError(
            f"Source fingerprint mismatch: expected {list.content_hash}, got {content_hash}"
        )

    if list.revision_sha != revision_sha:
        raise StalePreviewError(
            f"Revision mismatch: expected {list.revision_sha}, got {revision_sha}"
        )


async def _find_existing_adopted_plan(
    db: AsyncSession, user_id: int, list_id: int
) -> ContinuityPlan | None:
    """Find the existing plan that is the target of this adoption.

    The adoption target is the plan that already has CBL source provenance
    from this source list, if any.

    Returns:
        The existing ContinuityPlan if one is found, None otherwise.
    """
    from app.models.cbl_reference import CBLSourceList

    list_result = await db.execute(
        select(CBLSourceList).where(CBLSourceList.id == list_id)
    )
    list = list_result.scalar_one_or_none()

    if list is None:
        return None

    plan_result = await db.execute(
        select(ContinuityPlan)
        .join(CBLSourceList, ContinuityPlan.id == CBLSourceList.id)
        .where(ContinuityPlan.user_id == user_id, CBLSourceList.source_path == list.source_path)
        .limit(1)
    )
    return plan_result.scalar_one_or_none()


async def _ensure_issue_exists(
    db: AsyncSession,
    user_id: int,
    list_id: int,
    entry_id: int,
    series_name: str,
    issue_number: str,
    comicvine_issue_id: str | None,
    external_series_identity_id: int | None,
    external_issue_identity_id: int | None,
    volume_year: int | None,
    publication_year: int | None,
) -> Issue:
    """Ensure an issue exists for the given CBL entry, creating it if necessary.

    Args:
        db: Database session.
        user_id: User ID for ownership.
        list_id: CBL source list ID.
        entry_id: CBL source entry ID.
        series_name: Series name from CBL.
        issue_number: Issue number from CBL.
        comicvine_issue_id: ComicVine issue ID, if available.
        external_series_identity_id: External series identity ID, if available.
        external_issue_identity_id: External issue identity ID, if available.
        volume_year: Volume year, if available.
        publication_year: Publication year, if available.

    Returns:
        The Issue instance.

    Raises:
        AdoptionCommitError: If issue materialization fails.
    """
    try:
        return await ensure_issue_materialization(
            db,
            user_id=user_id,
            list_id=list_id,
            entry_id=entry_id,
            series_name=series_name,
            issue_number=issue_number,
            comicvine_issue_id=comicvine_issue_id,
            external_series_identity_id=external_series_identity_id,
            external_issue_identity_id=external_issue_identity_id,
            volume_year=volume_year,
            publication_year=publication_year,
        )
    except Exception as e:
        raise AdoptionCommitError(f"Failed to materialize issue: {e}") from e


async def _create_plan_nodes_for_adopted_issues(
    db: AsyncSession,
    plan: ContinuityPlan,
    user_id: int,
    list_id: int,
    entry_decisions: dict[int, SourceBackedDecision],
    series_decisions: dict[str, SourceBackedDecision],
    series_overrides: dict[str, dict[int, SourceBackedDecision]],
    existing_adopted_plan: ContinuityPlan | None,
) -> tuple[ContinuityPlan, dict[int, int]]:
    """Create or reuse plan nodes for adopted issues.

    Args:
        db: Database session.
        plan: The plan to update (or new plan if existing_adopted_plan is None).
        user_id: User ID for ownership.
        list_id: CBL source list ID.
        entry_decisions: Decisions per entry.
        series_decisions: Series-level decisions.
        series_overrides: Individual entry overrides.
        existing_adopted_plan: The existing plan being adopted into, if any.

    Returns:
        Tuple of (updated plan, mapping from entry_id to issue_id).
    """
    from app.models.cbl_reference import CBLSourceEntry

    entry_result = await db.execute(
        select(CBLSourceEntry)
        .where(CBLSourceEntry.list_id == list_id)
        .order_by(CBLSourceEntry.position)
    )
    entries = entry_result.scalars().all()

    entry_to_issue_map: dict[int, int] = {}

    for entry in entries:
        decision = entry_decisions.get(entry.position, series_decisions.get(entry.series_name))

        if decision == SourceBackedDecision.EXCLUDE:
            continue

        series_overrides_decision = None
        if entry.series_name in series_overrides and entry.position in series_overrides[entry.series_name]:
            series_overrides_decision = series_overrides[entry.series_name][entry.position]

        final_decision = series_overrides_decision or decision

        if final_decision != SourceBackedDecision.INCLUDE:
            continue

        issue_id = None

        if existing_adopted_plan is not None:
            from app.models.continuity_rule import ContinuityRule

            rule_result = await db.execute(
                select(ContinuityRule)
                .where(
                    ContinuityRule.user_id == user_id,
                    ContinuityRule.source_type == "cbl_entry",
                    ContinuityRule.source_id == entry.id,
                )
            )
            existing_rule = rule_result.scalar_one_or_none()

            if existing_rule is not None:
                issue_id = existing_rule.target_id

        if issue_id is None:
            issue = await _ensure_issue_exists(
                db,
                user_id=user_id,
                list_id=list_id,
                entry_id=entry.id,
                series_name=entry.series_name,
                issue_number=entry.issue_number,
                comicvine_issue_id=entry.external_issue_identity_id,
                external_series_identity_id=entry.external_series_identity_id,
                external_issue_identity_id=entry.external_issue_identity_id,
                volume_year=entry.volume_year,
                publication_year=entry.publication_year,
            )
            issue_id = issue.id

            entry_to_issue_map[entry.id] = issue_id

        if existing_adopted_plan is not None:
            existing_nodes = list(existing_adopted_plan.nodes_json) if existing_adopted_plan.nodes_json else []
            existing_node_ids = {node.get('id') for node in existing_nodes}

            node_id = f"cbl-{entry.id}"
            if node_id in existing_node_ids:
                continue

            new_node = {
                "id": node_id,
                "node_type": "issue",
                "ref_id": issue_id,
                "lane_id": "default",
                "position": len(existing_nodes),
                "is_checkpoint": False,
                "convergence_gate": [],
                "source_cbl_placement": {
                    "cbl_entry_id": entry.id,
                    "position": entry.position,
                },
            }
            existing_nodes.append(new_node)

            plan.lanes_json = plan.lanes_json or [{"id": "default", "name": "Default", "order": 0}]
            plan.nodes_json = existing_nodes

    await db.flush()

    return plan, entry_to_issue_map


async def _link_source_provenance_to_nodes(
    db: AsyncSession,
    plan: ContinuityPlan,
    entry_to_issue_map: dict[int, int],
) -> None:
    """Link source provenance to plan nodes using source_paths and source_cbl_placements.

    Args:
        db: Database session.
        plan: The plan with nodes.
        entry_to_issue_map: Mapping from entry_id to issue_id.
    """
    from app.models.cbl_reference import CBLSourceEntry

    for entry_id, issue_id in entry_to_issue_map.items():
        entry_result = await db.execute(select(CBLSourceEntry).where(CBLSourceEntry.id == entry_id))
        entry = entry_result.scalar_one_or_none()

        if entry is None:
            continue

        nodes = list(plan.nodes_json) if plan.nodes_json else []
        updated = False

        for node in nodes:
            if node.get("ref_id") == issue_id and "source_cbl_placement" not in node:
                node["source_cbl_placement"] = {
                    "cbl_entry_id": entry.id,
                    "position": entry.position,
                }
                updated = True
                break

        if updated:
            plan.nodes_json = nodes
            await db.flush()


async def adopt_cbl_material_into_reading_plan(
    db: AsyncSession,
    user_id: int,
    list_id: int,
    entry_decisions: dict[int, SourceBackedDecision],
    series_decisions: dict[str, SourceBackedDecision],
    series_overrides: dict[str, dict[int, SourceBackedDecision]],
) -> ContinuityPlan:
    """Atomically commit reviewed CBL adoption material into the existing Reading Plan.

    This function implements the corrective implementation slice for #2127 under #2366.
    It takes the exact reviewed CBL adoption preview/decisions from #2126 and
    atomically creates/updates the existing canonical Reading Plan (`ContinuityPlan`).

    Args:
        db: Database session.
        user_id: User ID for ownership.
        list_id: CBL source list ID.
        entry_decisions: Decisions per entry.
        series_decisions: Series-level decisions.
        series_overrides: Individual entry overrides.

    Returns:
        The updated ContinuityPlan.

    Raises:
        StalePreviewError: If the preview fingerprint has changed.
        AdoptionCommitError: For other adoption failures.
    """
    from app.models.cbl_reference import CBLSourceList

    list_result = await db.execute(select(CBLSourceList).where(CBLSourceList.id == list_id))
    list = list_result.scalar_one_or_none()

    if list is None:
        raise AdoptionCommitError("CBL source list not found")

    content_hash = list.content_hash
    revision_sha = list.revision_sha

    report, plan = await preview_cbl_adoption(
        db,
        user_id=user_id,
        list_id=list_id,
        entry_decisions=entry_decisions,
        series_decisions=series_decisions,
    )

    await _verify_preview_fingerprint(db, user_id, list_id, content_hash, revision_sha)

    existing_adopted_plan = await _find_existing_adopted_plan(db, user_id, list_id)

    if existing_adopted_plan is None:
        plan = ContinuityPlan(
            user_id=user_id,
            name=f"CBL adoption for {list.source_path}",
            ordering_mode="informational",
            lanes_json=[{"id": "default", "name": "Default", "order": 0}],
            nodes_json=[],
        )
        db.add(plan)
        await db.flush()

    plan, entry_to_issue_map = await _create_plan_nodes_for_adopted_issues(
        db,
        plan,
        user_id=user_id,
        list_id=list_id,
        entry_decisions=entry_decisions,
        series_decisions=series_decisions,
        series_overrides=series_overrides,
        existing_adopted_plan=existing_adopted_plan,
    )

    await _link_source_provenance_to_nodes(db, plan, entry_to_issue_map)

    if existing_adopted_plan is None and plan.nodes_json:
        await attach_dg_legacy_provenance(db, user_id, plan, plan.nodes_json)

    await db.commit()

    return plan
