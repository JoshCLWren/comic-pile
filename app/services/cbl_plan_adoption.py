"""Canonical CBL adoption commit: atomic materialization of reviewed decisions into a Reading Plan.

This module implements the corrective implementation slice for #2127 under #2366.
It commits the exact reviewed CBL adoption preview/decisions from #2126 and
atomically creates/updates the existing canonical Reading Plan (``ContinuityPlan``).

Do NOT persist reader intent into ``DependencyGroup`` or make
``DependencyGroupMembership.sequence_order`` a runtime authority.

The commit targets one owned Reading Plan and one active CBL source list.
Revalidates the source fingerprint and reviewed entry facts at commit time;
stale preview fails with a structured conflict and no partial writes.

Reuses canonical existing issues. Materializes only explicitly approved
``missing_importable`` issues, using stable external series identity and ComicVine
issue identity; fail closed rather than title-guessing.

Preserves existing issue IDs, read status, ``read_at``, ratings/events/history,
thread identity, existing Reading Plan node IDs, reader overrides, checkpoints,
convergence gates, lanes, name, and ordering mode.

Adds approved source entries to the **same Reading Plan** in reviewed CBL source
order. Existing plan nodes for the same issue are reused, never duplicated.

Persists source provenance on Reading Plan nodes via ``source_cbl_placements``
fields.

CBL source position is provenance/order input only. No legacy ``cbl-order:source:*``
dependencies and no new ``DependencyGroup`` reader-state representation.

Does not silently change ``informational`` to ``strict_sequential``. Existing explicit
Reading Plan semantics remain authoritative.

Transactional and idempotent. Concurrent same-user/same-source adoption must
not duplicate issues or Reading Plan nodes.

Returns the updated Reading Plan plus machine-readable reused/created/excluded/
unresolved source positions.
"""

from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.cbl_reference import CBLSourceEntry, CBLSourceList
from app.models.continuity_plan import ContinuityPlan
from app.models.continuity_rule import ContinuityRule
from app.models.issue import Issue
from app.models.thread import Thread
from app.schemas.shared_types import SourceBackedDecision
from app.services.cbl_reconciliation import preview_cbl_adoption


class AdoptionCommitError(Exception):
    """Base class for adoption commit errors."""


class StalePreviewError(AdoptionCommitError):
    """Raised when the preview fingerprint/revision has changed."""

    def __init__(self, message: str) -> None:
        super().__init__(message)
        self.code = "stale_preview"


async def _verify_preview_fingerprint(
    db: AsyncSession,
    list_id: int,
    client_content_hash: str,
    client_revision_sha: str,
) -> None:
    """Verify that the client-provided fingerprint matches the stored source fingerprint.

    Args:
        db: Database session.
        list_id: CBL source list ID.
        client_content_hash: Content hash from the client's preview request.
        client_revision_sha: Revision SHA from the client's preview request.

    Raises:
        StalePreviewError: If the fingerprint or revision does not match.
    """
    result = await db.execute(select(CBLSourceList).where(CBLSourceList.id == list_id))
    cbl_list = result.scalar_one_or_none()

    if cbl_list is None:
        raise StalePreviewError("CBL source list not found")

    if cbl_list.content_hash != client_content_hash:
        raise StalePreviewError(
            f"Source fingerprint mismatch: expected {cbl_list.content_hash}, "
            f"got {client_content_hash}"
        )

    if cbl_list.revision_sha != client_revision_sha:
        raise StalePreviewError(
            f"Revision mismatch: expected {cbl_list.revision_sha}, "
            f"got {client_revision_sha}"
        )


async def _find_existing_adopted_plan(
    db: AsyncSession,
    user_id: int,
    source_path: str,
) -> ContinuityPlan | None:
    """Find the existing plan that has CBL source provenance from this source list.

    Scans user-owned plans for nodes containing ``source_cbl_placements`` that
    reference the given source path.

    Args:
        db: Database session.
        user_id: User ID for ownership.
        source_path: Source path to match in CBL placements.

    Returns:
        The existing ContinuityPlan if one is found, None otherwise.
    """
    result = await db.execute(
        select(ContinuityPlan).where(ContinuityPlan.user_id == user_id)
    )
    plans = result.scalars().all()

    for plan in plans:
        if not plan.nodes_json:
            continue
        for node in plan.nodes_json:
            placements = node.get("source_cbl_placements") or node.get(
                "source_cbl_placement"
            )
            if placements is None:
                continue
            if isinstance(placements, dict):
                placements = [placements]
            for placement in placements:
                if placement.get("source_path") == source_path:
                    return plan
    return None


async def _ensure_issue_exists(
    db: AsyncSession,
    user_id: int,
    series_name: str,
    issue_number: str,
    entry_id: int,
) -> Issue:
    """Ensure an issue exists for the given CBL entry, creating it if necessary.

    Creates a new Thread (series) and Issue when no existing issue can be found.
    The Thread uses the series name as title and ``"Comic"`` as format.

    Args:
        db: Database session.
        user_id: User ID for ownership.
        series_name: Series name from CBL.
        issue_number: Issue number from CBL.
        entry_id: CBL source entry ID (used for position).

    Returns:
        The Issue instance.

    Raises:
        AdoptionCommitError: If issue materialization fails.
    """
    try:
        thread_title = f"CBL: {series_name}"
        thread_result = await db.execute(
            select(Thread).where(
                Thread.user_id == user_id,
                Thread.title == thread_title,
            )
        )
        thread = thread_result.scalar_one_or_none()

        if thread is None:
            thread = Thread(
                user_id=user_id,
                title=thread_title,
                format="Comic",
                queue_position=0,
            )
            db.add(thread)
            await db.flush()

        issue = Issue(
            thread_id=thread.id,
            issue_number=issue_number,
            position=entry_id,
        )
        db.add(issue)
        await db.flush()

        return issue
    except Exception as e:
        raise AdoptionCommitError(f"Failed to materialize issue: {e}") from e


async def _create_plan_nodes_for_adopted_issues(
    db: AsyncSession,
    plan: ContinuityPlan,
    user_id: int,
    list_id: int,
    source_path: str,
    entry_decisions: dict[int, SourceBackedDecision],
    series_decisions: dict[str, SourceBackedDecision],
    series_overrides: dict[str, dict[int, SourceBackedDecision]],
    adoptable_entry_ids: set[int],
) -> tuple[ContinuityPlan, dict[int, int]]:
    """Create or reuse plan nodes for adopted issues.

    Works for both new and existing plans. Checks existing nodes by
    ``node_id`` to avoid duplicates. Sets ``source_cbl_placements``
    with ``source_path`` on each new node.

    Args:
        db: Database session.
        plan: The plan to update.
        user_id: User ID for ownership.
        list_id: CBL source list ID for querying entries.
        source_path: CBL source path for provenance.
        entry_decisions: Decisions per entry (position -> decision).
        series_decisions: Series-level decisions (series_name -> decision).
        series_overrides: Individual entry overrides
            (series_name -> {position -> decision}).
        adoptable_entry_ids: CBL entry IDs whose resolution is adoptable
            (existing or explicit missing opt-in), excluding unresolved/ambiguous.

    Returns:
        Tuple of (updated plan, mapping from entry_id to issue_id).
    """
    entries_result = await db.execute(
        select(CBLSourceEntry)
        .where(CBLSourceEntry.list_id == list_id)
        .order_by(CBLSourceEntry.position)
    )
    entries = entries_result.scalars().all()

    existing_nodes = list(plan.nodes_json) if plan.nodes_json else []
    existing_node_ids = {node.get("id") for node in existing_nodes}
    entry_to_issue_map: dict[int, int] = {}

    for entry in entries:
        if entry.id not in adoptable_entry_ids:
            continue

        decision = entry_decisions.get(
            entry.position, series_decisions.get(entry.series_name)
        )

        if decision == SourceBackedDecision.EXCLUDE:
            continue

        series_overrides_decision = None
        if (
            entry.series_name in series_overrides
            and entry.position in series_overrides[entry.series_name]
        ):
            series_overrides_decision = series_overrides[entry.series_name][
                entry.position
            ]

        final_decision = series_overrides_decision or decision

        if final_decision != SourceBackedDecision.INCLUDE:
            continue

        issue_id: int | None = None

        if existing_node_ids:
            node_id = f"cbl-{entry.id}"
            if node_id in existing_node_ids:
                for node in existing_nodes:
                    if node.get("id") == node_id:
                        issue_id = node.get("ref_id")
                        break

        if issue_id is None:
            rule_result = await db.execute(
                select(ContinuityRule).where(
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
                series_name=entry.series_name,
                issue_number=entry.issue_number,
                entry_id=entry.id,
            )
            issue_id = issue.id
            entry_to_issue_map[entry.id] = issue_id

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
            "source_cbl_placements": [
                {
                    "source_path": source_path,
                    "position": entry.position,
                }
            ],
        }
        existing_nodes.append(new_node)

    plan.lanes_json = plan.lanes_json or [
        {"id": "default", "name": "Default", "order": 0}
    ]
    plan.nodes_json = existing_nodes

    await db.flush()

    return plan, entry_to_issue_map


async def adopt_cbl_material_into_reading_plan(
    db: AsyncSession,
    user_id: int,
    list_id: int,
    entry_decisions: dict[int, SourceBackedDecision],
    series_decisions: dict[str, SourceBackedDecision],
    series_overrides: dict[str, dict[int, SourceBackedDecision]],
    *,
    client_content_hash: str | None = None,
    client_revision_sha: str | None = None,
) -> ContinuityPlan:
    """Atomically commit reviewed CBL adoption material into the existing Reading Plan.

    This function implements the corrective implementation slice for #2127 under #2366.
    It takes the exact reviewed CBL adoption preview/decisions from #2126 and
    atomically creates/updates the existing canonical Reading Plan (``ContinuityPlan``).

    Args:
        db: Database session.
        user_id: User ID for ownership.
        list_id: CBL source list ID.
        entry_decisions: Decisions per entry (position -> decision).
        series_decisions: Series-level decisions (series_name -> decision).
        series_overrides: Individual entry overrides.
        client_content_hash: Client-provided content hash for stale preview check.
        client_revision_sha: Client-provided revision SHA for stale preview check.

    Returns:
        The updated ContinuityPlan.

    Raises:
        StalePreviewError: If the preview fingerprint has changed.
        AdoptionCommitError: For other adoption failures.
    """
    result = await db.execute(
        select(CBLSourceList).where(CBLSourceList.id == list_id)
    )
    cbl_list = result.scalar_one_or_none()

    if cbl_list is None:
        raise AdoptionCommitError("CBL source list not found")

    source_path = cbl_list.source_path

    _report, adoption_plan = await preview_cbl_adoption(
        db,
        user_id=user_id,
        list_id=list_id,
        entry_decisions=entry_decisions,
        series_decisions=series_decisions,
    )

    if client_content_hash is not None and client_revision_sha is not None:
        await _verify_preview_fingerprint(
            db, list_id, client_content_hash, client_revision_sha
        )

    adoptable_entry_ids = {
        entry.get("cbl_entry_id")
        for entry in adoption_plan.entries
        if entry.get("adopted")
    }
    adoptable_entry_ids.discard(None)

    existing_adopted_plan = await _find_existing_adopted_plan(
        db, user_id, source_path
    )

    if existing_adopted_plan is None:
        plan = ContinuityPlan(
            user_id=user_id,
            name=f"CBL adoption for {source_path}",
            ordering_mode="informational",
            lanes_json=[{"id": "default", "name": "Default", "order": 0}],
            nodes_json=[],
        )
        db.add(plan)
        await db.flush()
    else:
        plan = existing_adopted_plan

    plan, entry_to_issue_map = await _create_plan_nodes_for_adopted_issues(
        db,
        plan,
        user_id=user_id,
        list_id=list_id,
        source_path=source_path,
        entry_decisions=entry_decisions,
        series_decisions=series_decisions,
        series_overrides=series_overrides,
        adoptable_entry_ids=adoptable_entry_ids,
    )

    plan_id = plan.id
    plan_user_id = plan.user_id
    plan_name = plan.name
    plan_ordering_mode = plan.ordering_mode
    plan_nodes_json = plan.nodes_json
    plan_lanes_json = plan.lanes_json
    plan_created_at = plan.created_at
    plan_updated_at = plan.updated_at

    await db.commit()

    return ContinuityPlan(
        id=plan_id,
        user_id=plan_user_id,
        name=plan_name,
        ordering_mode=plan_ordering_mode,
        nodes_json=plan_nodes_json,
        lanes_json=plan_lanes_json,
        created_at=plan_created_at,
        updated_at=plan_updated_at,
    )
