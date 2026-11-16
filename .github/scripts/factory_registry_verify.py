#!/usr/bin/env python3
"""Verify GitHub registry comment locators using the canonical trust policy."""
from __future__ import annotations

import argparse
import json
import sys

from factory_registry_ingest import flatten, marker_ids


def select(payload: object, worker: str, kind: str, required_id: str = "") -> str:
    comments = ([payload] if isinstance(payload, dict) else flatten(payload))
    valid = [
        int(item["id"]) for item in marker_ids(comments)
        if item["worker"] == worker and item["kind"] == kind
        and (not required_id or item["id"] == required_id)
    ]
    return str(max(valid)) if valid else ""


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("mode", choices=("find", "verify"))
    parser.add_argument("--worker", required=True)
    parser.add_argument("--kind", choices=("heartbeat", "attempt"), required=True)
    parser.add_argument("--id", default="")
    args = parser.parse_args()
    if not args.worker.isdecimal() or (args.id and not args.id.isdecimal()):
        parser.error("invalid worker or locator ID")
    payload = json.load(sys.stdin)
    print(select(payload, args.worker, args.kind, args.id if args.mode == "verify" else ""))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
