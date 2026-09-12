"""Read-only release gate for retiring raw Dependency Roll blocking."""

from __future__ import annotations

from collections import Counter
from re import Pattern

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.continuity_blocking import get_continuity_blocked_thread_ids
from app.models.continuity_rule import ContinuityRule
from app.models.dependency import Dependency
from app.models.issue import Issue
from app.models.thread import Thread
from app.services.explicit_reader_order_migration import (
    _explicit_classifications,
    _generated_reader_order_patterns,
    _load_step14_index,
)
from comic_pile.dependencies import (
    _get_legacy_blocked_thread_ids_uncached,
    _invalidate_continuity_snapshot,
)


def _classification(
    dependency: Dependency,
    *,
    explicit: dict[int, str],
    generated_patterns: tuple[Pattern[str], ...],
) -> str:
    classified = explicit.get(dependency.id)
    if classified is not None:
        return classified
    note = dependency.note or ""
    if any(pattern.match(note) for pattern in generated_patterns):
        return "reading_plan_order"
    return "unclassified"


async def build_reader_order_cutover_audit(
    db: AsyncSession,
    *,
    user_id: int,
) -> dict[str, object]:
    """Prove whether production may stop consulting raw Dependency rows.

    The audit uses the canonical Step 14 classifications. It separately reports
    reader-order debris, genuine prerequisites, review-only state, and unknown
    rows. The runtime gate passes only when no active reader-order edge remains
    and every raw blocker is already represented by a continuity rule.
    """
    _invalidate_continuity_snapshot(user_id, db)
    index = _load_step14_index()
    explicit, _ = _explicit_classifications(index)
    patterns = _generated_reader_order_patterns(index)

    source_issue = Issue.__table__.alias("source_issue")
    target_issue = Issue.__table__.alias("target_issue")
    source_thread = Thread.__table__.alias("source_thread")
    target_thread = Thread.__table__.alias("target_thread")
    result = await db.execute(
        select(
            Dependency,
            source_issue.c.status,
            target_thread.c.next_unread_issue_id,
        )
        .join(source_issue, source_issue.c.id == Dependency.source_issue_id)
        .join(source_thread, source_thread.c.id == source_issue.c.thread_id)
        .join(target_issue, target_issue.c.id == Dependency.target_issue_id)
        .join(target_thread, target_thread.c.id == target_issue.c.thread_id)
        .where(source_thread.c.user_id == user_id, target_thread.c.user_id == user_id)
        .order_by(Dependency.id)
    )
    rows = list(result.all())
    classifications: dict[int, str] = {}
    totals: Counter[str] = Counter()
    active: Counter[str] = Counter()
    active_ids: dict[str, list[int]] = {}
    for dependency, source_status, next_unread_issue_id in rows:
        kind = _classification(
            dependency,
            explicit=explicit,
            generated_patterns=patterns,
        )
        classifications[dependency.id] = kind
        totals[kind] += 1
        if (
            source_status != "read"
            and dependency.target_issue_id == next_unread_issue_id
        ):
            active[kind] += 1
            active_ids.setdefault(kind, []).append(dependency.id)

    legacy_blocked = await _get_legacy_blocked_thread_ids_uncached(user_id, db)
    continuity_blocked = await get_continuity_blocked_thread_ids(user_id, db)
    legacy_only = sorted(legacy_blocked - continuity_blocked)

    linked_rules = list(
        (
            await db.execute(
                select(ContinuityRule).where(
                    ContinuityRule.user_id == user_id,
                    ContinuityRule.legacy_dependency_id.is_not(None),
                )
            )
        )
        .scalars()
        .all()
    )
    mirrored_ids = {
        rule.legacy_dependency_id
        for rule in linked_rules
        if rule.legacy_dependency_id is not None
    }
    active_standalone_ids = set(active_ids.get("standalone_prerequisite", []))
    missing_standalone_mirrors = sorted(active_standalone_ids - mirrored_ids)
    active_reader_order_ids = sorted(active_ids.get("reading_plan_order", []))
    active_needs_review_ids = sorted(active_ids.get("needs_review", []))
    active_unclassified_ids = sorted(active_ids.get("unclassified", []))

    release_condition_met = not active_reader_order_ids
    runtime_cutover_safe = (
        release_condition_met
        and not active_needs_review_ids
        and not active_unclassified_ids
        and not missing_standalone_mirrors
        and not legacy_only
    )
    return {
        "user_id": user_id,
        "classification_totals": dict(sorted(totals.items())),
        "active_blocking_totals": dict(sorted(active.items())),
        "active_reading_plan_order_dependency_ids": active_reader_order_ids,
        "active_standalone_prerequisite_dependency_ids": sorted(active_standalone_ids),
        "active_needs_review_dependency_ids": active_needs_review_ids,
        "active_unclassified_dependency_ids": active_unclassified_ids,
        "active_standalone_dependencies_missing_continuity_mirror": (
            missing_standalone_mirrors
        ),
        "legacy_blocked_thread_ids": sorted(legacy_blocked),
        "continuity_blocked_thread_ids": sorted(continuity_blocked),
        "legacy_only_blocked_thread_ids": legacy_only,
        "release_condition_met": release_condition_met,
        "runtime_cutover_safe": runtime_cutover_safe,
    }
