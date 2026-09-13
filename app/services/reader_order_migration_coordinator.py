"""Coordinator helpers for the one-shot Step 27 production migration."""

from __future__ import annotations

from typing import Any

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.continuity_plan import ContinuityPlan
from app.models.dependency import Dependency
from app.services.explicit_reader_order_migration import (
    ExplicitReaderOrderSpec,
    _explicit_classifications,
    _load_step14_index,
    _resolve_selected_dependency_ids,
    build_explicit_reader_order_dry_run,
)
from app.services.source_backed_reader_order_migration import (
    SourceBackedReaderOrderSpec,
    build_source_backed_reader_order_dry_run,
)


def migration_report_status(report: dict[str, Any]) -> str:
    """Return the operator-facing classification for one manifest report."""
    if report.get("already_migrated") is True:
        return "already-migrated"
    if report.get("ok") is True:
        return "safe-to-migrate"
    errors = [str(error) for error in report.get("errors", [])]
    if any("needs_review" in error for error in errors):
        return "blocked-by-needs-review"
    if any(
        phrase in error
        for error in errors
        for phrase in (
            "Roll eligibility would change",
            "loses protection",
            "does not exactly reproduce",
        )
    ):
        return "behavior-mismatch"
    return "blocked-by-identity-or-source"


async def _explicit_already_migrated(
    db: AsyncSession,
    spec: ExplicitReaderOrderSpec,
) -> bool:
    index = _load_step14_index()
    _, families = _explicit_classifications(index)
    selected_ids = _resolve_selected_dependency_ids(spec, by_family=families)
    remaining = await db.scalar(
        select(func.count()).select_from(Dependency).where(Dependency.id.in_(selected_ids))
    )
    if remaining != 0:
        return False
    plans = list(
        (
            await db.execute(
                select(ContinuityPlan).where(
                    ContinuityPlan.user_id == spec.user_id,
                    ContinuityPlan.name == spec.plan_name,
                )
            )
        )
        .scalars()
        .all()
    )
    if len(plans) != 1 or not plans[0].nodes_json:
        return False
    return True


def _source_placement_count(plan: ContinuityPlan, source_path: str) -> int:
    count = 0
    for node in plan.nodes_json or []:
        placements = node.get("source_cbl_placements")
        if not isinstance(placements, list):
            continue
        count += sum(
            1
            for placement in placements
            if isinstance(placement, dict)
            and placement.get("source_path") == source_path
        )
    return count


async def _source_already_migrated(
    db: AsyncSession,
    spec: SourceBackedReaderOrderSpec,
    report: dict[str, Any],
) -> bool:
    source = report.get("source")
    if not isinstance(source, dict):
        return False
    source_path = source.get("source_path")
    if not isinstance(source_path, str):
        return False
    plans = list(
        (
            await db.execute(
                select(ContinuityPlan).where(
                    ContinuityPlan.user_id == spec.user_id,
                    ContinuityPlan.name == spec.plan_name,
                    ContinuityPlan.ordering_mode == "strict_sequential",
                )
            )
        )
        .scalars()
        .all()
    )
    return len(plans) == 1 and _source_placement_count(
        plans[0], source_path
    ) == spec.expected_positions


async def build_manifest_report(
    db: AsyncSession,
    *,
    manifest: str,
    source_manifests: dict[str, SourceBackedReaderOrderSpec],
    explicit_manifests: dict[str, ExplicitReaderOrderSpec],
) -> dict[str, Any]:
    """Build and classify one source-backed or explicit-family dry-run."""
    if manifest in source_manifests:
        spec = source_manifests[manifest]
        report = await build_source_backed_reader_order_dry_run(db, spec)
        already_migrated = await _source_already_migrated(db, spec, report)
    else:
        spec = explicit_manifests[manifest]
        report = await build_explicit_reader_order_dry_run(db, spec)
        already_migrated = await _explicit_already_migrated(db, spec)
    if already_migrated:
        report = {**report, "already_migrated": True}
    return {"status": migration_report_status(report), **report}
