"""Audit and reconciliation tooling for Reading Plan canonical issue membership uniqueness.

Provides functions to detect, report, and deterministically reconcile duplicate
canonical issue memberships within a Reading Plan.
"""

from __future__ import annotations

from dataclasses import dataclass

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.reading_plan_membership import ReadingPlanIssue


@dataclass(frozen=True)
class DuplicateIssueMembership:
    """Represents one canonical Issue with multiple membership occurrences in a plan."""

    plan_id: int
    issue_id: int
    occurrence_ids: list[str]
    lane_ids: list[str]
    display_positions: list[int]
    labels: list[str | None]
    reader_roles: list[str | None]
    reader_optionals: list[bool | None]
    is_checkpoints: list[bool]
    source_metadata_list: list[dict[str, object] | None]

    @property
    def count(self) -> int:
        """Number of duplicate occurrences for this issue."""
        return len(self.occurrence_ids)


@dataclass(frozen=True)
class PlanDuplicateReport:
    """Report of all duplicate canonical issue memberships in one plan."""

    plan_id: int
    duplicates: list[DuplicateIssueMembership]

    @property
    def total_duplicate_issues(self) -> int:
        """Number of distinct issues with duplicate memberships."""
        return len(self.duplicates)

    @property
    def total_extra_occurrences(self) -> int:
        """Total extra occurrences beyond the first for each duplicated issue."""
        return sum(d.count - 1 for d in self.duplicates)


async def audit_plan_duplicate_memberships(
    db: AsyncSession, *, plan_id: int
) -> PlanDuplicateReport:
    """Audit one plan for duplicate canonical issue memberships.

    Returns a report of all issues that appear more than once in the plan.
    """
    result = await db.execute(
        select(ReadingPlanIssue)
        .where(ReadingPlanIssue.plan_id == plan_id)
        .order_by(ReadingPlanIssue.issue_id, ReadingPlanIssue.display_position)
    )
    rows = list(result.scalars().all())

    issues_by_id: dict[int, list[ReadingPlanIssue]] = {}
    for row in rows:
        issues_by_id.setdefault(row.issue_id, []).append(row)

    duplicates = [
        DuplicateIssueMembership(
            plan_id=plan_id,
            issue_id=issue_id,
            occurrence_ids=[r.occurrence_id for r in occurrences],
            lane_ids=[r.lane_id for r in occurrences],
            display_positions=[r.display_position for r in occurrences],
            labels=[r.label for r in occurrences],
            reader_roles=[r.reader_role for r in occurrences],
            reader_optionals=[r.reader_optional for r in occurrences],
            is_checkpoints=[r.is_checkpoint for r in occurrences],
            source_metadata_list=[r.source_metadata_json for r in occurrences],
        )
        for issue_id, occurrences in issues_by_id.items()
        if len(occurrences) > 1
    ]

    return PlanDuplicateReport(plan_id=plan_id, duplicates=duplicates)


async def audit_all_plans_duplicate_memberships(
    db: AsyncSession,
) -> list[PlanDuplicateReport]:
    """Audit all plans for duplicate canonical issue memberships.

    Returns a list of reports for plans that have duplicates.
    """
    result = await db.execute(
        select(ReadingPlanIssue.plan_id)
        .distinct()
        .order_by(ReadingPlanIssue.plan_id)
    )
    plan_ids = list(result.scalars().all())

    reports: list[PlanDuplicateReport] = []
    for plan_id in plan_ids:
        report = await audit_plan_duplicate_memberships(db, plan_id=plan_id)
        if report.total_duplicate_issues > 0:
            reports.append(report)

    return reports


@dataclass(frozen=True)
class ReconciliationPlan:
    """Plan for reconciling duplicate issue memberships in one plan.

    For each duplicated issue, the primary occurrence (first by display_position,
    then occurrence_id) is kept. Other occurrences are marked for removal.
    """

    plan_id: int
    primary_occurrence_ids: dict[int, str]  # issue_id -> occurrence_id to keep
    removal_occurrence_ids: list[str]  # occurrence_ids to remove


def create_reconciliation_plan(
    report: PlanDuplicateReport,
) -> ReconciliationPlan:
    """Create a deterministic reconciliation plan from a duplicate report.

    For each duplicated issue, the primary occurrence is the one with the
    lowest display_position, breaking ties by occurrence_id. This preserves
    the earliest position in the plan.
    """
    primary: dict[int, str] = {}
    removal: list[str] = []

    for dup in report.duplicates:
        # Sort occurrences by (display_position, occurrence_id) to pick primary.
        sorted_occurrences = sorted(
            zip(
                dup.display_positions,
                dup.occurrence_ids,
                dup.lane_ids,
                dup.labels,
                dup.reader_roles,
                dup.reader_optionals,
                dup.is_checkpoints,
                dup.source_metadata_list,
                strict=False,
            ),
            key=lambda x: (x[0], x[1]),
        )
        primary_occurrence_id = sorted_occurrences[0][1]
        primary[dup.issue_id] = primary_occurrence_id
        for occ in sorted_occurrences[1:]:
            removal.append(occ[1])

    return ReconciliationPlan(
        plan_id=report.plan_id,
        primary_occurrence_ids=primary,
        removal_occurrence_ids=removal,
    )


async def apply_reconciliation_plan(
    db: AsyncSession, *, plan: ReconciliationPlan
) -> None:
    """Apply a reconciliation plan by removing duplicate occurrences.

    The primary occurrence for each issue is preserved. All other occurrences
    are deleted. Source placements are not modified; they remain associated
    with their original occurrence_ids (which may now be orphaned but preserved
    for provenance).
    """
    if not plan.removal_occurrence_ids:
        return

    from sqlalchemy import delete

    await db.execute(
        delete(ReadingPlanIssue).where(
            ReadingPlanIssue.plan_id == plan.plan_id,
            ReadingPlanIssue.occurrence_id.in_(plan.removal_occurrence_ids),
        )
    )
    await db.flush()


async def reconcile_plan_duplicates(db: AsyncSession, *, plan_id: int) -> PlanDuplicateReport:
    """Audit and reconcile duplicate memberships in one plan in one transaction.

    Returns the report of what was found and reconciled.
    """
    report = await audit_plan_duplicate_memberships(db, plan_id=plan_id)
    if report.total_duplicate_issues > 0:
        reconciliation = create_reconciliation_plan(report)
        await apply_reconciliation_plan(db, plan=reconciliation)
    return report


async def reconcile_all_plans_duplicates(db: AsyncSession) -> list[PlanDuplicateReport]:
    """Audit and reconcile duplicate memberships in all plans.

    Returns reports for all plans that had duplicates.
    """
    reports = await audit_all_plans_duplicate_memberships(db)
    for report in reports:
        reconciliation = create_reconciliation_plan(report)
        await apply_reconciliation_plan(db, plan=reconciliation)
    return reports