"""Audit and reconciliation tooling for Reading Plan membership uniqueness.

Reading Plan membership is set membership, so one canonical Issue belongs to a
plan at most once (``uq_reading_plan_issue_plan_issue``). Rows written before
that constraint existed can still violate it, so this module answers two
operational questions with deterministic, reviewable output:

- *audit*: which plans violate the invariant, and what exactly disagrees;
- *reconcile*: which occurrence survives, which are removed, and which import
  provenance must move or be dropped.

Query construction and persistence for this model family live in
``app/repositories/reading_plan_repository.py``; this module only decides.
``scripts/audit_reading_plan_duplicate_memberships.py`` is the repeatable
command that drives these functions, and no function here mutates state on its
own: ``create_reconciliation_plan`` is pure, and mutation happens only through
the explicit ``apply_reconciliation_plan`` call.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from sqlalchemy.ext.asyncio import AsyncSession

from app.models.reading_plan_membership import ReadingPlanIssue
from app.repositories import reading_plan_repository

#: Membership fields whose disagreement between duplicate occurrences makes a
#: collapse a review decision rather than a mechanical repair.
CONFLICTING_MEMBERSHIP_FIELDS = (
    "lane_id",
    "label",
    "reader_role",
    "reader_optional",
    "is_checkpoint",
)


@dataclass(frozen=True)
class DuplicateIssueMembership:
    """One canonical Issue with more than one membership occurrence in a plan."""

    plan_id: int
    issue_id: int
    occurrence_ids: tuple[str, ...]
    lane_ids: tuple[str, ...]
    display_positions: tuple[int, ...]
    labels: tuple[str | None, ...]
    reader_roles: tuple[str | None, ...]
    reader_optionals: tuple[bool | None, ...]
    is_checkpoints: tuple[bool, ...]
    source_metadata: tuple[dict[str, object] | None, ...]

    @property
    def count(self) -> int:
        """Number of duplicate occurrences recorded for this canonical Issue."""
        return len(self.occurrence_ids)

    @property
    def conflicting_fields(self) -> tuple[str, ...]:
        """Membership fields whose occurrences disagree with each other.

        A disagreement is not guessed away. The deterministic collapse rule
        still picks a survivor, but reconciliation surfaces these fields so an
        operator can review the difference instead of discovering it later.
        """
        values = {
            "lane_id": self.lane_ids,
            "label": self.labels,
            "reader_role": self.reader_roles,
            "reader_optional": self.reader_optionals,
            "is_checkpoint": self.is_checkpoints,
        }
        return tuple(
            name
            for name in CONFLICTING_MEMBERSHIP_FIELDS
            if len(set(values[name])) > 1
        )

    @property
    def has_conflicts(self) -> bool:
        """Whether collapsing this duplicate would discard reader-visible state."""
        return bool(self.conflicting_fields)


@dataclass(frozen=True)
class PlanDuplicateReport:
    """Every duplicate canonical Issue membership found in one plan."""

    plan_id: int
    duplicates: tuple[DuplicateIssueMembership, ...]

    @property
    def total_duplicate_issues(self) -> int:
        """Number of distinct canonical Issues with duplicate membership."""
        return len(self.duplicates)

    @property
    def total_extra_occurrences(self) -> int:
        """Occurrences that would be removed beyond one survivor per Issue."""
        return sum(duplicate.count - 1 for duplicate in self.duplicates)

    @property
    def conflicting_issue_ids(self) -> tuple[int, ...]:
        """Canonical Issues whose duplicates disagree on reader-visible state."""
        return tuple(
            duplicate.issue_id
            for duplicate in self.duplicates
            if duplicate.has_conflicts
        )


@dataclass(frozen=True)
class ReconciliationPlan:
    """Deterministic collapse decision for one plan's duplicate memberships.

    ``primary_occurrence_ids`` records the surviving occurrence per canonical
    Issue; ``occurrence_map`` is the same decision expressed as a rewrite from a
    removed occurrence to its survivor so import provenance can follow it.
    """

    plan_id: int
    primary_occurrence_ids: dict[int, str] = field(default_factory=dict)
    occurrence_map: dict[str, str] = field(default_factory=dict)
    conflicting_issue_ids: tuple[int, ...] = ()

    @property
    def removal_occurrence_ids(self) -> list[str]:
        """Occurrences to delete, in deterministic removal order."""
        return [
            occurrence_id
            for occurrence_id, _survivor in self.occurrence_map.items()
        ]

    @property
    def has_conflicts(self) -> bool:
        """Whether this collapse would discard reader-visible state."""
        return bool(self.conflicting_issue_ids)


@dataclass(frozen=True)
class PlanAuditResult:
    """Audit result for one plan, optionally including every plan."""

    reports: tuple[PlanDuplicateReport, ...]

    @property
    def total_duplicate_issues(self) -> int:
        """Distinct canonical Issues with duplicate membership across the audit."""
        return sum(report.total_duplicate_issues for report in self.reports)

    @property
    def total_extra_occurrences(self) -> int:
        """Occurrences removable across the audit."""
        return sum(report.total_extra_occurrences for report in self.reports)

    @property
    def is_clean(self) -> bool:
        """Whether every audited plan satisfies the membership invariant."""
        return not self.reports


def _duplicate_membership(
    plan_id: int, issue_id: int, rows: list[ReadingPlanIssue]
) -> DuplicateIssueMembership:
    """Build one duplicate report entry from a plan's occurrence rows."""
    return DuplicateIssueMembership(
        plan_id=plan_id,
        issue_id=issue_id,
        occurrence_ids=tuple(row.occurrence_id for row in rows),
        lane_ids=tuple(row.lane_id for row in rows),
        display_positions=tuple(row.display_position for row in rows),
        labels=tuple(row.label for row in rows),
        reader_roles=tuple(row.reader_role for row in rows),
        reader_optionals=tuple(row.reader_optional for row in rows),
        is_checkpoints=tuple(row.is_checkpoint for row in rows),
        source_metadata=tuple(row.source_metadata_json for row in rows),
    )


async def audit_plan_duplicate_memberships(
    db: AsyncSession, *, plan_id: int
) -> PlanDuplicateReport:
    """Audit one plan for duplicate canonical Issue membership.

    Args:
        db: Database session.
        plan_id: Plan to audit.

    Returns:
        Report of every canonical Issue with more than one occurrence.
    """
    rows = await reading_plan_repository.list_plan_issue_occurrences_by_issue(
        db, plan_id=plan_id
    )
    by_issue: dict[int, list[ReadingPlanIssue]] = {}
    for row in rows:
        by_issue.setdefault(row.issue_id, []).append(row)
    return PlanDuplicateReport(
        plan_id=plan_id,
        duplicates=tuple(
            _duplicate_membership(plan_id, issue_id, occurrences)
            for issue_id, occurrences in sorted(by_issue.items())
            if len(occurrences) > 1
        ),
    )


async def audit_reading_plan_duplicate_memberships(
    db: AsyncSession, *, plan_id: int | None = None
) -> PlanAuditResult:
    """Audit one plan, or every plan that owns membership rows.

    Args:
        db: Database session.
        plan_id: Restrict the audit to one plan; None audits every plan.

    Returns:
        Reports for the audited plans that violate the membership invariant.
    """
    plan_ids = (
        [plan_id]
        if plan_id is not None
        else await reading_plan_repository.list_plan_ids_with_membership(db)
    )
    reports: list[PlanDuplicateReport] = []
    for audited_plan_id in plan_ids:
        report = await audit_plan_duplicate_memberships(db, plan_id=audited_plan_id)
        if report.total_duplicate_issues > 0:
            reports.append(report)
    return PlanAuditResult(reports=tuple(reports))


def create_reconciliation_plan(report: PlanDuplicateReport) -> ReconciliationPlan:
    """Decide deterministically how to collapse one plan's duplicates.

    The surviving occurrence of each canonical Issue is the lowest
    ``(display_position, occurrence_id)`` pair, matching the rule
    ``normalize_plan_nodes`` applies on the write path. Reader-visible
    disagreements are recorded in ``conflicting_issue_ids`` rather than being
    resolved by guessing.

    Args:
        report: Duplicate membership report for one plan.

    Returns:
        The collapse decision for that plan.
    """
    occurrence_map: dict[str, str] = {}
    primary_occurrence_ids: dict[int, str] = {}
    for duplicate in sorted(
        report.duplicates,
        key=lambda entry: (entry.display_positions[0], entry.occurrence_ids[0]),
    ):
        ordered = sorted(
            (position, occurrence_id)
            for position, occurrence_id in zip(
                duplicate.display_positions, duplicate.occurrence_ids, strict=True
            )
        )
        survivor = ordered[0][1]
        primary_occurrence_ids[duplicate.issue_id] = survivor
        for _position, occurrence_id in ordered[1:]:
            occurrence_map[occurrence_id] = survivor
    return ReconciliationPlan(
        plan_id=report.plan_id,
        primary_occurrence_ids=primary_occurrence_ids,
        occurrence_map=occurrence_map,
        conflicting_issue_ids=report.conflicting_issue_ids,
    )


async def apply_reconciliation_plan(
    db: AsyncSession, *, plan: ReconciliationPlan
) -> None:
    """Collapse one plan's duplicate membership rows inside the caller's transaction.

    Provenance follows the collapse: placements that would become an exact
    duplicate of provenance the survivor already owns are dropped first, the
    rest are re-pointed at the survivor, and any placement still referencing a
    removed occurrence is deleted. Source snapshots are never removed.

    Args:
        db: Database session owned by the caller.
        plan: Collapse decision to apply.
    """
    removed = plan.removal_occurrence_ids
    if not removed:
        return
    await reading_plan_repository.prune_redundant_plan_source_placements(
        db, plan_id=plan.plan_id, occurrence_map=plan.occurrence_map
    )
    await reading_plan_repository.repoint_plan_source_placements(
        db, plan_id=plan.plan_id, occurrence_map=plan.occurrence_map
    )
    await reading_plan_repository.delete_plan_source_placements_for_occurrences(
        db, plan_id=plan.plan_id, occurrence_ids=removed
    )
    await reading_plan_repository.delete_plan_issue_occurrences(
        db, plan_id=plan.plan_id, occurrence_ids=removed
    )


async def reconcile_reading_plan_duplicate_memberships(
    db: AsyncSession,
    *,
    plan_id: int | None = None,
    allow_conflicts: bool = False,
) -> PlanAuditResult:
    """Audit and then collapse duplicate membership for one plan or every plan.

    Args:
        db: Database session owned by the caller; nothing is committed here.
        plan_id: Restrict reconciliation to one plan; None covers every plan.
        allow_conflicts: Collapse even when duplicate occurrences disagree on
            reader-visible state. False keeps such plans untouched so a reviewer
            resolves them instead of the tooling choosing for them.

    Returns:
        Reports for the plans that were audited, including collapsed ones.
    """
    result = await audit_reading_plan_duplicate_memberships(db, plan_id=plan_id)
    for report in result.reports:
        plan = create_reconciliation_plan(report)
        if plan.has_conflicts and not allow_conflicts:
            continue
        await apply_reconciliation_plan(db, plan=plan)
    return result