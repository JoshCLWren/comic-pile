"""Integrity checks for the persisted Step 14B production evidence."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import cast

ROOT = Path(__file__).resolve().parents[1]
EVIDENCE = ROOT / "docs/recovery/step14b-generated-compatibility-evidence.json"


def _manifest_sha256(ids: list[int]) -> str:
    """Return the audit's deterministic dependency-ID fingerprint."""
    return hashlib.sha256(",".join(str(value) for value in ids).encode()).hexdigest()


def test_step14b_evidence_reconciles_exactly() -> None:
    """Every classified ID is unique, fingerprinted, and accounted for once."""
    report = cast(dict[str, object], json.loads(EVIDENCE.read_text(encoding="utf-8")))
    families = cast(list[dict[str, object]], report["families"])
    unnamed, ultimate = families
    unnamed_ids = cast(list[int], unnamed["dependency_ids"])
    ultimate_ids = cast(list[int], ultimate["dependency_ids"])
    combined_ids = sorted(unnamed_ids + ultimate_ids)

    assert len(unnamed_ids) == len(set(unnamed_ids)) == 1228
    assert len(ultimate_ids) == len(set(ultimate_ids)) == 73
    assert set(unnamed_ids).isdisjoint(ultimate_ids)
    assert unnamed["id_manifest_sha256"] == _manifest_sha256(unnamed_ids)
    assert ultimate["id_manifest_sha256"] == _manifest_sha256(ultimate_ids)
    assert report["total_manifest_sha256"] == _manifest_sha256(combined_ids)
    assert report["total_dependency_count"] == len(combined_ids) == 1301


def test_step14b_evidence_is_fail_closed_and_scope_complete() -> None:
    """Both proven families classify cleanly without authorizing later work."""
    report = cast(dict[str, object], json.loads(EVIDENCE.read_text(encoding="utf-8")))
    families = cast(list[dict[str, object]], report["families"])
    unnamed, ultimate = families
    ultimate_ids = set(cast(list[int], ultimate["dependency_ids"]))
    adjacency_ids = set(cast(list[int], ultimate["strict_adjacency_duplicate_ids"]))
    bridge_ids = set(cast(list[int], ultimate["historical_gap_bridge_ids"]))

    assert unnamed["proof_passes"] is True
    assert ultimate["proof_passes"] is True
    assert unnamed["global_exceptions"] == []
    assert ultimate["global_exceptions"] == []
    assert report["reading_plan_order_count"] == 1301
    assert report["standalone_prerequisite_count"] == 0
    assert report["needs_review_count"] == 0
    assert report["needs_review_dependency_ids"] == []
    assert report["family_overlap_dependency_ids"] == []
    assert len(adjacency_ids) == 55
    assert len(bridge_ids) == 18
    assert adjacency_ids.isdisjoint(bridge_ids)
    assert adjacency_ids | bridge_ids == ultimate_ids
    assert report["migration_authorized"] is False
    assert report["step_14a_repeated"] is False
    assert report["step_14c_included"] is False
