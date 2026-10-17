"""Deterministic Option E conversion planning: dry-run manifests and receipts.

This module is pure. It performs no database access, writes nothing, and exposes
no apply/commit path. Given one reader-owned execution snapshot, the read-only
reconciliation evidence for that reader, and a reviewed reader-intent document,
it produces a deterministic conversion manifest: proposed list modes and skips,
migrated prerequisite provenance, applied exclusions, derived frontier repairs,
a before/after eligibility diff computed by the shared pure evaluator, and a
reversible before-image receipt plan for every proposed change.

Nothing here decides reader intent. Unresolved list-versus-plan differences,
non-durable source links, multiple plan lanes, ambiguous placement, and
unclassified prerequisite provenance are refused rather than guessed. Conversion
execution and production approval belong to separate manual-only issues.
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass, field
from typing import Literal

from app.services.reading_list_cycle_validator import (
    ReadingCycleError,
    validate_reading_constraints,
)
from app.services.reading_list_evaluator import (
    ReadingList,
    ReadingListEntry,
    ReadingPrerequisite,
    ReadingSnapshot,
    ThreadEligibility,
    evaluate,
)

Gate = Literal["none", "hold", "after_previous"]
Mode = Literal["strict", "loose"]
Classification = Literal["A", "B", "C", "D"]
DiscrepancyKind = Literal["list_only", "plan_only", "order_conflict", "duplicate_placement"]
PrerequisiteAction = Literal["keep_reader", "convert"]

SCHEMA_VERSION = 1


@dataclass(frozen=True, slots=True)
class ProjectEvidence:
    """Read-only reconciliation evidence for one reader-owned Reading List.

    ``plan_membership_issue_ids`` is ordered by the paired legacy plan's display
    position. ``durable_source_link`` is false when no
    ``reading_plan_sources.custom_cbl_list_id`` row pairs the plan with this list;
    matching names or timestamps never establish authority. ``foreign_source_list_ids``
    records source links that resolved to a different owned list.
    """

    list_id: int
    plan_membership_issue_ids: tuple[int, ...] = ()
    durable_source_link: bool = True
    plan_lane_count: int = 1
    foreign_source_list_ids: tuple[int, ...] = ()
    entry_row_ids: tuple[tuple[int, int], ...] = ()


@dataclass(frozen=True, slots=True)
class StoredFrontier:
    """One Thread's cached next-unread projection and legacy counters."""

    thread_id: int
    stored_next_issue_id: int | None = None
    issues_remaining: int | None = None
    total_issues: int | None = None


@dataclass(frozen=True, slots=True)
class StoredPrerequisiteEvidence:
    """Raw stored columns for one prerequisite edge, before any classification."""

    dependency_id: int
    origin: Literal["reader", "converted"] | None = None
    classification: Classification | None = None
    provenance: str | None = None
    note: str | None = None


@dataclass(frozen=True, slots=True)
class StoredExclusion:
    """Exact durable exclusion identity, including targets with no local Issues."""

    row_id: int
    provider: str | None = None
    external_volume_id: str | None = None
    thread_id: int | None = None
    issue_id: int | None = None


@dataclass(frozen=True, slots=True)
class ConversionEvidence:
    """Complete read-only conversion evidence for one reader."""

    projects: tuple[ProjectEvidence, ...] = ()
    stored_frontiers: tuple[StoredFrontier, ...] = ()
    stored_prerequisites: tuple[StoredPrerequisiteEvidence, ...] = ()
    stored_exclusions: tuple[StoredExclusion, ...] = ()
    unpaired_plan_ids: tuple[int, ...] = ()


@dataclass(frozen=True, slots=True)
class DiscrepancyKey:
    """Identity of one acknowledged list-versus-plan discrepancy."""

    issue_id: int
    kind: DiscrepancyKind


@dataclass(frozen=True, slots=True)
class ListDecision:
    """Reviewed reader intent for exactly one Reading List."""

    list_id: int
    mode: Mode
    acknowledged_discrepancies: tuple[DiscrepancyKey, ...] = ()
    skipped_issue_ids: frozenset[int] = field(default_factory=frozenset)
    gates: tuple[tuple[int, Gate], ...] = ()


@dataclass(frozen=True, slots=True)
class PrerequisiteDecision:
    """Reviewed classification of one stored prerequisite edge."""

    dependency_id: int
    action: PrerequisiteAction
    classification: Classification | None = None
    provenance: str | None = None


@dataclass(frozen=True, slots=True)
class ExclusionDecision:
    """One approved collection exclusion, resolved against local Issues by the loader."""

    provider: str | None = None
    external_volume_id: str | None = None
    thread_id: int | None = None
    issue_id: int | None = None
    resolved_issue_ids: tuple[int, ...] = ()


@dataclass(frozen=True, slots=True)
class FrontierRepairDecision:
    """Approved repair of one Thread's cached next-unread projection."""

    thread_id: int
    derived_issue_id: int | None


@dataclass(frozen=True, slots=True)
class ConversionIntent:
    """Reviewed reader intent, bound to the exact source snapshot it was written against."""

    source_fingerprint: str
    lists: tuple[ListDecision, ...] = ()
    prerequisites: tuple[PrerequisiteDecision, ...] = ()
    exclusions: tuple[ExclusionDecision, ...] = ()
    frontier_repairs: tuple[FrontierRepairDecision, ...] = ()
    schema_version: int = SCHEMA_VERSION


@dataclass(frozen=True, slots=True)
class ManifestRefusal:
    """One reason the manifest is not convertible exactly as reviewed."""

    code: str
    subject: str
    detail: str


@dataclass(frozen=True, slots=True)
class Discrepancy:
    """One list-versus-plan difference that is surfaced, never silently resolved."""

    issue_id: int
    kind: DiscrepancyKind
    detail: str


@dataclass(frozen=True, slots=True)
class ListProposal:
    """Proposed persisted intent for one Reading List."""

    list_id: int
    name: str
    before_mode: Mode
    mode: Mode
    entry_count: int
    skipped_issue_ids: tuple[int, ...]
    gates: tuple[tuple[int, Gate], ...]
    discrepancies: tuple[Discrepancy, ...]
    acknowledged: tuple[DiscrepancyKey, ...]
    changed: bool


@dataclass(frozen=True, slots=True)
class PrerequisiteProposal:
    """Proposed persisted state for one stored prerequisite edge."""

    dependency_id: int
    source_issue_id: int
    target_issue_id: int
    action: PrerequisiteAction
    before_origin: Literal["reader", "converted"]
    before_classification: Classification | None
    before_provenance: tuple[str, ...]
    origin: Literal["reader", "converted"]
    classification: Classification | None
    provenance: tuple[str, ...]
    changed: bool


@dataclass(frozen=True, slots=True)
class ExclusionProposal:
    """One approved collection exclusion with its resolved local effect."""

    provider: str | None
    external_volume_id: str | None
    thread_id: int | None
    issue_id: int | None
    resolved_issue_ids: tuple[int, ...]
    already_present: bool


@dataclass(frozen=True, slots=True)
class FrontierRepairProposal:
    """One approved cached-frontier repair; never the eligibility authority."""

    thread_id: int
    stored_next_issue_id: int | None
    derived_issue_id: int | None
    issues_remaining_before: int | None
    total_issues_before: int | None
    changed: bool


@dataclass(frozen=True, slots=True)
class EligibilityChange:
    """One active Thread whose derived frontier or blockers would change."""

    thread_id: int
    before_issue_id: int | None
    after_issue_id: int | None
    before_eligible: bool | None
    after_eligible: bool | None


@dataclass(frozen=True, slots=True)
class ReceiptRow:
    """Reversible before-image for one row the manifest would change."""

    table: str
    row_id: int | None
    before: Mapping[str, object]


@dataclass(frozen=True, slots=True)
class ConversionManifest:
    """Deterministic dry-run result: proposals, diff, receipts, and refusals."""

    schema_version: int
    read_only: bool
    user_id: int
    source_fingerprint: str
    counts: Mapping[str, object]
    lists: tuple[ListProposal, ...]
    prerequisites: tuple[PrerequisiteProposal, ...]
    prerequisites_pending_review: tuple[int, ...]
    exclusions: tuple[ExclusionProposal, ...]
    frontier_repairs: tuple[FrontierRepairProposal, ...]
    eligibility_before: Mapping[int, tuple[int | None, bool]]
    eligibility_after: Mapping[int, tuple[int | None, bool]] | None
    eligibility_changes: tuple[EligibilityChange, ...]
    receipts: tuple[ReceiptRow, ...]
    refusals: tuple[ManifestRefusal, ...]

    @property
    def valid(self) -> bool:
        """Return whether the reviewed intent applies exactly with no refusal."""
        return not self.refusals and self.eligibility_after is not None

    def to_json(self) -> dict[str, object]:
        """Return a stable JSON-compatible manifest including exact reversible before-images."""
        return {
            "schema_version": self.schema_version,
            "read_only": self.read_only,
            "user_id": self.user_id,
            "source_fingerprint": self.source_fingerprint,
            "valid": self.valid,
            "counts": dict(self.counts),
            "lists": [
                {
                    "list_id": row.list_id,
                    "name": row.name,
                    "before_mode": row.before_mode,
                    "mode": row.mode,
                    "entry_count": row.entry_count,
                    "skipped_issue_ids": list(row.skipped_issue_ids),
                    "gates": [[issue_id, gate] for issue_id, gate in row.gates],
                    "changed": row.changed,
                    "acknowledged": [
                        {"issue_id": key.issue_id, "kind": key.kind} for key in row.acknowledged
                    ],
                    "discrepancies": [
                        {"issue_id": d.issue_id, "kind": d.kind, "detail": d.detail}
                        for d in row.discrepancies
                    ],
                }
                for row in self.lists
            ],
            "prerequisites": [
                {
                    "dependency_id": row.dependency_id,
                    "source_issue_id": row.source_issue_id,
                    "target_issue_id": row.target_issue_id,
                    "action": row.action,
                    "before_origin": row.before_origin,
                    "before_classification": row.before_classification,
                    "before_provenance": list(row.before_provenance),
                    "origin": row.origin,
                    "classification": row.classification,
                    "provenance": list(row.provenance),
                    "changed": row.changed,
                }
                for row in self.prerequisites
            ],
            "prerequisites_pending_review": list(self.prerequisites_pending_review),
            "exclusions": [
                {
                    "provider": row.provider,
                    "external_volume_id": row.external_volume_id,
                    "thread_id": row.thread_id,
                    "issue_id": row.issue_id,
                    "resolved_issue_ids": list(row.resolved_issue_ids),
                    "already_present": row.already_present,
                }
                for row in self.exclusions
            ],
            "frontier_repairs": [
                {
                    "thread_id": row.thread_id,
                    "stored_next_issue_id": row.stored_next_issue_id,
                    "derived_issue_id": row.derived_issue_id,
                    "issues_remaining_before": row.issues_remaining_before,
                    "total_issues_before": row.total_issues_before,
                    "changed": row.changed,
                }
                for row in self.frontier_repairs
            ],
            "eligibility": {
                "before": {
                    str(thread_id): {"next_issue_id": value[0], "eligible": value[1]}
                    for thread_id, value in sorted(self.eligibility_before.items())
                },
                "after": (
                    {
                        str(thread_id): {"next_issue_id": value[0], "eligible": value[1]}
                        for thread_id, value in sorted(self.eligibility_after.items())
                    }
                    if self.eligibility_after is not None
                    else None
                ),
                "changes": [
                    {
                        "thread_id": row.thread_id,
                        "before_issue_id": row.before_issue_id,
                        "after_issue_id": row.after_issue_id,
                        "before_eligible": row.before_eligible,
                        "after_eligible": row.after_eligible,
                    }
                    for row in self.eligibility_changes
                ],
            },
            "receipts": [
                {"table": row.table, "row_id": row.row_id, "before": dict(row.before)}
                for row in self.receipts
            ],
            "refusals": [
                {"code": row.code, "subject": row.subject, "detail": row.detail}
                for row in self.refusals
            ],
        }


def derived_frontier(snapshot: ReadingSnapshot) -> dict[int, int]:
    """Derive each Thread frontier from ``(position, issue_id)`` and global read state."""
    result: dict[int, int] = {}
    for issue in sorted(snapshot.issues, key=lambda row: (row.position, row.issue_id)):
        if issue.status != "read" and issue.issue_id not in snapshot.excluded_issue_ids:
            result.setdefault(issue.thread_id, issue.issue_id)
    return result


def _canonical_snapshot(
    snapshot: ReadingSnapshot, evidence: ConversionEvidence
) -> dict[str, object]:
    return {
        "user_id": snapshot.user_id,
        "unpaired_plan_ids": sorted(evidence.unpaired_plan_ids),
        "threads": sorted([t.thread_id, t.status, t.name] for t in snapshot.threads),
        "issues": sorted([i.issue_id, i.thread_id, i.position, i.status] for i in snapshot.issues),
        "lists": sorted(
            [
                row.list_id,
                row.mode,
                row.name,
                [[e.issue_id, e.gate, e.skipped] for e in row.entries],
            ]
            for row in snapshot.lists
        ),
        "prerequisites": sorted(
            [
                p.prerequisite_id,
                p.source_issue_id,
                p.target_issue_id,
                p.origin,
                list(p.provenance),
            ]
            for p in snapshot.prerequisites
        ),
        "excluded_issue_ids": sorted(snapshot.excluded_issue_ids),
        "projects": sorted(
            [
                p.list_id,
                list(p.plan_membership_issue_ids),
                p.durable_source_link,
                p.plan_lane_count,
                sorted(p.foreign_source_list_ids),
                [list(pair) for pair in sorted(p.entry_row_ids)],
            ]
            for p in evidence.projects
        ),
        "stored_frontiers": sorted(
            [
                f.thread_id,
                -1 if f.stored_next_issue_id is None else f.stored_next_issue_id,
                -1 if f.issues_remaining is None else f.issues_remaining,
                -1 if f.total_issues is None else f.total_issues,
            ]
            for f in evidence.stored_frontiers
        ),
        "stored_exclusions": sorted(
            [row.row_id, row.provider, row.external_volume_id, row.thread_id, row.issue_id]
            for row in evidence.stored_exclusions
        ),
        "stored_prerequisites": sorted(
            [
                row.dependency_id,
                row.origin or "",
                row.classification or "",
                row.provenance or "",
                row.note or "",
            ]
            for row in evidence.stored_prerequisites
        ),
    }


def snapshot_fingerprint(snapshot: ReadingSnapshot, evidence: ConversionEvidence) -> str:
    """Return the deterministic fingerprint a reviewed intent must be written against."""
    canonical = json.dumps(
        _canonical_snapshot(snapshot, evidence), sort_keys=True, separators=(",", ":")
    )
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def _list_by_id(snapshot: ReadingSnapshot) -> dict[int, ReadingList]:
    return {row.list_id: row for row in snapshot.lists}


def _discrepancies(reading_list: ReadingList, membership: Sequence[int]) -> tuple[Discrepancy, ...]:
    """Surface every list-versus-plan difference in both directions and in order."""
    entries = [entry.issue_id for entry in reading_list.entries]
    found: list[Discrepancy] = []
    counts: dict[int, int] = {}
    for issue_id in membership:
        counts[issue_id] = counts.get(issue_id, 0) + 1
    for issue_id, count in counts.items():
        if count > 1:
            found.append(
                Discrepancy(
                    issue_id,
                    "duplicate_placement",
                    f"plan membership repeats Issue {issue_id} {count} times",
                )
            )
    in_list = set(entries)
    in_plan = set(membership)
    for issue_id in sorted(in_list - in_plan):
        found.append(
            Discrepancy(issue_id, "list_only", f"Issue {issue_id} is in the list, not the plan")
        )
    for issue_id in sorted(in_plan - in_list):
        found.append(
            Discrepancy(issue_id, "plan_only", f"Issue {issue_id} is in the plan, not the list")
        )
    shared = [issue_id for issue_id in entries if issue_id in in_plan]
    plan_shared = [issue_id for issue_id in membership if issue_id in in_list]
    if shared != plan_shared:
        moved = sorted(set(shared) ^ set(plan_shared)) or shared
        found.append(
            Discrepancy(
                shared[0] if shared else sorted(in_list & in_plan)[0],
                "order_conflict",
                "list and plan order disagree for Issues "
                + ", ".join(str(issue_id) for issue_id in moved[:10]),
            )
        )
    return tuple(found)


def _eligibility_map(result: Mapping[int, ThreadEligibility]) -> dict[int, tuple[int | None, bool]]:
    return {
        thread_id: (row.next_issue_id, row.eligible) for thread_id, row in sorted(result.items())
    }


def build_manifest(
    snapshot: ReadingSnapshot,
    evidence: ConversionEvidence,
    intent: ConversionIntent,
) -> ConversionManifest:
    """Translate reviewed reader intent into a deterministic, refusable manifest.

    Args:
        snapshot: Complete current reader execution inputs.
        evidence: Read-only reconciliation evidence for the same reader.
        intent: Reviewed intent bound to ``snapshot`` by fingerprint.

    Returns:
        Manifest carrying proposals, the before/after eligibility diff, reversible
        receipts, and every refusal. ``valid`` is false when any refusal exists.
    """
    refusals: list[ManifestRefusal] = []
    fingerprint = snapshot_fingerprint(snapshot, evidence)
    lists_by_id = _list_by_id(snapshot)
    counts: dict[str, object] = {
        "threads": len(snapshot.threads),
        "issues": len(snapshot.issues),
        "lists": len(snapshot.lists),
        "list_entries": sum(len(row.entries) for row in snapshot.lists),
        "prerequisites": len(snapshot.prerequisites),
        "excluded_issues": len(snapshot.excluded_issue_ids),
    }
    before_result: dict[int, ThreadEligibility] | None
    try:
        before_result = evaluate(snapshot)
    except ValueError as error:
        before_result = None
        refusals.append(ManifestRefusal("invalid_current_snapshot", "reader", str(error)))
    if intent.source_fingerprint != fingerprint:
        refusals.append(
            ManifestRefusal(
                "stale_snapshot",
                "intent",
                "Reviewed intent fingerprint does not match the current read-only snapshot",
            )
        )
        return ConversionManifest(
            SCHEMA_VERSION,
            True,
            snapshot.user_id,
            fingerprint,
            counts,
            (),
            (),
            (),
            (),
            (),
            _eligibility_map(before_result) if before_result is not None else {},
            None,
            (),
            (),
            tuple(refusals),
        )

    for plan_id in evidence.unpaired_plan_ids:
        refusals.append(
            ManifestRefusal(
                "source_mismatch",
                f"plan:{plan_id}",
                "Legacy plan has no durable owned list pairing",
            )
        )
    if intent.schema_version != SCHEMA_VERSION:
        refusals.append(
            ManifestRefusal("schema_version", "intent", "Unsupported intent schema version")
        )
    evidence_by_id = {row.list_id: row for row in evidence.projects}
    for reading_list in snapshot.lists:
        if reading_list.list_id not in {row.list_id for row in intent.lists}:
            refusals.append(
                ManifestRefusal(
                    "unreviewed_list",
                    f"list:{reading_list.list_id}",
                    "Every list requires a reviewed mode and reconciliation",
                )
            )
    decisions: dict[int, ListDecision] = {}
    proposals: list[ListProposal] = []
    receipts: list[ReceiptRow] = []
    for decision in intent.lists:
        reading_list = lists_by_id.get(decision.list_id)
        if reading_list is None:
            refusals.append(
                ManifestRefusal("unknown_reference", f"list:{decision.list_id}", "List not found")
            )
            continue
        if decision.list_id in decisions:
            refusals.append(
                ManifestRefusal(
                    "duplicate_decision", f"list:{decision.list_id}", "Repeated list decision"
                )
            )
            continue
        decisions[decision.list_id] = decision
        project = evidence_by_id.get(
            decision.list_id, ProjectEvidence(decision.list_id, durable_source_link=False)
        )
        discrepancies = (
            _discrepancies(reading_list, project.plan_membership_issue_ids)
            if project.durable_source_link or project.plan_membership_issue_ids
            else ()
        )
        if project.plan_membership_issue_ids and not project.durable_source_link:
            refusals.append(
                ManifestRefusal(
                    "source_mismatch",
                    f"list:{decision.list_id}",
                    "Plan membership has no durable custom_cbl_list_id source link",
                )
            )
        if project.foreign_source_list_ids:
            refusals.append(
                ManifestRefusal(
                    "source_mismatch",
                    f"list:{decision.list_id}",
                    "Source links resolve to other lists: "
                    + ", ".join(str(value) for value in sorted(project.foreign_source_list_ids)),
                )
            )
        if project.plan_lane_count > 1:
            refusals.append(
                ManifestRefusal(
                    "ambiguous_placement",
                    f"list:{decision.list_id}",
                    f"Plan has {project.plan_lane_count} lanes; no multi-lane runtime exists",
                )
            )
        acknowledged = tuple(decision.acknowledged_discrepancies)
        accredited = {(key.issue_id, key.kind) for key in acknowledged}
        for discrepancy in discrepancies:
            if (discrepancy.issue_id, discrepancy.kind) not in accredited:
                refusals.append(
                    ManifestRefusal(
                        "unresolved_discrepancy",
                        f"list:{decision.list_id}",
                        discrepancy.detail,
                    )
                )
        entry_issue_ids = {entry.issue_id for entry in reading_list.entries}
        for issue_id in sorted(decision.skipped_issue_ids - entry_issue_ids):
            refusals.append(
                ManifestRefusal(
                    "unknown_reference",
                    f"list:{decision.list_id}",
                    f"Skip references Issue {issue_id} not in the list",
                )
            )
        gates = tuple(sorted(decision.gates))
        for issue_id, gate in gates:
            if gate not in ("none", "hold", "after_previous"):
                refusals.append(
                    ManifestRefusal(
                        "unknown_gate", f"list:{decision.list_id}", f"Unsupported gate {gate!r}"
                    )
                )
            if issue_id not in entry_issue_ids:
                refusals.append(
                    ManifestRefusal(
                        "unknown_reference",
                        f"list:{decision.list_id}",
                        f"Gate references Issue {issue_id} not in the list",
                    )
                )
            elif issue_id in decision.skipped_issue_ids:
                refusals.append(
                    ManifestRefusal(
                        "ambiguous_placement",
                        f"list:{decision.list_id}",
                        f"Issue {issue_id} is both skipped and gated",
                    )
                )
        before_gates = tuple(
            sorted((e.issue_id, e.gate) for e in reading_list.entries if e.gate != "none")
        )
        before_skips = tuple(sorted(e.issue_id for e in reading_list.entries if e.skipped))
        gate_updates = dict(gates)
        if len(gate_updates) != len(gates):
            refusals.append(
                ManifestRefusal(
                    "duplicate_decision", f"list:{decision.list_id}", "Repeated gate decision"
                )
            )
        after_gates = tuple(
            sorted(
                (entry.issue_id, gate_updates.get(entry.issue_id, entry.gate))
                for entry in reading_list.entries
                if gate_updates.get(entry.issue_id, entry.gate) != "none"
            )
        )
        after_skips = tuple(sorted(set(before_skips) | decision.skipped_issue_ids))
        changed = (
            reading_list.mode != decision.mode
            or before_gates != after_gates
            or before_skips != after_skips
        )
        entry_row_ids = dict(project.entry_row_ids)
        if changed:
            receipts.append(
                ReceiptRow(
                    "custom_cbl_lists",
                    reading_list.list_id,
                    {
                        "mode": reading_list.mode,
                        "name": reading_list.name,
                    },
                )
            )
            for entry in reading_list.entries:
                after_gate = dict(decision.gates).get(entry.issue_id, entry.gate)
                after_skip = entry.issue_id in decision.skipped_issue_ids or entry.skipped
                if entry.gate == after_gate and entry.skipped == after_skip:
                    continue
                if entry.issue_id not in entry_row_ids:
                    refusals.append(
                        ManifestRefusal(
                            "missing_row_identity",
                            f"list:{decision.list_id}",
                            f"Missing entry row ID for Issue {entry.issue_id}",
                        )
                    )
                    continue
                receipts.append(
                    ReceiptRow(
                        "custom_cbl_entries",
                        entry_row_ids[entry.issue_id],
                        {"issue_id": entry.issue_id, "gate": entry.gate, "skipped": entry.skipped},
                    )
                )
        proposals.append(
            ListProposal(
                reading_list.list_id,
                reading_list.name,
                reading_list.mode,
                decision.mode,
                len(reading_list.entries),
                after_skips,
                after_gates,
                discrepancies,
                acknowledged,
                changed,
            )
        )

    by_id = {row.prerequisite_id: row for row in snapshot.prerequisites}
    raw_by_id = {row.dependency_id: row for row in evidence.stored_prerequisites}
    states: dict[int, PrerequisiteProposal] = {}
    decided: set[int] = set()
    prerequisite_proposals: list[PrerequisiteProposal] = []
    for decision in intent.prerequisites:
        row = by_id.get(decision.dependency_id)
        if row is None:
            refusals.append(
                ManifestRefusal(
                    "unknown_reference",
                    f"dependency:{decision.dependency_id}",
                    "Stored prerequisite not found",
                )
            )
            continue
        if row.prerequisite_id in decided:
            refusals.append(
                ManifestRefusal(
                    "duplicate_decision",
                    f"dependency:{row.prerequisite_id}",
                    "Repeated prerequisite decision",
                )
            )
            continue
        raw = raw_by_id.get(row.prerequisite_id)
        decided.add(row.prerequisite_id)
        before_origin: Literal["reader", "converted"] = (
            raw.origin if raw is not None and raw.origin is not None else row.origin
        )
        before_classification = raw.classification if raw is not None else None
        before_provenance = (
            tuple(value for value in (raw.provenance, raw.note) if value)
            if raw is not None
            else row.provenance
        )
        if decision.action == "convert":
            converted_text = (decision.provenance or "").strip()
            if decision.classification not in ("A", "B", "C") or not converted_text:
                refusals.append(
                    ManifestRefusal(
                        "unresolved_provenance",
                        f"dependency:{row.prerequisite_id}",
                        "Conversion requires a reviewed A/B/C classification and provenance",
                    )
                )
                continue
            converted_provenance = (converted_text,)
            proposal = PrerequisiteProposal(
                row.prerequisite_id,
                row.source_issue_id,
                row.target_issue_id,
                decision.action,
                before_origin,
                before_classification,
                before_provenance,
                "converted",
                decision.classification,
                converted_provenance,
                before_origin != "converted"
                or before_classification != decision.classification
                or before_provenance != converted_provenance,
            )
        else:
            proposal = PrerequisiteProposal(
                row.prerequisite_id,
                row.source_issue_id,
                row.target_issue_id,
                decision.action,
                before_origin,
                before_classification,
                before_provenance,
                "reader",
                before_classification,
                before_provenance,
                before_origin != "reader",
            )
        if proposal.changed:
            receipts.append(
                ReceiptRow(
                    "dependencies",
                    row.prerequisite_id,
                    {
                        "origin": raw.origin if raw is not None else None,
                        "classification": before_classification,
                        "provenance": raw.provenance if raw is not None else None,
                        "note": raw.note if raw is not None else None,
                        "source_issue_id": row.source_issue_id,
                        "target_issue_id": row.target_issue_id,
                    },
                )
            )
        states[row.prerequisite_id] = proposal
        prerequisite_proposals.append(proposal)

    pending = tuple(
        sorted(
            row.prerequisite_id
            for row in snapshot.prerequisites
            if row.prerequisite_id not in decided
            and row.origin != "reader"
            and (
                row.prerequisite_id not in raw_by_id
                or raw_by_id[row.prerequisite_id].classification in (None, "D")
            )
        )
    )

    for dependency_id in pending:
        refusals.append(
            ManifestRefusal(
                "unresolved_provenance",
                f"dependency:{dependency_id}",
                "Stored prerequisite requires an explicit reviewed classification",
            )
        )

    exclusions: list[ExclusionProposal] = []
    new_excluded: set[int] = set()
    for decision in intent.exclusions:
        targets = [
            decision.external_volume_id is not None,
            decision.thread_id is not None,
            decision.issue_id is not None,
        ]
        if sum(targets) != 1 or (decision.provider is not None) != (
            decision.external_volume_id is not None
        ):
            refusals.append(
                ManifestRefusal(
                    "invalid_exclusion_target",
                    "exclusion",
                    "Exactly one of external_volume_id, thread_id or issue_id is required",
                )
            )
            continue
        if decision.thread_id is not None and decision.thread_id not in {
            row.thread_id for row in snapshot.threads
        }:
            refusals.append(
                ManifestRefusal("unknown_reference", "exclusion", "Thread exclusion is not owned")
            )
            continue
        resolved = set(decision.resolved_issue_ids)
        if decision.issue_id is not None:
            resolved = {decision.issue_id}
        elif decision.thread_id is not None:
            resolved = {
                issue.issue_id for issue in snapshot.issues if issue.thread_id == decision.thread_id
            }
        if decision.external_volume_id is not None and not decision.provider:
            refusals.append(
                ManifestRefusal("invalid_exclusion_target", "exclusion", "A provider is required")
            )
            continue
        unknown = resolved - {issue.issue_id for issue in snapshot.issues}
        if unknown:
            refusals.append(
                ManifestRefusal(
                    "unknown_reference",
                    "exclusion",
                    "Exclusion resolves to unknown Issues "
                    + ", ".join(str(value) for value in sorted(unknown)),
                )
            )
            continue
        already = any(
            (row.provider, row.external_volume_id, row.thread_id, row.issue_id)
            == (
                decision.provider,
                decision.external_volume_id,
                decision.thread_id,
                decision.issue_id,
            )
            for row in evidence.stored_exclusions
        )
        new_excluded.update(resolved - snapshot.excluded_issue_ids)
        if not already:
            receipts.append(
                ReceiptRow(
                    "collection_exclusions",
                    None,
                    {
                        "action": "insert",
                        "provider": decision.provider,
                        "external_volume_id": decision.external_volume_id,
                        "thread_id": decision.thread_id,
                        "issue_id": decision.issue_id,
                        "resolved_issue_ids": sorted(resolved),
                    },
                )
            )
        exclusions.append(
            ExclusionProposal(
                decision.provider,
                decision.external_volume_id,
                decision.thread_id,
                decision.issue_id,
                tuple(sorted(resolved)),
                already,
            )
        )

    frontiers: list[FrontierRepairProposal] = []
    derived: dict[int, int] = {}
    for issue in sorted(snapshot.issues, key=lambda row: (row.position, row.issue_id)):
        if (
            issue.status != "read"
            and issue.issue_id not in snapshot.excluded_issue_ids | new_excluded
        ):
            derived.setdefault(issue.thread_id, issue.issue_id)
    stored_by_thread = {row.thread_id: row for row in evidence.stored_frontiers}
    for decision in intent.frontier_repairs:
        stored = stored_by_thread.get(decision.thread_id)
        if stored is None:
            refusals.append(
                ManifestRefusal(
                    "unknown_reference",
                    f"thread:{decision.thread_id}",
                    "Stored frontier row not found",
                )
            )
            continue
        expected = derived.get(decision.thread_id)
        if decision.derived_issue_id != expected:
            refusals.append(
                ManifestRefusal(
                    "frontier_repair_mismatch",
                    f"thread:{decision.thread_id}",
                    "Repair target differs from the derived frontier authority",
                )
            )
            continue
        changed = stored.stored_next_issue_id != decision.derived_issue_id
        if changed:
            receipts.append(
                ReceiptRow(
                    "threads",
                    decision.thread_id,
                    {
                        "next_unread_issue_id": stored.stored_next_issue_id,
                        "issues_remaining": stored.issues_remaining,
                        "total_issues": stored.total_issues,
                    },
                )
            )
        frontiers.append(
            FrontierRepairProposal(
                decision.thread_id,
                stored.stored_next_issue_id,
                decision.derived_issue_id,
                stored.issues_remaining,
                stored.total_issues,
                changed,
            )
        )

    after_result: dict[int, ThreadEligibility] | None = None
    projected: ReadingSnapshot | None = None
    if not refusals:
        try:
            projected = _project_snapshot(snapshot, decisions, states, frozenset(new_excluded))
            validate_reading_constraints(projected)
            after_result = evaluate(projected)
        except ReadingCycleError as error:
            refusals.append(
                ManifestRefusal(
                    "reading_cycle",
                    "graph",
                    "; ".join(
                        f"{edge.source_issue_id}->{edge.target_issue_id} ({edge.origin})"
                        for edge in error.edges[:20]
                    ),
                )
            )
        except ValueError as error:
            refusals.append(ManifestRefusal("invalid_projection", "graph", str(error)))

    changes: tuple[EligibilityChange, ...] = ()
    if before_result is not None and after_result is not None:
        rows: list[EligibilityChange] = []
        for thread_id in sorted(set(before_result) | set(after_result)):
            before_row = before_result.get(thread_id)
            after_row = after_result.get(thread_id)
            before_issue = before_row.next_issue_id if before_row is not None else None
            after_issue = after_row.next_issue_id if after_row is not None else None
            before_eligible = before_row.eligible if before_row is not None else None
            after_eligible = after_row.eligible if after_row is not None else None
            if (before_issue, before_eligible) != (after_issue, after_eligible):
                rows.append(
                    EligibilityChange(
                        thread_id, before_issue, after_issue, before_eligible, after_eligible
                    )
                )
        changes = tuple(rows)

    counts["list_discrepancies"] = sum(len(row.discrepancies) for row in proposals)
    counts["prerequisites_converted"] = sum(
        1 for row in prerequisite_proposals if row.action == "convert"
    )
    counts["exclusions_proposed"] = len(exclusions)
    counts["frontier_repairs"] = sum(1 for row in frontiers if row.changed)
    counts["eligible_threads_before"] = sum(
        1 for row in (before_result or {}).values() if row.eligible
    )
    counts["eligible_threads_after"] = (
        sum(1 for row in after_result.values() if row.eligible)
        if after_result is not None
        else None
    )
    return ConversionManifest(
        SCHEMA_VERSION,
        True,
        snapshot.user_id,
        fingerprint,
        counts,
        tuple(proposals),
        tuple(prerequisite_proposals),
        pending,
        tuple(exclusions),
        tuple(frontiers),
        _eligibility_map(before_result) if before_result is not None else {},
        _eligibility_map(after_result) if after_result is not None else None,
        changes,
        tuple(receipts),
        tuple(refusals),
    )


def _project_snapshot(
    snapshot: ReadingSnapshot,
    decisions: Mapping[int, ListDecision],
    states: Mapping[int, PrerequisiteProposal],
    new_excluded: frozenset[int],
) -> ReadingSnapshot:
    """Apply reviewed list and prerequisite intent to an in-memory snapshot."""
    lists: list[ReadingList] = []
    for reading_list in snapshot.lists:
        decision = decisions.get(reading_list.list_id)
        if decision is None:
            lists.append(reading_list)
            continue
        gates = dict(decision.gates)
        entries = tuple(
            ReadingListEntry(
                entry.issue_id,
                gates.get(entry.issue_id, entry.gate),
                entry.issue_id in decision.skipped_issue_ids or entry.skipped,
            )
            for entry in reading_list.entries
        )
        lists.append(ReadingList(reading_list.list_id, decision.mode, entries, reading_list.name))
    prerequisites: list[ReadingPrerequisite] = []
    for row in snapshot.prerequisites:
        state = states.get(row.prerequisite_id)
        if state is None:
            prerequisites.append(row)
            continue
        prerequisites.append(
            ReadingPrerequisite(
                row.prerequisite_id,
                row.source_issue_id,
                row.target_issue_id,
                state.origin,
                state.provenance,
            )
        )
    return ReadingSnapshot(
        snapshot.user_id,
        tuple(snapshot.threads),
        tuple(snapshot.issues),
        tuple(lists),
        tuple(prerequisites),
        snapshot.excluded_issue_ids | new_excluded,
    )


def iter_receipt_tables(receipts: Iterable[ReceiptRow]) -> tuple[str, ...]:
    """Return the sorted distinct tables a receipt plan would touch."""
    return tuple(sorted({row.table for row in receipts}))
