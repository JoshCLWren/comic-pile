#!/usr/bin/env python3
"""Issue-state precedence and blocked-label skip for factory reconciliation."""

from __future__ import annotations

import argparse
import json
from collections.abc import Iterable, Mapping
from pathlib import Path
from typing import Any

from factory_work_policy import BLOCKED_LABELS, is_manual_only


def stage_from_trusted_prs(records: Iterable[Mapping[str, Any]]) -> str:
    """Derive issue lifecycle from trusted canonical PR history.

    Durable merged provenance permanently wins. Without a merged PR, any open
    trusted canonical PR owns the lifecycle. Only when every trusted attempt is
    closed unmerged does the issue return to claimable backlog state.
    """
    trusted = [record for record in records if bool(record.get("trusted"))]
    if any(bool(record.get("merged")) for record in trusted):
        return "factory:ready"
    if any(str(record.get("state") or "").upper() == "OPEN" for record in trusted):
        return "factory:review"
    return "claimable"


def issue_labels_block_reconciliation(labels: Iterable[str]) -> bool:
    """Return whether claim policy forbids rewriting this issue's factory labels.

    Reuses ``BLOCKED_LABELS`` from factory work policy so the scheduled
    reconciler leaves ``ralph-status:blocked`` (and the rest of that set)
    alone instead of restoring ``factory`` + ``factory:unowned``.
    """
    return bool(set(labels) & BLOCKED_LABELS)


def body_blocks_reconciliation(body: str | None) -> bool:
    """Return whether a body forbids rewriting this target's factory labels.

    Mirrors ``stale_pr_decay.process_stale_prs``: a standalone
    ``<!-- factory-execution:manual-only -->`` directive is an operator hold.
    ``gh issue list --label factory`` includes pull requests, so the scheduled
    reconciler must skip those PR bodies the same way stale-expiration does.
    """
    return is_manual_only(body)


def _label_names(decoded: object) -> list[str]:
    """Return string label names from a decoded JSON labels payload."""
    if not isinstance(decoded, list):
        raise TypeError("labels JSON must decode to a list")
    return [item for item in decoded if isinstance(item, str)]


def main() -> int:
    """Print derived issue stage, or whether labels block reconciliation."""
    parser = argparse.ArgumentParser()
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--records-json")
    mode.add_argument("--blocked-by-labels-json")
    mode.add_argument("--blocked-by-body-file")
    args = parser.parse_args()
    if args.blocked_by_labels_json is not None:
        try:
            labels = _label_names(json.loads(args.blocked_by_labels_json))
        except (TypeError, json.JSONDecodeError) as exc:
            parser.error(f"--blocked-by-labels-json must decode to a list: {exc}")
        print("blocked" if issue_labels_block_reconciliation(labels) else "ok")
        return 0
    if args.blocked_by_body_file is not None:
        body = Path(args.blocked_by_body_file).read_text(encoding="utf-8")
        print("blocked" if body_blocks_reconciliation(body) else "ok")
        return 0
    if args.records_json is None:
        parser.error("--records-json is required")
    records = json.loads(args.records_json)
    if not isinstance(records, list):
        parser.error("--records-json must decode to a list")
    print(stage_from_trusted_prs(records))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
