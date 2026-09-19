"""Read-only release gate for retiring raw Dependency Roll blocking."""

from __future__ import annotations

from collections import Counter
from re import Pattern

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.continuity_blocking import (
    get_continuity_rule_blocked_thread_ids,
    get_sequence_order_blocked_thread_ids,
)
from app.models.continuity_rule import ContinuityRule
from app.models.dependency import Dependency
from app.models.issue import Issue
from app.models.thread import Thread
from app.services.explicit_reader_order_migration import (
    _explicit_classifications,
    _generated_reader_order_patterns,
    _load_step14_index,
)
from comic_pile.dependencies import _invalidate_continuity_snapshot


async def _legacy_blocked_thread_ids_for_audit(user_id: int, db: AsyncSession) -> set[int]:
    """Read raw-Dependency blocked thread IDs for the cutover audit comparison.

    The Roll runtime no longer consults raw Dependency rows; this query exists
    only so the read-only release gate can prove ContinuityRule coverage
    against the retired legacy behavior.
    """
    source_issue = Issue.__table__.alias("source_issue")
    next_unread_issue = Issue.__table__.alias("next_unread_issue")
    target_thread = Thread.__table__.alias("target_thread")
    source = Thread.__table__.alias("source_thread")

    issue_result = await db.execute(
        select(target_thread.c.id)
        .join(
            next_unread_issue,
            next_unread_issue.c.id == target_thread.c.next_unread_issue_id,
        )
        .join(Dependency, Dependency.target_issue_id == next_unread_issue.c.id)
        .join(source_issue, Dependency.source_issue_id == source_issue.c.id)
        .join(source, source_issue.c.thread_id == source.c.id)
        .where(target_thread.c.user_id == user_id)
        .where(source.c.user_id == user_id)
        .where(source_issue.c.status != "read")
        .where(target_thread.c.next_unread_issue_id.isnot(None))
        .distinct()
    )
    return {row[0] for row in issue_result.all()}


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


def _standalone_mirror_matches(dependency: Dependency, rule: ContinuityRule) -> bool:
    """Return True when a ContinuityRule exactly mirrors one Dependency edge."""
    return (
        rule.legacy_dependency_id == dependency.id
        and rule.source_type == "issue"
        and rule.source_id == dependency.source_issue_id
        and rule.target_type == "issue"
        and rule.target_id == dependency.target_issue_id
        and rule.satisfaction_type == "item_read"
    )


async def build_reader_order_cutover_audit(
    db: AsyncSession,
    *,
    user_id: int,
) -> dict[str, object]:
    """Prove whether production may stop consulting raw Dependency rows.

    The audit uses the canonical Step 14 classifications. Cutover is semantic:
    every remaining ``reading_plan_order`` row blocks release (including dormant
    edges that would reactivate if a reader marked an earlier issue unread),
    every ``needs_review`` / unclassified row is a hard stop, and every
    surviving standalone prerequisite must have a continuity-rule mirror with
    identical source/target/`item_read` semantics regardless of current read
    state. Continuity coverage is measured from compiled ``ContinuityRule`` rows
    only — active ``DependencyGroupMembership.sequence_order`` blockers fail the
    gate rather than counting as canonical coverage. Point-in-time Roll equality
    is reported as an additional check, not as the definition of equivalence.
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
    remaining_ids: dict[str, list[int]] = {}
    dependencies_by_id: dict[int, Dependency] = {}
    for dependency, source_status, next_unread_issue_id in rows:
        dependencies_by_id[dependency.id] = dependency
        kind = _classification(
            dependency,
            explicit=explicit,
            generated_patterns=patterns,
        )
        classifications[dependency.id] = kind
        totals[kind] += 1
        remaining_ids.setdefault(kind, []).append(dependency.id)
        if (
            source_status != "read"
            and dependency.target_issue_id == next_unread_issue_id
        ):
            active[kind] += 1
            active_ids.setdefault(kind, []).append(dependency.id)

    legacy_blocked = await _legacy_blocked_thread_ids_for_audit(user_id, db)
    # Cutover must prove ContinuityRule coverage only. sequence_order is not a
    # Roll authority under the frozen architecture, so it cannot clear legacy_only.
    continuity_rule_blocked = await get_continuity_rule_blocked_thread_ids(user_id, db)
    sequence_order_blocked = await get_sequence_order_blocked_thread_ids(user_id, db)
    legacy_only = sorted(legacy_blocked - continuity_rule_blocked)

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
    rules_by_legacy_id: dict[int, list[ContinuityRule]] = {}
    for rule in linked_rules:
        legacy_id = rule.legacy_dependency_id
        if legacy_id is None:
            continue
        rules_by_legacy_id.setdefault(legacy_id, []).append(rule)

    remaining_standalone_ids = set(remaining_ids.get("standalone_prerequisite", []))
    missing_standalone_mirrors: list[int] = []
    mismatched_standalone_mirrors: list[int] = []
    for dependency_id in sorted(remaining_standalone_ids):
        dependency = dependencies_by_id[dependency_id]
        linked = rules_by_legacy_id.get(dependency_id, [])
        if not linked:
            missing_standalone_mirrors.append(dependency_id)
            continue
        if not any(_standalone_mirror_matches(dependency, rule) for rule in linked):
            mismatched_standalone_mirrors.append(dependency_id)
    incomplete_standalone_mirrors = sorted(
        set(missing_standalone_mirrors) | set(mismatched_standalone_mirrors)
    )
    remaining_reader_order_ids = sorted(remaining_ids.get("reading_plan_order", []))
    remaining_needs_review_ids = sorted(remaining_ids.get("needs_review", []))
    remaining_unclassified_ids = sorted(remaining_ids.get("unclassified", []))
    active_standalone_ids = set(active_ids.get("standalone_prerequisite", []))
    active_reader_order_ids = sorted(active_ids.get("reading_plan_order", []))
    active_needs_review_ids = sorted(active_ids.get("needs_review", []))
    active_unclassified_ids = sorted(active_ids.get("unclassified", []))
    sequence_order_blocked_ids = sorted(sequence_order_blocked)

    # Semantic release: dormant reader-order debt still blocks cutover.
    release_condition_met = not remaining_reader_order_ids
    runtime_cutover_safe = (
        release_condition_met
        and not remaining_needs_review_ids
        and not remaining_unclassified_ids
        and not incomplete_standalone_mirrors
        and not legacy_only
        and not sequence_order_blocked_ids
    )
    return {
        "user_id": user_id,
        "classification_totals": dict(sorted(totals.items())),
        "active_blocking_totals": dict(sorted(active.items())),
        "remaining_reading_plan_order_dependency_ids": remaining_reader_order_ids,
        "remaining_standalone_prerequisite_dependency_ids": sorted(
            remaining_standalone_ids
        ),
        "remaining_needs_review_dependency_ids": remaining_needs_review_ids,
        "remaining_unclassified_dependency_ids": remaining_unclassified_ids,
        "active_reading_plan_order_dependency_ids": active_reader_order_ids,
        "active_standalone_prerequisite_dependency_ids": sorted(active_standalone_ids),
        "active_needs_review_dependency_ids": active_needs_review_ids,
        "active_unclassified_dependency_ids": active_unclassified_ids,
        "standalone_dependencies_missing_continuity_mirror": missing_standalone_mirrors,
        "standalone_dependencies_with_mismatched_continuity_mirror": (
            mismatched_standalone_mirrors
        ),
        # Compatibility alias used by older receipts/tests: any incomplete mirror.
        "active_standalone_dependencies_missing_continuity_mirror": (
            incomplete_standalone_mirrors
        ),
        "legacy_blocked_thread_ids": sorted(legacy_blocked),
        "continuity_rule_blocked_thread_ids": sorted(continuity_rule_blocked),
        # Compatibility alias: previously mixed rules + sequence_order.
        "continuity_blocked_thread_ids": sorted(continuity_rule_blocked),
        "sequence_order_blocked_thread_ids": sequence_order_blocked_ids,
        "legacy_only_blocked_thread_ids": legacy_only,
        "release_condition_met": release_condition_met,
        "runtime_cutover_safe": runtime_cutover_safe,
    }
