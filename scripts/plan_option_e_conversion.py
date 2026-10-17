"""Option E conversion preflight and local rehearsal (dry-run only).

Two modes, neither of which mutates durable state:

* ``preflight`` reads one consistent snapshot inside a PostgreSQL-enforced
  read-only, repeatable-read transaction and prints the conversion manifest:
  exact row identities, counts, proposed list modes and skips, migrated
  prerequisite provenance, derived frontier repairs, a before/after eligibility
  diff and a reversible receipt plan.
* ``rehearse`` applies the manifest inside a local transaction, reloads the
  applied state, re-evaluates eligibility, compares it with the manifest, then
  **always rolls back**. It requires ``--acknowledge-rollback``. There is no
  apply or commit path in this module.

Requires an explicit ``postgresql+asyncpg://`` URL, an owner id, and a reviewed
intent document bound to the source fingerprint by ``--intent``. Nothing here
approves production: execution is a separate manual-only issue.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
from collections.abc import Mapping, Sequence
from pathlib import Path

from fastapi import HTTPException
from sqlalchemy import select, text
from sqlalchemy.engine import make_url
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine

from app.models.collection_exclusion import CollectionExclusion
from app.models.continuity_plan import ContinuityPlan
from app.models.custom_cbl import CustomCBLList, CustomCBLEntry
from app.models.dependency import Dependency
from app.models.reading_plan_membership import ReadingPlanIssue, ReadingPlanSource
from app.models.thread import Thread
from app.repositories import reading_list_authoring_repository as authoring_repository
from app.services.reading_list_authoring import load_authoring_snapshot
from app.services.reading_list_conversion_plan import (
    ConversionEvidence,
    ConversionIntent,
    ConversionManifest,
    DiscrepancyKey,
    ExclusionDecision,
    FrontierRepairDecision,
    ListDecision,
    PrerequisiteDecision,
    ProjectEvidence,
    StoredFrontier,
    StoredExclusion,
    StoredPrerequisiteEvidence,
    build_manifest,
)
from app.services.reading_list_evaluator import ReadingSnapshot, evaluate

MODE_CHOICES = ("preflight", "rehearse")
GATE_VALUES = ("none", "hold", "after_previous")
KIND_VALUES = ("list_only", "plan_only", "order_conflict", "duplicate_placement")
CLASSIFICATION_VALUES = ("A", "B", "C", "D")


def _require_async_url(database_url: str) -> None:
    if not database_url.startswith("postgresql+asyncpg://"):
        raise ValueError("An explicit postgresql+asyncpg:// URL is required")


def _rows(value: object) -> list[Mapping[str, object]]:
    if value is None:
        return []
    if not isinstance(value, list):
        raise ValueError("Expected a JSON array")
    rows: list[Mapping[str, object]] = []
    for item in value:
        if not isinstance(item, dict):
            raise ValueError("Expected a JSON object inside an array")
        rows.append({str(key): entry for key, entry in item.items()})
    return rows


def _sequence(value: object) -> list[object]:
    if value is None:
        return []
    if not isinstance(value, list):
        raise ValueError("Expected a JSON array")
    return list(value)


def _pairs(value: object) -> list[list[object]]:
    pairs: list[list[object]] = []
    for item in _sequence(value):
        if not isinstance(item, (list, tuple)) or len(item) != 2:
            raise ValueError("Expected [issue_id, gate] pairs")
        pairs.append([item[0], item[1]])
    return pairs


def _as_int(value: object, field: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise ValueError(f"{field} must be an integer")
    return value


def _optional_int(value: object) -> int | None:
    if value is None:
        return None
    return _as_int(value, "optional integer")


def _optional_str(value: object) -> str | None:
    if value is None:
        return None
    if not isinstance(value, str):
        raise ValueError("optional string expected")
    return value


def _check_intent_keys(payload: Mapping[str, object]) -> None:
    """Reject unknown decision keys before constructing any reviewed intent."""

    def check(row: Mapping[str, object], allowed: set[str], where: str) -> None:
        if extra := set(row) - allowed:
            raise ValueError(f"Unknown {where} keys: {sorted(extra)}")

    check(
        payload,
        {
            "source_fingerprint",
            "schema_version",
            "lists",
            "prerequisites",
            "exclusions",
            "frontier_repairs",
        },
        "intent",
    )
    allowed_rows = {
        "lists": {"list_id", "mode", "acknowledged_discrepancies", "skipped_issue_ids", "gates"},
        "prerequisites": {"dependency_id", "action", "classification", "provenance"},
        "exclusions": {
            "provider",
            "external_volume_id",
            "thread_id",
            "issue_id",
            "resolved_issue_ids",
        },
        "frontier_repairs": {"thread_id", "derived_issue_id"},
    }
    for section, allowed in allowed_rows.items():
        for row in _rows(payload.get(section)):
            check(row, allowed, section)
            if section == "lists":
                for discrepancy in _rows(row.get("acknowledged_discrepancies")):
                    check(discrepancy, {"issue_id", "kind"}, "acknowledged_discrepancies")


def parse_intent(payload: Mapping[str, object]) -> ConversionIntent:
    """Parse a reviewed intent document without inventing defaults for decisions."""
    _check_intent_keys(payload)
    fingerprint = payload.get("source_fingerprint")
    if not isinstance(fingerprint, str) or not fingerprint:
        raise ValueError("Reviewed intent requires a source_fingerprint")
    lists: list[ListDecision] = []
    for row in _rows(payload.get("lists")):
        mode = row.get("mode")
        if mode not in ("strict", "loose"):
            raise ValueError(f"List {row.get('list_id')} has no reviewed strict/loose mode")
        acknowledgements: list[DiscrepancyKey] = []
        for item in _rows(row.get("acknowledged_discrepancies")):
            kind = item.get("kind")
            if kind not in KIND_VALUES:
                raise ValueError(f"Unknown discrepancy kind {kind!r}")
            acknowledgements.append(
                DiscrepancyKey(_as_int(item.get("issue_id"), "acknowledged[].issue_id"), kind)
            )
        gates: list[tuple[int, str]] = []
        for pair in _pairs(row.get("gates")):
            gate = pair[1]
            if gate not in GATE_VALUES:
                raise ValueError(f"Unknown gate {gate!r}")
            gates.append((_as_int(pair[0], "gates[][0]"), gate))
        lists.append(
            ListDecision(
                list_id=_as_int(row.get("list_id"), "lists[].list_id"),
                mode=mode,
                acknowledged_discrepancies=tuple(acknowledgements),
                skipped_issue_ids=frozenset(
                    _as_int(value, "skipped_issue_ids[]")
                    for value in _sequence(row.get("skipped_issue_ids"))
                ),
                gates=tuple(gates),
            )
        )
    prerequisites: list[PrerequisiteDecision] = []
    for row in _rows(payload.get("prerequisites")):
        action = row.get("action")
        if action not in ("keep_reader", "convert", "preserve_unknown"):
            raise ValueError(
                f"Prerequisite {row.get('dependency_id')} has no reviewed "
                "keep_reader/convert/preserve_unknown action"
            )
        if action == "preserve_unknown" and (
            row.get("classification") is not None or row.get("provenance") is not None
        ):
            raise ValueError(
                "preserve_unknown keeps raw provenance unchanged; "
                "do not provide classification or provenance"
            )
        classification = row.get("classification")
        if classification is not None and classification not in CLASSIFICATION_VALUES:
            raise ValueError(f"Unknown classification {classification!r}")
        prerequisites.append(
            PrerequisiteDecision(
                dependency_id=_as_int(row.get("dependency_id"), "prerequisites[].dependency_id"),
                action=action,
                classification=classification,
                provenance=_optional_str(row.get("provenance")),
            )
        )
    exclusions = tuple(
        ExclusionDecision(
            provider=_optional_str(row.get("provider")),
            external_volume_id=_optional_str(row.get("external_volume_id")),
            thread_id=_optional_int(row.get("thread_id")),
            issue_id=_optional_int(row.get("issue_id")),
            resolved_issue_ids=tuple(
                _as_int(value, "resolved_issue_ids[]")
                for value in _sequence(row.get("resolved_issue_ids"))
            ),
        )
        for row in _rows(payload.get("exclusions"))
    )
    repairs = tuple(
        FrontierRepairDecision(
            thread_id=_as_int(row.get("thread_id"), "frontier_repairs[].thread_id"),
            derived_issue_id=_optional_int(row.get("derived_issue_id")),
        )
        for row in _rows(payload.get("frontier_repairs"))
    )
    return ConversionIntent(
        source_fingerprint=fingerprint,
        lists=tuple(lists),
        prerequisites=tuple(prerequisites),
        exclusions=exclusions,
        frontier_repairs=repairs,
        schema_version=_as_int(payload.get("schema_version", 1), "schema_version"),
    )


async def load_project_evidence(
    db: AsyncSession, user_id: int, snapshot: ReadingSnapshot
) -> tuple[ProjectEvidence, ...]:
    """Load paired plan membership evidence without guessing a source.

    Pairing requires the durable ``reading_plan_sources.custom_cbl_list_id`` link.
    A list with no such link reports ``durable_source_link=False`` so plan
    membership can never be adopted by name or timestamp.
    """
    entry_ids: dict[int, list[tuple[int, int]]] = {}
    for row in await authoring_repository.load_entries(db, user_id):
        entry_ids.setdefault(row.list_id, []).append((row.issue_id, row.id))
    sources = list(
        (
            await db.scalars(
                select(ReadingPlanSource)
                .join(ContinuityPlan, ContinuityPlan.id == ReadingPlanSource.plan_id)
                .where(ContinuityPlan.user_id == user_id)
            )
        ).all()
    )
    lists_by_plan: dict[int, set[int]] = {}
    for source in sources:
        if source.custom_cbl_list_id is not None:
            lists_by_plan.setdefault(source.plan_id, set()).add(source.custom_cbl_list_id)
    results: list[ProjectEvidence] = []
    for reading_list in sorted(snapshot.lists, key=lambda row: row.list_id):
        plan_ids = {
            plan_id
            for plan_id, list_ids in lists_by_plan.items()
            if reading_list.list_id in list_ids
        }
        memberships: list[ReadingPlanIssue] = []
        if plan_ids:
            statement = select(ReadingPlanIssue).where(
                ReadingPlanIssue.plan_id.in_(sorted(plan_ids))
            )
            memberships = list((await db.scalars(statement)).all())
        memberships.sort(key=lambda row: (row.display_position, row.occurrence_id))
        foreign = sorted(
            {value for plan_id in plan_ids for value in lists_by_plan[plan_id]}
            - {reading_list.list_id}
        )
        results.append(
            ProjectEvidence(
                list_id=reading_list.list_id,
                plan_membership_issue_ids=tuple(row.issue_id for row in memberships),
                durable_source_link=bool(plan_ids),
                plan_lane_count=max(
                    len(plan_ids), len({(row.plan_id, row.lane_id) for row in memberships}), 1
                ),
                foreign_source_list_ids=tuple(foreign),
                entry_row_ids=tuple(sorted(entry_ids.get(reading_list.list_id, []))),
            )
        )
    return tuple(results)


async def _load_evidence(
    db: AsyncSession, user_id: int, snapshot: ReadingSnapshot
) -> ConversionEvidence:
    thread_rows = list((await db.scalars(select(Thread).where(Thread.user_id == user_id))).all())
    dependency_rows = await authoring_repository.load_requirements(db, user_id)
    exclusions = list(
        (
            await db.scalars(
                select(CollectionExclusion).where(CollectionExclusion.user_id == user_id)
            )
        ).all()
    )
    plan_ids = set(
        (await db.scalars(select(ContinuityPlan.id).where(ContinuityPlan.user_id == user_id))).all()
    )
    paired_ids = set(
        (
            await db.scalars(
                select(ReadingPlanSource.plan_id)
                .join(CustomCBLList, CustomCBLList.id == ReadingPlanSource.custom_cbl_list_id)
                .where(CustomCBLList.user_id == user_id)
            )
        ).all()
    )
    return ConversionEvidence(
        unpaired_plan_ids=tuple(sorted(plan_ids - paired_ids)),
        stored_exclusions=tuple(
            StoredExclusion(
                row.id, row.provider, row.external_volume_id, row.thread_id, row.issue_id
            )
            for row in sorted(exclusions, key=lambda row: row.id)
        ),
        projects=await load_project_evidence(db, user_id, snapshot),
        stored_frontiers=tuple(
            StoredFrontier(row.id, row.next_unread_issue_id, row.issues_remaining, row.total_issues)
            for row in sorted(thread_rows, key=lambda value: value.id)
        ),
        stored_prerequisites=tuple(
            StoredPrerequisiteEvidence(
                row.id, row.origin, row.classification, row.provenance, row.note
            )
            for row in sorted(dependency_rows, key=lambda value: value.id)
        ),
    )


async def _load_applied(db: AsyncSession, user_id: int) -> ReadingSnapshot | None:
    try:
        snapshot, _ = await load_authoring_snapshot(db, user_id)
    except HTTPException, ValueError:
        return None
    return snapshot


async def _manifest_for(
    db: AsyncSession, user_id: int, intent: ConversionIntent
) -> tuple[ConversionManifest, ConversionEvidence]:
    snapshot = await _load_applied(db, user_id)
    if snapshot is None:
        raise ValueError("Current reader constraints are already invalid; refusing to plan")
    evidence = await _load_evidence(db, user_id, snapshot)
    issues = await authoring_repository.load_issues(db, user_id)
    for decision in intent.exclusions:
        if decision.external_volume_id is not None:
            resolved = await authoring_repository.load_excluded_issue_ids(
                db,
                user_id,
                issues,
                proposed_exclusions=[
                    CollectionExclusion(
                        user_id=user_id,
                        provider=decision.provider,
                        external_volume_id=decision.external_volume_id,
                    )
                ],
            )
            if resolved != frozenset(decision.resolved_issue_ids):
                raise ValueError("Reviewed external-volume exclusion resolution is stale")
    return build_manifest(snapshot, evidence, intent), evidence


async def _apply_manifest(
    db: AsyncSession,
    snapshot: ReadingSnapshot,
    evidence: ConversionEvidence,
    manifest: ConversionManifest,
) -> None:
    """Stage every manifest proposal on the session; the caller always rolls back."""
    entry_ids = {row.list_id: dict(row.entry_row_ids) for row in evidence.projects}
    lists_by_id = {row.list_id: row for row in snapshot.lists}
    for proposal in manifest.lists:
        if not proposal.changed:
            continue
        reading_list = lists_by_id[proposal.list_id]
        orm_list = await db.get(CustomCBLList, proposal.list_id)
        if orm_list is not None:
            orm_list.mode = proposal.mode
        gates = dict(proposal.gates)
        for entry in reading_list.entries:
            entry_id = entry_ids.get(proposal.list_id, {}).get(entry.issue_id)
            if entry_id is None:
                continue
            orm_entry = await db.get(CustomCBLEntry, entry_id)
            if orm_entry is None:
                continue
            orm_entry.gate = gates.get(entry.issue_id, entry.gate)
            orm_entry.skipped = entry.skipped or entry.issue_id in proposal.skipped_issue_ids
    for proposal in manifest.prerequisites:
        if not proposal.changed:
            continue
        row = await db.get(Dependency, proposal.dependency_id)
        if row is None:
            continue
        row.origin = proposal.origin
        row.classification = proposal.classification
        row.provenance = proposal.provenance[0] if proposal.provenance else None
    for proposal in manifest.exclusions:
        if proposal.already_present:
            continue
        db.add(
            CollectionExclusion(
                user_id=snapshot.user_id,
                provider=proposal.provider,
                external_volume_id=proposal.external_volume_id,
                thread_id=proposal.thread_id,
                issue_id=proposal.issue_id,
            )
        )
    for proposal in manifest.frontier_repairs:
        if not proposal.changed:
            continue
        thread = await db.get(Thread, proposal.thread_id)
        if thread is not None:
            thread.next_unread_issue_id = proposal.derived_issue_id


async def run(
    db: AsyncSession,
    user_id: int,
    intent: ConversionIntent,
    *,
    mode: str,
    acknowledge_rollback: bool,
) -> dict[str, object]:
    """Run one dry-run mode against an open session.

    Args:
        db: Session whose transaction the caller controls.
        user_id: Reader whose constraints are planned.
        intent: Reviewed intent bound to the source fingerprint.
        mode: ``preflight`` (read-only) or ``rehearse`` (always rolled back).
        acknowledge_rollback: Required for ``rehearse``.

    Returns:
        JSON-compatible manifest, plus a rehearsal comparison when rehearsing.
    """
    if mode not in MODE_CHOICES:
        raise ValueError("Unknown dry-run mode")
    if mode == "rehearse" and not acknowledge_rollback:
        raise ValueError("rehearse requires --acknowledge-rollback")
    manifest, evidence = await _manifest_for(db, user_id, intent)
    payload = manifest.to_json()
    payload["mode"] = mode
    if mode == "preflight":
        return payload
    if not acknowledge_rollback:
        raise ValueError("rehearse requires --acknowledge-rollback (it always rolls back)")
    payload["committed"] = False
    if not manifest.valid:
        payload["rehearsal"] = {
            "applied": False,
            "reason": "manifest_invalid",
            "refusals": [row.code for row in manifest.refusals],
        }
        return payload
    snapshot = await _load_applied(db, user_id)
    if snapshot is None:
        payload["rehearsal"] = {"applied": False, "reason": "current_state_invalid"}
        return payload
    try:
        await _apply_manifest(db, snapshot, evidence, manifest)
        await db.flush()
        db.expire_all()
        applied = await _load_applied(db, user_id)
        if applied is None:
            payload["rehearsal"] = {"applied": False, "reason": "applied_state_invalid"}
        else:
            observed = {
                str(thread_id): {"next_issue_id": row.next_issue_id, "eligible": row.eligible}
                for thread_id, row in sorted(evaluate(applied).items())
            }
            expected = (
                {
                    str(thread_id): {"next_issue_id": value[0], "eligible": value[1]}
                    for thread_id, value in sorted(manifest.eligibility_after.items())
                }
                if manifest.eligibility_after is not None
                else None
            )
            payload["rehearsal"] = {
                "applied": True,
                "matches_manifest": observed == expected,
                "observed_after": observed,
            }
    finally:
        await db.rollback()
    return payload


async def _run_cli(args: argparse.Namespace) -> dict[str, object]:
    _require_async_url(args.database_url)
    if args.mode == "rehearse" and not args.acknowledge_rollback:
        raise ValueError("rehearse requires --acknowledge-rollback (it always rolls back)")
    intent = parse_intent(json.loads(Path(args.intent).read_text(encoding="utf-8")))
    if args.mode == "rehearse" and make_url(args.database_url).host not in (
        "localhost",
        "127.0.0.1",
        "::1",
    ):
        raise ValueError("Rehearsal requires a local PostgreSQL database")
    isolation = "REPEATABLE READ"
    engine = create_async_engine(args.database_url, isolation_level=isolation)
    try:
        async with AsyncSession(engine, autoflush=False) as db:
            if args.mode == "preflight":
                async with db.begin():
                    await db.execute(text("SET TRANSACTION READ ONLY"))
                    result = await run(
                        db,
                        args.user_id,
                        intent,
                        mode=args.mode,
                        acknowledge_rollback=args.acknowledge_rollback,
                    )
            else:
                try:
                    await db.execute(text("SET LOCAL lock_timeout = '5s'"))
                    result = await run(
                        db,
                        args.user_id,
                        intent,
                        mode=args.mode,
                        acknowledge_rollback=args.acknowledge_rollback,
                    )
                finally:
                    await db.rollback()
    finally:
        await engine.dispose()
    if args.receipt_out:
        Path(args.receipt_out).write_text(
            json.dumps(result.get("receipts", []), indent=2, sort_keys=True), encoding="utf-8"
        )
    return result


def main(argv: Sequence[str] | None = None) -> int:
    """Run a dry-run preflight or rehearsal; never mutate durable state."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--database-url", required=True)
    parser.add_argument("--user-id", required=True, type=int)
    parser.add_argument("--intent", required=True, help="Reviewed intent JSON bound by fingerprint")
    parser.add_argument("--mode", choices=MODE_CHOICES, default="preflight")
    parser.add_argument("--receipt-out", default=None)
    parser.add_argument(
        "--acknowledge-rollback",
        action="store_true",
        help="Required for rehearse; the transaction is always rolled back",
    )
    args = parser.parse_args(argv)
    try:
        result = asyncio.run(_run_cli(args))
    except ValueError as error:
        print(json.dumps({"error": str(error)}, indent=2), file=sys.stderr)
        return 2
    print(json.dumps(result, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
