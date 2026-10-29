"""Plan/List membership parity evaluation and repair (#4254).

Option E makes a reader-owned Reading List the single issue-order authority of
its Reading Plan. Durable authority is only valid when the plan carries an
owned-list source snapshot: a
:class:`~app.models.reading_plan_membership.ReadingPlanSource` row whose
``custom_cbl_list_id`` points at the owner's
:class:`~app.models.custom_cbl.CustomCBLList`, without dropping retained
historical provenance rows (for example ``comicvine:4050-18250``).

Issue #4254 recorded one production defect of this exact shape: Plan #29 kept
only a ComicVine source snapshot, so its List link was missing, its membership
lacked the List's Issue at position 32, and the first four shared positions
carried a different order. This module evaluates that parity contract and
repairs it with idempotent, auditable steps:

- ``evaluate_plan_list_parity``: read-only parity report (link state,
  membership difference, shared-order conflict, first-unread frontier).
- ``plan_parity_repair``: a fail-closed dry-run manifest of the mutations an
  apply would perform. It never writes anything.
- ``execute_parity_repair``: performs only those mutations in the caller's
  transaction, then re-evaluates parity in the same transaction and raises so
  the caller rolls back when the expected after-state is not observed.

The owner's List is never modified: not one ``custom_cbl_lists`` or
``custom_cbl_entries`` row is touched, and Plan membership is only ever added
or repositioned within the plan, never deleted. Explicitly approved
data-changing intent parsed by :func:`parse_repair_intent` must be passed to
:func:`execute_parity_repair` before anything durable can change.
"""

from __future__ import annotations

from collections import Counter
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field, replace

from sqlalchemy.ext.asyncio import AsyncSession

from app.models.custom_cbl import CustomCBLEntry, CustomCBLList
from app.models.reading_plan_membership import (
    ReadingPlanIssue,
    ReadingPlanSource,
    ReadingPlanSourcePlacement,
)
from app.repositories import reading_plan_parity_repository as parity_repository

REPAIR_INTENT_CONTRACT = "reading-plan-list-parity-repair:v1"

LINK_STATE_MISSING = "missing_link"
LINK_STATE_LINKED = "linked"
LINK_STATE_FOREIGN = "foreign_link"
LINK_STATE_AMBIGUOUS = "ambiguous_link"

ORDER_CONFLICT_CODE = "shared_issue_order_conflict"
MEMBERSHIP_DIFFERENCE_CODE = "membership_difference"
LINK_MISSING_CODE = "durable_link_missing"
LINK_FOREIGN_CODE = "durable_link_points_elsewhere"
LANE_SHAPE_CODE = "plan_multi_lane_membership"
PLAN_ONLY_CODE = "plan_only_membership"
GATED_FRONTIER_CODE = "gated_frontier_observation"
PLAN_JSON_MISMATCH_CODE = "plan_json_membership_mismatch"

#: Blocking findings every parity repair must leave behind zero of.
BLOCKING_CODES = frozenset({
    LINK_MISSING_CODE,
    LINK_FOREIGN_CODE,
    LINK_STATE_AMBIGUOUS,
    LANE_SHAPE_CODE,
    PLAN_ONLY_CODE,
    ORDER_CONFLICT_CODE,
})

#: Tables the repair may write; everything else is provenance or authority.
MUTATED_TABLES = (
    "reading_plan_sources",
    "reading_plan_issues",
    "reading_plan_source_placements",
)

_REPAIR_OCCURRENCE_PREFIX = "parity-"


@dataclass(frozen=True)
class SourceSpec:
    """One immutable Plan-source snapshot relevant to parity."""

    source_id: int | None
    raw_source_path: str
    custom_cbl_list_id: int | None


@dataclass(frozen=True)
class ListEntrySpec:
    """One List entry in authority order with its Issue read status."""

    issue_id: int
    position: int
    gate: str
    skipped: bool
    is_checkpoint: bool
    status: str


@dataclass(frozen=True)
class OccurrenceSpec:
    """One Plan membership occurrence with its Issue read status."""

    occurrence_id: str
    issue_id: int
    lane_id: str
    display_position: int
    is_checkpoint: bool
    status: str


@dataclass(frozen=True)
class PlanParityContext:
    """All parity-relevant facts about one Plan and its candidate List."""

    user_id: int
    plan_id: int
    list_id: int | None
    plan_ordering_mode: str
    sources: tuple[SourceSpec, ...]
    entries: tuple[ListEntrySpec, ...]
    occurrences: tuple[OccurrenceSpec, ...]
    plan_json_issue_ids: tuple[int, ...] = ()


@dataclass(frozen=True)
class FrontierSpec:
    """First unread, non-skipped entry or occurrence of one authority."""

    issue_id: int
    position: int
    entry_number: int
    status: str
    gate: str


@dataclass(frozen=True)
class OrderConflictSpec:
    """One index where shared-issue order disagrees between Plan and List."""

    index: int
    list_issue_id: int
    plan_issue_id: int


@dataclass(frozen=True)
class ParityFinding:
    """One observational or blocking parity result code with details."""

    code: str
    detail: dict[str, object] = field(default_factory=dict)


@dataclass(frozen=True)
class PlanListParity:
    """Complete read-only parity result for one Plan/List pair."""

    link_state: str
    linked_list_ids: tuple[int, ...]
    list_issue_count: int
    plan_issue_count: int
    list_only: tuple[int, ...]
    plan_only: tuple[int, ...]
    shared_order_conflicts: tuple[OrderConflictSpec, ...]
    shared_order_aligned: bool
    list_frontier: FrontierSpec | None
    plan_frontier: FrontierSpec | None
    findings: tuple[ParityFinding, ...]


@dataclass(frozen=True)
class RepairAction:
    """One durably applied stage of the parity repair."""

    kind: str
    detail: dict[str, object] = field(default_factory=dict)


@dataclass(frozen=True)
class ParityRepairIntent:
    """Explicitly approved data-changing authorization for one repair."""

    owner_user_id: int
    plan_id: int
    list_id: int
    issue: str
    reader_intent_signoff: str


@dataclass(frozen=True)
class RepairManifest:
    """Fail-closed dry-run plan of the mutations an apply would perform."""

    plan_id: int
    list_id: int
    refusals: tuple[str, ...]
    actions: tuple[RepairAction, ...]
    parity_before: PlanListParity
    parity_after: PlanListParity
    mutated_tables: tuple[str, ...] = MUTATED_TABLES

    @property
    def valid(self) -> bool:
        """Return whether an apply may proceed."""
        return not self.refusals


@dataclass(frozen=True)
class RepairReceipt:
    """Durable, auditable outcome of one parity repair execution."""

    plan_id: int
    list_id: int
    applied_actions: tuple[RepairAction, ...]
    idempotent: bool
    residual_blocking_findings: tuple[str, ...]


def _first_unread(
    specs: Sequence[ListEntrySpec | OccurrenceSpec],
) -> FrontierSpec | None:
    """Return the first unread, non-skipped spec, or ``None`` when all read.

    Args:
        specs: Entry or occurrence specs already ordered by authority position.

    Returns:
        Frontier facts for the first spec whose Issue is not read and whose
        row is not skipped.
    """
    for spec in specs:
        skipped = getattr(spec, "skipped", False)
        if skipped or spec.status == "read":
            continue
        position = spec.position if isinstance(spec, ListEntrySpec) else spec.display_position
        return FrontierSpec(
            issue_id=spec.issue_id,
            position=position,
            entry_number=position + 1,
            status=spec.status,
            gate=getattr(spec, "gate", "none"),
        )
    return None


def evaluate_parity(context: PlanParityContext) -> PlanListParity:
    """Judge Plan membership and ownership against one authoritative List.

    Args:
        context: Owner-scoped facts for one Plan plus its candidate List
            entries, statuses and source snapshots.

    Returns:
        Link state, membership and shared-order parity, frontier observations
        and finding codes. Observational shapes are reported; illegal repair
        shapes become refusal findings in :func:`plan_parity_repair`.
    """
    findings: list[ParityFinding] = []
    owned_links = sorted({
        source.custom_cbl_list_id
        for source in context.sources
        if source.custom_cbl_list_id is not None
    })
    if context.list_id is not None and context.list_id in owned_links:
        link_state = LINK_STATE_LINKED
    elif len(owned_links) > 1:
        link_state = LINK_STATE_AMBIGUOUS
    elif owned_links:
        link_state = LINK_STATE_FOREIGN
        findings.append(
            ParityFinding(LINK_FOREIGN_CODE, {"owned_link_list_ids": owned_links})
        )
    elif context.list_id is None:
        link_state = LINK_STATE_MISSING
    else:
        link_state = LINK_STATE_MISSING
        findings.append(ParityFinding(LINK_MISSING_CODE, {"list_id": context.list_id}))
    if link_state == LINK_STATE_AMBIGUOUS:
        findings.append(
            ParityFinding(LINK_STATE_AMBIGUOUS, {"owned_link_list_ids": owned_links})
        )

    entries = sorted(context.entries, key=lambda entry: entry.position)
    occurrences = sorted(
        context.occurrences,
        key=lambda occurrence: (occurrence.lane_id, occurrence.display_position,
                                occurrence.occurrence_id),
    )
    lane_count = len({occurrence.lane_id for occurrence in occurrences})
    if lane_count > 1:
        findings.append(ParityFinding(LANE_SHAPE_CODE, {"lane_count": lane_count}))

    list_ids = {entry.issue_id for entry in entries}
    plan_ids = {occurrence.issue_id for occurrence in occurrences}
    list_only = [entry.issue_id for entry in entries if entry.issue_id not in plan_ids]
    plan_only = sorted(
        occurrence.issue_id
        for occurrence in occurrences
        if occurrence.issue_id not in list_ids
    )
    if list_only or plan_only:
        findings.append(
            ParityFinding(
                MEMBERSHIP_DIFFERENCE_CODE,
                {"list_only": list_only, "plan_only": plan_only},
            )
        )

    plan_only_set = set(plan_only)
    shared_list = [entry.issue_id for entry in entries if entry.issue_id not in plan_only_set]
    list_only_set = set(list_only)
    shared_plan = [
        occurrence.issue_id
        for occurrence in occurrences
        if occurrence.issue_id not in list_only_set
    ]
    conflicts = tuple(
        OrderConflictSpec(index, left, right)
        for index, (left, right) in enumerate(zip(shared_list, shared_plan, strict=False))
        if left != right
    )
    shared_order_aligned = not conflicts and len(shared_list) == len(shared_plan)
    if conflicts:
        findings.append(
            ParityFinding(
                ORDER_CONFLICT_CODE,
                {
                    "conflicts": [
                        {
                            "index": conflict.index,
                            "list_issue_id": conflict.list_issue_id,
                            "plan_issue_id": conflict.plan_issue_id,
                        }
                        for conflict in conflicts
                    ]
                },
            )
        )

    list_frontier = _first_unread(
        [entry for entry in entries if not entry.skipped]
    )
    if list_frontier is not None and list_frontier.gate != "none":
        findings.append(
            ParityFinding(
                GATED_FRONTIER_CODE,
                {
                    "gate": list_frontier.gate,
                    "issue_id": list_frontier.issue_id,
                    "position": list_frontier.position,
                },
            )
        )
    plan_frontier = _first_unread(occurrences) if occurrences else None

    if Counter(context.plan_json_issue_ids) != Counter(plan_ids):
        findings.append(
            ParityFinding(
                PLAN_JSON_MISMATCH_CODE,
                {
                    "plan_json_issue_ids": list(context.plan_json_issue_ids),
                    "membership_issue_ids": sorted(plan_ids),
                },
            )
        )

    return PlanListParity(
        link_state=link_state,
        linked_list_ids=tuple(owned_links),
        list_issue_count=len(entries),
        plan_issue_count=len(occurrences),
        list_only=tuple(list_only),
        plan_only=tuple(plan_only),
        shared_order_conflicts=conflicts,
        shared_order_aligned=shared_order_aligned,
        list_frontier=list_frontier,
        plan_frontier=plan_frontier,
        findings=tuple(findings),
    )


def _blocking_codes(parity: PlanListParity) -> list[str]:
    """Return the blocking finding codes a repair must clear.

    Args:
        parity: Parity report whose findings are classified.

    Returns:
        Finding codes restricted to :data:`BLOCKING_CODES`, in report order.
    """
    return [finding.code for finding in parity.findings if finding.code in BLOCKING_CODES]


def _desired_occurrence(
    entry: ListEntrySpec,
    occurrence_id: str,
    lane_id: str,
) -> OccurrenceSpec:
    """Project one authoritative entry onto its required plan occurrence.

    Args:
        entry: List entry in authority order.
        occurrence_id: Plan occurrence ID carrying this entry.
        lane_id: Single plan lane the membership is reconciled into.

    Returns:
        Occurrence spec exactly matching the List's position and checkpoint.
    """
    return OccurrenceSpec(
        occurrence_id=occurrence_id,
        issue_id=entry.issue_id,
        lane_id=lane_id,
        display_position=entry.position,
        is_checkpoint=entry.is_checkpoint,
        status=entry.status,
    )


def _repair_lane_id(context: PlanParityContext) -> str:
    """Return the single populated lane that a repair may write into.

    Args:
        context: Parity context with the plan's current occurrences.

    Returns:
        The only observed lane ID, or ``"main"`` for an empty plan.
    """
    lanes = {occurrence.lane_id for occurrence in context.occurrences}
    if len(lanes) == 1:
        return next(iter(lanes))
    if len(lanes) > 1:
        return ""
    return "main"


def plan_parity_repair(context: PlanParityContext) -> RepairManifest:
    """Build the fail-closed dry-run manifest for one Plan/List repair.

    Args:
        context: Owner-scoped facts for one Plan and its authoritative List.

    Returns:
        Manifest of refusal reasons (empty when repairable), the exact
        mutation actions an apply would perform, and simulated parity before
        and after. This function is pure and performs no writes.

    Raises:
        ValueError: When no authoritative List was supplied or the supplied
            List is not owned.
    """
    if context.list_id is None:
        raise ValueError("A target Reading List is required to plan a parity repair")
    parity_before = evaluate_parity(context)
    refusals: list[str] = []
    parity_before_blocking = _blocking_codes(parity_before)
    if LINK_STATE_FOREIGN in parity_before_blocking:
        refusals.append("durable Link already points at another owned Reading List")
    if LINK_STATE_AMBIGUOUS in parity_before_blocking:
        refusals.append("Plan carries ambiguous owned Reading List links")
    if LANE_SHAPE_CODE in parity_before_blocking:
        refusals.append(
            "Plan membership spans multiple lanes; reconciliation is refused"
        )
    if PLAN_ONLY_CODE in parity_before_blocking:
        refusals.append(
            "Plan contains Issues absent from the authoritative List; "
            "membership is never deleted"
        )
    if any(
        occurrence for occurrence in context.occurrences
        if occurrence.status not in {"read", "unread"}
    ):
        # Read status vocabulary drift is not this repair's contract.
        refusals.append("Membership carries unexpected Issue status vocabulary")

    lane_id = _repair_lane_id(context)
    existing_by_issue = {occurrence.issue_id: occurrence for occurrence in context.occurrences}
    existing_occurrence_ids = {
        occurrence.occurrence_id for occurrence in context.occurrences
    }
    entries = sorted(context.entries, key=lambda entry: entry.position)

    actions: list[RepairAction] = []
    if parity_before.link_state != LINK_STATE_LINKED:
        actions.append(
            RepairAction(
                kind="link_source",
                detail={
                    "raw_source_path": f"custom-cbl:{context.list_id}",
                    "custom_cbl_list_id": context.list_id,
                    "retained_other_sources": [
                        {
                            "raw_source_path": source.raw_source_path,
                            "custom_cbl_list_id": source.custom_cbl_list_id,
                        }
                        for source in context.sources
                        if source.custom_cbl_list_id is None
                    ],
                },
            )
        )
        actions.append(
            RepairAction(
                kind="record_source_placements",
                detail={"occurrence_count": len(entries)},
            )
        )

    missing_entries = [
        entry for entry in entries if entry.issue_id not in existing_by_issue
    ]
    if missing_entries:
        for entry in missing_entries:
            planned_id = f"{_REPAIR_OCCURRENCE_PREFIX}{entry.position}"
            if planned_id in existing_occurrence_ids:
                refusals.append(
                    f"Reserved occurrence id {planned_id!r} already exists on the plan"
                )
        actions.append(
            RepairAction(
                kind="add_occurrences",
                detail={
                    "occurrences": [
                        {
                            "occurrence_id": f"{_REPAIR_OCCURRENCE_PREFIX}{entry.position}",
                            "issue_id": entry.issue_id,
                            "lane_id": lane_id,
                            "display_position": entry.position,
                            "is_checkpoint": entry.is_checkpoint,
                        }
                        for entry in missing_entries
                    ]
                },
            )
        )

    reordered = [
        (existing.occurrence_id, entry.issue_id, existing.display_position, entry.position)
        for entry in entries
        if (existing := existing_by_issue.get(entry.issue_id)) is not None
        and existing.display_position != entry.position
    ]
    if reordered:
        actions.append(
            RepairAction(
                kind="reorder_occurrences",
                detail={
                    "moves": [
                        {
                            "occurrence_id": occurrence_id,
                            "issue_id": issue_id,
                            "from": previous,
                            "to": desired,
                        }
                        for occurrence_id, issue_id, previous, desired in reordered
                    ]
                },
            )
        )

    simulated_sources = (*context.sources, SourceSpec(
        source_id=None,
        raw_source_path=f"custom-cbl:{context.list_id}",
        custom_cbl_list_id=context.list_id,
    )) if parity_before.link_state == LINK_STATE_MISSING else context.sources
    simulated_occurrences: list[OccurrenceSpec] = []
    for entry in entries:
        existing = existing_by_issue.get(entry.issue_id)
        if existing is None:
            simulated_occurrences.append(_desired_occurrence(
                entry, f"{_REPAIR_OCCURRENCE_PREFIX}{entry.position}", lane_id,
            ))
        else:
            simulated_occurrences.append(
                _desired_occurrence(entry, existing.occurrence_id, lane_id)
            )
    parity_after = evaluate_parity(replace(context, sources=simulated_sources,
                                           occurrences=tuple(simulated_occurrences)))

    return RepairManifest(
        plan_id=context.plan_id,
        list_id=context.list_id,
        refusals=tuple(refusals),
        actions=tuple(actions),
        parity_before=parity_before,
        parity_after=parity_after,
        mutated_tables=MUTATED_TABLES,
    )


async def _load_context(
    db: AsyncSession,
    *,
    user_id: int,
    plan_id: int,
    list_id: int,
) -> PlanParityContext:
    """Load one owner-scoped parity context from the database.

    Args:
        db: Database session.
        user_id: Owner whose plan and List must be loaded.
        plan_id: Plan to inspect.
        list_id: Target Reading List; must belong to the owner.

    Returns:
        Fully populated parity context.

    Raises:
        ValueError: When the plan or List is missing or not owned.
    """
    plan, source_rows, membership_rows = await parity_repository.load_plan_parity_rows(
        db, user_id=user_id, plan_id=plan_id
    )
    if plan is None:
        raise ValueError(f"Reading Plan {plan_id} not found for this owner")
    lists = await parity_repository.load_lists(
        db, user_id=user_id, list_ids=[list_id]
    )
    if list_id not in lists:
        raise ValueError(f"Reading List {list_id} not found for this owner")
    entries_by_list = await parity_repository.load_entries_for_lists(
        db, user_id=user_id, list_ids=[list_id]
    )
    entry_rows: list[CustomCBLEntry] = entries_by_list.get(list_id, [])
    issue_ids = sorted({
        *[row.issue_id for row in entry_rows],
        *[row.issue_id for row in membership_rows],
    })
    statuses = await parity_repository.load_issue_statuses(db, issue_ids=issue_ids)
    reading_list: CustomCBLList = lists[list_id]
    del reading_list
    plan_json_issue_ids = [
        node.get("ref_id")
        for node in (plan.nodes_json or [])
        if isinstance(node, dict)
        and node.get("node_type") == "issue"
        and type(node.get("ref_id")) is int
    ]
    return PlanParityContext(
        user_id=user_id,
        plan_id=plan.id,
        list_id=list_id,
        plan_ordering_mode=plan.ordering_mode,
        sources=tuple(
            SourceSpec(
                source_id=source.id,
                raw_source_path=source.raw_source_path,
                custom_cbl_list_id=source.custom_cbl_list_id,
            )
            for source in source_rows
        ),
        entries=tuple(
            ListEntrySpec(
                issue_id=entry.issue_id,
                position=entry.position,
                gate=entry.gate,
                skipped=entry.skipped,
                is_checkpoint=entry.is_checkpoint,
                status=statuses.get(entry.issue_id, "unread"),
            )
            for entry in entry_rows
        ),
        occurrences=tuple(
            OccurrenceSpec(
                occurrence_id=membership.occurrence_id,
                issue_id=membership.issue_id,
                lane_id=membership.lane_id,
                display_position=membership.display_position,
                is_checkpoint=membership.is_checkpoint,
                status=statuses.get(membership.issue_id, "unread"),
            )
            for membership in membership_rows
        ),
        plan_json_issue_ids=tuple(plan_json_issue_ids),
    )


async def evaluate_plan_list_parity(
    db: AsyncSession,
    *,
    user_id: int,
    plan_id: int,
    list_id: int,
) -> PlanListParity:
    """Read-only parity report for one Plan against one owned List.

    Args:
        db: Database session.
        user_id: Owner whose plan and List are compared.
        plan_id: Plan to inspect.
        list_id: Target Reading List; must belong to the owner.

    Returns:
        Link state, membership and order parity plus frontier observations.
    """
    context = await _load_context(db, user_id=user_id, plan_id=plan_id, list_id=list_id)
    return evaluate_parity(context)


async def plan_plan_list_parity_repair(
    db: AsyncSession,
    *,
    user_id: int,
    plan_id: int,
    list_id: int,
) -> RepairManifest:
    """Build a dry-run repair manifest without writing anything.

    Args:
        db: Database session.
        user_id: Owner whose plan and List are inspected.
        plan_id: Plan to repair.
        list_id: Target Reading List; must belong to the owner.

    Returns:
        Fail-closed dry-run manifest with refusals, actions and parity deltas.
    """
    context = await _load_context(db, user_id=user_id, plan_id=plan_id, list_id=list_id)
    return plan_parity_repair(context)


async def _apply_repair_actions(
    db: AsyncSession,
    *,
    plan_id: int,
    list_id: int,
    manifest: RepairManifest,
) -> list[RepairAction]:
    """Apply every manifest action inside the caller's open transaction.

    Steps are idempotent against their own durable effects and preserve every
    historical provenance row: ``(custom_cbl_lists, custom_cbl_entries)`` is
    never written and existing source snapshots are never updated or removed.

    Args:
        db: Database session with an active transaction.
        plan_id: Plan receiving the membership repair.
        list_id: Owned Reading List being durably linked.
        manifest: Valid dry-run manifest.

    Returns:
        The actions actually applied; an already-repaired plan yields an
        empty list.

    Raises:
        ValueError: When the manifest carries refusals.
    """
    if not manifest.valid:
        raise ValueError(f"Repair refused: {'; '.join(manifest.refusals)}")
    applied: list[RepairAction] = []
    new_source_id: int | None = None

    for action in manifest.actions:
        if action.kind != "link_source":
            continue
        linked = {
            row.custom_cbl_list_id
            for row in await parity_repository.load_plan_source_rows(db, plan_id=plan_id)
            if row.custom_cbl_list_id == list_id
        }
        if linked:
            continue
        source = await parity_repository.insert_plan_source(
            db,
            ReadingPlanSource(
                plan_id=plan_id,
                raw_source_path=f"custom-cbl:{list_id}",
                custom_cbl_list_id=list_id,
                metadata_json={"repair": REPAIR_INTENT_CONTRACT},
            ),
        )
        new_source_id = source.id
        applied.append(action)

    renumber: dict[str, int] = {}
    new_issue_rows: list[ReadingPlanIssue] = []
    add_action: RepairAction | None = None
    reorder_action: RepairAction | None = None
    for action in manifest.actions:
        if action.kind == "add_occurrences":
            add_action = action
            for index, row in enumerate(action.detail.get("occurrences", [])):
                if not isinstance(row, dict):
                    raise ValueError("Malformed add_occurrences detail")
                occurrence_id = str(row["occurrence_id"])
                renumber[occurrence_id] = int(row["display_position"])
                new_issue_rows.append(
                    ReadingPlanIssue(
                        plan_id=plan_id,
                        occurrence_id=occurrence_id,
                        issue_id=int(row["issue_id"]),
                        lane_id=str(row["lane_id"]),
                        # Sentinel positions keep lane uniqueness satisfied
                        # until the two-pass renumber below swaps every row.
                        display_position=-1000000 - index,
                        is_checkpoint=bool(row.get("is_checkpoint", False)),
                        source_metadata_json={
                            "authority": f"custom-cbl:{list_id}",
                            "source_position": int(row["display_position"]),
                        },
                    )
                )
        elif action.kind == "reorder_occurrences":
            moves = action.detail.get("moves", [])
            if not isinstance(moves, list):
                raise ValueError("Malformed reorder_occurrences detail")
            for move in moves:
                if not isinstance(move, dict):
                    raise ValueError("Malformed reorder_occurrences detail")
                renumber[str(move["occurrence_id"])] = int(move["to"])
            reorder_action = action

    if new_issue_rows and add_action is not None:
        await parity_repository.add_plan_issue_occurrences(
            db, plan_id=plan_id, rows=new_issue_rows
        )
        applied.append(add_action)
    if renumber:
        await parity_repository.renumber_plan_issue_positions(
            db, plan_id=plan_id, updates=list(renumber.items())
        )
    if reorder_action is not None and renumber:
        applied.append(reorder_action)

    if new_source_id is not None:
        membership_rows = await parity_repository.load_plan_issue_rows(db, plan_id=plan_id)
        placements = [
            ReadingPlanSourcePlacement(
                plan_id=plan_id,
                occurrence_id=membership.occurrence_id,
                plan_source_id=new_source_id,
                source_position=membership.display_position,
            )
            for membership in membership_rows
        ]
        if placements:
            await parity_repository.insert_plan_source_placements(
                db, plan_id=plan_id, rows=placements
            )
        placements_action = next(
            (
                action
                for action in manifest.actions
                if action.kind == "record_source_placements"
            ),
            None,
        )
        if placements_action is not None:
            applied.append(placements_action)
    return applied


async def execute_parity_repair(
    db: AsyncSession,
    *,
    user_id: int,
    plan_id: int,
    list_id: int,
    approval: ParityRepairIntent,
) -> RepairReceipt:
    """Apply an approved parity repair and self-verify inside one transaction.

    The caller owns the transaction: perform the call inside one open
    transaction and commit only after receiving a receipt with an empty
    ``residual_blocking_findings``. When self-verification detects any
    residual blocking finding, this raises so the caller can roll back
    without leaving a half-repaired plan.

    Args:
        db: Database session with an active transaction.
        user_id: Owner whose plan and List are being repaired.
        plan_id: Plan to repair.
        list_id: Owned Reading List to durably link and reconcile to.
        approval: Explicitly approved intent from :func:`parse_repair_intent`.

    Returns:
        Durable receipt with the applied actions and residual findings.

    Raises:
        ValueError: When the approval does not match this repair, or the
            manifest is refused.
        RuntimeError: When the post-apply self-verification fails.
    """
    if approval.owner_user_id != user_id or approval.plan_id != plan_id:
        raise ValueError("Approved intent does not match the requested repair target")
    if approval.list_id != list_id:
        raise ValueError("Approved intent does not match the requested Reading List")

    manifest = await plan_plan_list_parity_repair(
        db, user_id=user_id, plan_id=plan_id, list_id=list_id
    )
    applied = await _apply_repair_actions(
        db, plan_id=plan_id, list_id=list_id, manifest=manifest
    )
    parity_after = await evaluate_plan_list_parity(
        db, user_id=user_id, plan_id=plan_id, list_id=list_id
    )
    residual = _blocking_codes(parity_after)
    if residual:
        raise RuntimeError(
            f"Parity repair self-verification failed with residual findings: {residual}"
        )
    return RepairReceipt(
        plan_id=plan_id,
        list_id=list_id,
        applied_actions=tuple(applied),
        idempotent=not applied,
        residual_blocking_findings=tuple(residual),
    )


def parse_repair_intent(document: Mapping[str, object]) -> ParityRepairIntent:
    """Validate explicitly approved data-changing intent for one repair.

    The intent document is the data-changing approval gate: a worker/operator
    records which plan and List are being reconciled, for which issue, and a
    reader-intent signoff. Durability is refused without all of them.

    Args:
        document: Parsed JSON intent document.

    Returns:
        Validated intent bound to one owner, plan and list.

    Raises:
        ValueError: On any missing, empty or mismatched required field.
    """
    problems: list[str] = []
    if document.get("contract") != REPAIR_INTENT_CONTRACT:
        problems.append(f"contract must be {REPAIR_INTENT_CONTRACT!r}")
    if document.get("approved") is not True:
        problems.append("approved must be exactly true (explicit data-changing approval)")
    for key in ("owner_user_id", "plan_id", "list_id"):
        value = document.get(key)
        if not isinstance(value, int) or isinstance(value, bool) or value <= 0:
            problems.append(f"{key} must be a positive integer")
    for key in ("issue", "reader_intent_signoff"):
        value = document.get(key)
        if not isinstance(value, str) or not value.strip():
            problems.append(f"{key} must be a non-empty string")
    if problems:
        raise ValueError("Invalid parity repair intent: " + "; ".join(problems))
    return ParityRepairIntent(
        owner_user_id=int(document["owner_user_id"]),
        plan_id=int(document["plan_id"]),
        list_id=int(document["list_id"]),
        issue=str(document["issue"]),
        reader_intent_signoff=str(document["reader_intent_signoff"]),
    )

