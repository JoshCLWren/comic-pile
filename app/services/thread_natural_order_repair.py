"""Reviewed repair for threads whose issue positions drifted from natural order.

CBL adoption historically appended missing ordinary numbers. Roll reads
``Issue.position`` plus explicitly recorded checkpoints, so an appended
``#1`` after ``#7–#24`` makes next-unread skip the early unread issues.

This pass reseats ordinary numeric issues onto the existing
``Issue.position`` column. It does not create a second ordering system,
does not infer dependencies, and does not mutate read history. Threads
that contain any irregular number are left untouched.

The operator CLI defaults to a read-only preflight. Apply and rollback are
transactional and require an explicit confirmation token. This module is
committed for review; it is not run against production from the
implementation change.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Literal

from sqlalchemy.ext.asyncio import AsyncSession

from app.models import Issue, Thread
from app.repositories import issue_repository, thread_repository
from app.services.issue_tracking import apply_thread_issue_tracking_state
from app.utils.issue_natural_order import natural_issue_order

CONFIRMATION_TOKEN = "NATURAL-ISSUE-ORDER-REPAIR"
"""Required --confirm value for apply and rollback. Preflight does not need it."""

RepairMode = Literal["preflight", "apply", "rollback"]


class NaturalOrderRepairError(Exception):
    """Raised when a repair snapshot or confirmation is invalid."""


@dataclass(frozen=True)
class IssuePositionSnapshot:
    """Before/after position for one issue on a repaired thread."""

    issue_id: int
    issue_number: str
    position_before: int
    position_after: int


@dataclass(frozen=True)
class ThreadNaturalOrderRepair:
    """Planned or applied natural-order reseat for one thread."""

    thread_id: int
    title: str
    next_unread_issue_id_before: int | None
    next_unread_issue_id_after: int | None
    issues: tuple[IssuePositionSnapshot, ...]


@dataclass(frozen=True)
class NaturalOrderRepairReport:
    """Outcome of one natural-order repair preflight, apply, or rollback."""

    mode: RepairMode
    scanned: int
    skipped_irregular: int
    skipped_already_natural: int
    repaired: int
    committed: bool
    repairs: tuple[ThreadNaturalOrderRepair, ...]

    def to_snapshot(self) -> dict[str, object]:
        """Serialize the report for a durable apply/rollback snapshot.

        Returns:
            JSON-safe snapshot dict.
        """
        return {
            "version": 1,
            "mode": self.mode,
            "scanned": self.scanned,
            "skipped_irregular": self.skipped_irregular,
            "skipped_already_natural": self.skipped_already_natural,
            "repaired": self.repaired,
            "committed": self.committed,
            "repairs": [asdict(repair) for repair in self.repairs],
        }


def _plan_repair(
    thread: Thread,
    issues: list[Issue],
) -> ThreadNaturalOrderRepair | None:
    """Return a reseat plan when every issue number is ordinary and unsorted.

    Args:
        thread: Thread being inspected.
        issues: That thread's issues in current position order.

    Returns:
        The planned repair, or ``None`` when the thread is already natural or
        contains an irregular number.
    """
    current_numbers = [issue.issue_number for issue in issues]
    natural_order = natural_issue_order(current_numbers, [])
    if natural_order is None or natural_order == current_numbers:
        return None

    target_positions = {
        issue_number: position
        for position, issue_number in enumerate(natural_order, start=1)
    }
    snapshots = tuple(
        IssuePositionSnapshot(
            issue_id=issue.id,
            issue_number=issue.issue_number,
            position_before=issue.position,
            position_after=target_positions[issue.issue_number],
        )
        for issue in issues
    )
    reseated = sorted(issues, key=lambda issue: target_positions[issue.issue_number])
    next_unread = next(
        (issue.id for issue in reseated if issue.status == "unread"),
        None,
    )
    return ThreadNaturalOrderRepair(
        thread_id=thread.id,
        title=thread.title,
        next_unread_issue_id_before=thread.next_unread_issue_id,
        next_unread_issue_id_after=next_unread,
        issues=snapshots,
    )


def _thread_is_irregular(issues: list[Issue]) -> bool:
    """Return True when any issue number has no ordinary natural position."""
    return natural_issue_order([issue.issue_number for issue in issues], []) is None


async def _apply_repair_plan(
    db: AsyncSession,
    thread: Thread,
    issues: list[Issue],
    plan: ThreadNaturalOrderRepair,
    *,
    use_after_positions: bool,
) -> None:
    """Write planned positions and refresh derived next-unread state.

    Args:
        db: Database session.
        thread: Locked thread being repaired.
        issues: Locked issues for the thread.
        plan: Planned before/after positions.
        use_after_positions: True applies the natural order; False restores
            the snapshot's ``position_before`` values.
    """
    positions_by_id = {
        snapshot.issue_id: (
            snapshot.position_after if use_after_positions else snapshot.position_before
        )
        for snapshot in plan.issues
    }
    if any(issue.position != positions_by_id[issue.id] for issue in issues):
        await issue_repository.defer_position_unique_constraint(db)
        for issue in issues:
            issue.position = positions_by_id[issue.id]
    ordered = sorted(issues, key=lambda issue: issue.position)
    apply_thread_issue_tracking_state(thread, ordered)


async def repair_thread_natural_issue_order(
    db: AsyncSession,
    *,
    user_id: int | None = None,
    thread_id: int | None = None,
    limit: int | None = None,
    commit: bool = False,
) -> NaturalOrderRepairReport:
    """Inspect or reseat ordinary numeric threads that are out of natural order.

    Args:
        db: Async database session. The caller owns the connection; this
            function commits only when ``commit`` is True and otherwise rolls
            the transaction back so preflight stays read-only.
        user_id: Optional owner filter.
        thread_id: Optional single-thread filter.
        limit: Optional maximum number of threads to inspect.
        commit: When True, persist the reseats; otherwise roll them back.

    Returns:
        Report describing scanned threads and planned or applied repairs.
    """
    threads = await thread_repository.fetch_threads_for_natural_order_scan(
        db, user_id=user_id, thread_id=thread_id, limit=limit
    )
    issues_by_thread = await issue_repository.issues_for_threads(
        db, {thread.id for thread in threads}
    )

    skipped_irregular = 0
    skipped_already_natural = 0
    repairs: list[ThreadNaturalOrderRepair] = []

    for thread in threads:
        issues = issues_by_thread.get(thread.id, [])
        if not issues:
            continue
        if _thread_is_irregular(issues):
            skipped_irregular += 1
            continue
        plan = _plan_repair(thread, issues)
        if plan is None:
            skipped_already_natural += 1
            continue
        if commit:
            locked_thread = await thread_repository.lock_thread(db, thread.id)
            if locked_thread is None:
                continue
            locked_issues = await issue_repository.locked_issues(db, thread.id)
            locked_plan = _plan_repair(locked_thread, locked_issues)
            if locked_plan is None:
                if _thread_is_irregular(locked_issues):
                    skipped_irregular += 1
                else:
                    skipped_already_natural += 1
                continue
            await _apply_repair_plan(
                db,
                locked_thread,
                locked_issues,
                locked_plan,
                use_after_positions=True,
            )
            repairs.append(
                ThreadNaturalOrderRepair(
                    thread_id=locked_plan.thread_id,
                    title=locked_plan.title,
                    next_unread_issue_id_before=locked_plan.next_unread_issue_id_before,
                    next_unread_issue_id_after=locked_thread.next_unread_issue_id,
                    issues=locked_plan.issues,
                )
            )
        else:
            repairs.append(plan)

    mode: RepairMode = "apply" if commit else "preflight"
    if commit:
        await db.commit()
    else:
        await db.rollback()

    return NaturalOrderRepairReport(
        mode=mode,
        scanned=len(threads),
        skipped_irregular=skipped_irregular,
        skipped_already_natural=skipped_already_natural,
        repaired=len(repairs),
        committed=commit,
        repairs=tuple(repairs),
    )


def _repair_from_snapshot(raw: object) -> ThreadNaturalOrderRepair:
    """Parse one thread repair from a durable snapshot.

    Args:
        raw: One repair object from a snapshot file.

    Returns:
        The typed repair.

    Raises:
        NaturalOrderRepairError: The snapshot entry is malformed.
    """
    if not isinstance(raw, dict):
        raise NaturalOrderRepairError("snapshot repair must be an object")
    issues_raw = raw.get("issues")
    if not isinstance(issues_raw, list):
        raise NaturalOrderRepairError("snapshot repair issues must be a list")
    issues: list[IssuePositionSnapshot] = []
    for issue_raw in issues_raw:
        if not isinstance(issue_raw, dict):
            raise NaturalOrderRepairError("snapshot issue must be an object")
        try:
            issues.append(
                IssuePositionSnapshot(
                    issue_id=int(issue_raw["issue_id"]),
                    issue_number=str(issue_raw["issue_number"]),
                    position_before=int(issue_raw["position_before"]),
                    position_after=int(issue_raw["position_after"]),
                )
            )
        except (KeyError, TypeError, ValueError) as exc:
            raise NaturalOrderRepairError("snapshot issue positions are invalid") from exc
    try:
        next_before = raw.get("next_unread_issue_id_before")
        next_after = raw.get("next_unread_issue_id_after")
        return ThreadNaturalOrderRepair(
            thread_id=int(raw["thread_id"]),
            title=str(raw.get("title") or ""),
            next_unread_issue_id_before=(
                int(next_before) if next_before is not None else None
            ),
            next_unread_issue_id_after=int(next_after) if next_after is not None else None,
            issues=tuple(issues),
        )
    except (KeyError, TypeError, ValueError) as exc:
        raise NaturalOrderRepairError("snapshot repair thread fields are invalid") from exc


def parse_repair_snapshot(snapshot: dict[str, object]) -> tuple[ThreadNaturalOrderRepair, ...]:
    """Validate and load thread repairs from a durable snapshot.

    Args:
        snapshot: JSON object written by :meth:`NaturalOrderRepairReport.to_snapshot`.

    Returns:
        The typed thread repairs.

    Raises:
        NaturalOrderRepairError: The snapshot version or payload is invalid.
    """
    if snapshot.get("version") != 1:
        raise NaturalOrderRepairError("unsupported natural-order repair snapshot version")
    repairs_raw = snapshot.get("repairs")
    if not isinstance(repairs_raw, list):
        raise NaturalOrderRepairError("snapshot repairs must be a list")
    return tuple(_repair_from_snapshot(item) for item in repairs_raw)


async def rollback_thread_natural_issue_order(
    db: AsyncSession,
    snapshot: dict[str, object],
    *,
    commit: bool = False,
) -> NaturalOrderRepairReport:
    """Restore positions recorded in an apply snapshot.

    Args:
        db: Async database session.
        snapshot: Durable snapshot from a previous apply.
        commit: When True, persist the restored positions; otherwise roll back.

    Returns:
        Report describing the restored threads.

    Raises:
        NaturalOrderRepairError: The snapshot is malformed.
    """
    plans = parse_repair_snapshot(snapshot)
    restored: list[ThreadNaturalOrderRepair] = []
    for plan in plans:
        thread = await thread_repository.lock_thread(db, plan.thread_id)
        if thread is None:
            continue
        issues = await issue_repository.locked_issues(db, plan.thread_id)
        planned_ids = {item.issue_id for item in plan.issues}
        current_ids = {issue.id for issue in issues}
        if planned_ids != current_ids:
            raise NaturalOrderRepairError(
                f"thread {plan.thread_id} issue set no longer matches the snapshot"
            )
        await _apply_repair_plan(
            db,
            thread,
            issues,
            plan,
            use_after_positions=False,
        )
        restored.append(
            ThreadNaturalOrderRepair(
                thread_id=plan.thread_id,
                title=thread.title,
                next_unread_issue_id_before=plan.next_unread_issue_id_after,
                next_unread_issue_id_after=thread.next_unread_issue_id,
                issues=plan.issues,
            )
        )

    if commit:
        await db.commit()
    else:
        await db.rollback()

    return NaturalOrderRepairReport(
        mode="rollback",
        scanned=len(plans),
        skipped_irregular=0,
        skipped_already_natural=0,
        repaired=len(restored),
        committed=commit,
        repairs=tuple(restored),
    )
