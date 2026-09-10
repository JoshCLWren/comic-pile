#!/usr/bin/env python3
"""Step 14A read-only audit for exact cbl-order:source:* dependencies.

Produces an exact dependency-ID manifest plus family evidence. This script never
commits and contains no mutation statements.
"""

from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
from pathlib import Path
import re
import sys
from typing import Any

from sqlalchemy import text

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app.database import AsyncSessionLocal  # noqa: E402

NOTE_RE = re.compile(r"^cbl-order:source:([^:]+):(\d+)->(\d+)$")
WOLVERINE_HASH = "1e6b55e99d9317ba68782678710a3e621786c9f57afb1203f44154714acef9b8"


async def build_report(user_id: int = 1) -> dict[str, Any]:
    async with AsyncSessionLocal() as db:
        rows = (
            await db.execute(
                text(
                    """
                    SELECT d.id, d.created_at, d.source_issue_id, d.target_issue_id, d.note
                    FROM dependencies d
                    JOIN issues si ON si.id = d.source_issue_id
                    JOIN threads st ON st.id = si.thread_id
                    JOIN issues ti ON ti.id = d.target_issue_id
                    JOIN threads tt ON tt.id = ti.thread_id
                    WHERE st.user_id = :user_id
                      AND tt.user_id = :user_id
                      AND d.note ~ '^cbl-order:source:[^:]+:[0-9]+->[0-9]+$'
                    ORDER BY d.id
                    """
                ),
                {"user_id": user_id},
            )
        ).mappings().all()

        lists = (
            await db.execute(
                text(
                    """
                    SELECT l.id, l.name, l.content_hash, l.active,
                           e.position, e.series_name, e.issue_number, e.volume_year,
                           e.external_issue_identity_id
                    FROM cbl_source_lists l
                    JOIN cbl_source_entries e ON e.list_id = l.id
                    WHERE l.active IS TRUE
                    ORDER BY l.content_hash, e.position
                    """
                )
            )
        ).mappings().all()

        confirmed = (
            await db.execute(
                text(
                    """
                    SELECT issue_id, external_identity_id
                    FROM issue_external_identity_mappings
                    WHERE status = 'confirmed'
                    """
                )
            )
        ).all()

        issue_rows = (
            await db.execute(
                text(
                    """
                    SELECT i.id, i.issue_number, t.title, t.user_id
                    FROM issues i
                    JOIN threads t ON t.id = i.thread_id
                    WHERE t.user_id = :user_id
                    """
                ),
                {"user_id": user_id},
            )
        ).mappings().all()
        await db.rollback()

    active_lists: dict[str, dict[str, Any]] = {}
    entries: dict[tuple[str, int], dict[str, Any]] = {}
    for row in lists:
        content_hash = row["content_hash"]
        existing = active_lists.setdefault(
            content_hash,
            {"id": row["id"], "name": row["name"], "active": row["active"]},
        )
        if existing["id"] != row["id"]:
            raise RuntimeError(f"multiple active lists share content hash {content_hash}")
        entries[(content_hash, row["position"])] = dict(row)

    confirmed_pairs = {(int(issue_id), int(external_id)) for issue_id, external_id in confirmed}
    issues = {int(row["id"]): dict(row) for row in issue_rows}

    families: dict[str, dict[str, Any]] = {}
    all_ids: list[int] = []
    for row in rows:
        match = NOTE_RE.fullmatch(row["note"])
        if match is None:
            raise RuntimeError(f"unexpected note for dependency {row['id']}: {row['note']!r}")
        content_hash, source_text, target_text = match.groups()
        source_pos, target_pos = int(source_text), int(target_text)
        family = families.setdefault(
            content_hash,
            {
                "content_hash": content_hash,
                "dependency_ids": [],
                "nonforward_dependency_ids": [],
                "missing_position_dependency_ids": [],
                "mapping_exception_dependency_ids": [],
            },
        )
        dep_id = int(row["id"])
        family["dependency_ids"].append(dep_id)
        all_ids.append(dep_id)

        if source_pos >= target_pos:
            family["nonforward_dependency_ids"].append(dep_id)

        source_entry = entries.get((content_hash, source_pos))
        target_entry = entries.get((content_hash, target_pos))
        if source_entry is None or target_entry is None:
            family["missing_position_dependency_ids"].append(dep_id)
            continue

        source_ok = (
            source_entry["external_issue_identity_id"] is not None
            and (int(row["source_issue_id"]), int(source_entry["external_issue_identity_id"]))
            in confirmed_pairs
        )
        target_ok = (
            target_entry["external_issue_identity_id"] is not None
            and (int(row["target_issue_id"]), int(target_entry["external_issue_identity_id"]))
            in confirmed_pairs
        )
        if not (source_ok and target_ok):
            family["mapping_exception_dependency_ids"].append(dep_id)

    wolverine_positions: list[dict[str, Any]] = []
    for position in range(63, 67):
        entry = entries[(WOLVERINE_HASH, position)]
        endpoint_ids: set[int] = set()
        for row in rows:
            match = NOTE_RE.fullmatch(row["note"])
            if match is None or match.group(1) != WOLVERINE_HASH:
                continue
            source_pos, target_pos = int(match.group(2)), int(match.group(3))
            if source_pos == position:
                endpoint_ids.add(int(row["source_issue_id"]))
            if target_pos == position:
                endpoint_ids.add(int(row["target_issue_id"]))
        endpoint_evidence = [issues[issue_id] | {"issue_id": issue_id} for issue_id in sorted(endpoint_ids)]
        wolverine_positions.append(
            {
                "position": position,
                "cbl_series": entry["series_name"],
                "cbl_issue_number": entry["issue_number"],
                "volume_year": entry["volume_year"],
                "endpoint_evidence": endpoint_evidence,
            }
        )

    for content_hash, family in families.items():
        source_list = active_lists.get(content_hash)
        family["source_list"] = source_list
        family["dependency_count"] = len(family["dependency_ids"])
        family["id_manifest_sha256"] = hashlib.sha256(
            ",".join(str(value) for value in family["dependency_ids"]).encode()
        ).hexdigest()
        family["classification"] = "reading_plan_order"
        family["proof_passes"] = (
            source_list is not None
            and not family["nonforward_dependency_ids"]
            and not family["missing_position_dependency_ids"]
            and (
                not family["mapping_exception_dependency_ids"]
                or content_hash == WOLVERINE_HASH
            )
        )

    report = {
        "step": "14A",
        "user_id": user_id,
        "classification": "reading_plan_order",
        "total_dependency_count": len(all_ids),
        "family_count": len(families),
        "global_id_manifest_sha256": hashlib.sha256(
            ",".join(str(value) for value in all_ids).encode()
        ).hexdigest(),
        "families": sorted(families.values(), key=lambda item: item["content_hash"]),
        "wolverine_exception_corroboration": wolverine_positions,
    }
    if report["total_dependency_count"] != 101632:
        raise RuntimeError(
            f"Step 14A population drifted: expected 101632, got {report['total_dependency_count']}"
        )
    if report["family_count"] != 11:
        raise RuntimeError(
            f"Step 14A family count drifted: expected 11, got {report['family_count']}"
        )
    failed = [f["content_hash"] for f in report["families"] if not f["proof_passes"]]
    if failed:
        raise RuntimeError(f"Step 14A family proof failed: {failed}")
    return report


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Read-only Step 14A CBL-source dependency audit")
    parser.add_argument("--user-id", type=int, default=1)
    parser.add_argument("--output", type=Path, required=True)
    return parser


async def _main() -> int:
    args = _parser().parse_args()
    report = await build_report(args.user_id)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(
        json.dumps(
            {
                "step": report["step"],
                "total_dependency_count": report["total_dependency_count"],
                "family_count": report["family_count"],
                "global_id_manifest_sha256": report["global_id_manifest_sha256"],
            },
            indent=2,
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(_main()))
