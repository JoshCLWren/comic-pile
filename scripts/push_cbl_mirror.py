#!/usr/bin/env python3
"""Push a local CBL mirror to ComicPile through the service-authorized API."""

from __future__ import annotations

import argparse
from dataclasses import asdict
import json
import os
from pathlib import Path
import sys
from urllib import error, parse, request

from app.cbl_ingest import parse_cbl_mirror

DEFAULT_REPOSITORY = "JoshCLWren/CBL-ReadingLists"
DEFAULT_API_URL = "https://comic-pile.vercel.app/api/v1/cbl-sync"
BATCH_SIZE = 20


def _json_request(
    url: str,
    *,
    token: str,
    method: str = "GET",
    payload: dict | None = None,
) -> dict:
    """Call the CBL synchronization API and decode its JSON response."""
    data = None if payload is None else json.dumps(payload).encode()
    headers = {"X-CBL-Sync-Token": token}
    if data is not None:
        headers["Content-Type"] = "application/json"
    req = request.Request(url, data=data, headers=headers, method=method)
    try:
        with request.urlopen(req, timeout=60) as response:
            return json.loads(response.read().decode())
    except error.HTTPError as exc:
        body = exc.read().decode(errors="replace")
        raise RuntimeError(f"CBL sync API returned HTTP {exc.code}: {body}") from exc


def _parser() -> argparse.ArgumentParser:
    """Build command-line arguments."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("mirror_path", type=Path)
    parser.add_argument("--repository", default=DEFAULT_REPOSITORY)
    parser.add_argument("--revision-sha", required=True)
    parser.add_argument("--api-url", default=os.getenv("CBL_SYNC_API_URL", DEFAULT_API_URL))
    parser.add_argument("--force", action="store_true")
    return parser


def main() -> int:
    """Reconcile one local mirror revision through the deployed ComicPile API."""
    args = _parser().parse_args()
    if not args.mirror_path.is_dir():
        print(json.dumps({"error": "mirror_path_not_directory"}), file=sys.stderr)
        return 2
    token = os.getenv("CBL_SYNC_TOKEN", "").strip()
    if not token:
        print(json.dumps({"error": "CBL_SYNC_TOKEN_not_configured"}), file=sys.stderr)
        return 2

    source_url = f"{args.api_url.rstrip('/')}/source?" + parse.urlencode(
        {"repository": args.repository}
    )
    source = _json_request(source_url, token=token)
    if not args.force and source.get("revision_sha") == args.revision_sha:
        print(
            json.dumps(
                {
                    "repository": args.repository,
                    "revision_sha": args.revision_sha,
                    "skipped": True,
                    "reason": "revision_already_synchronized",
                },
                sort_keys=True,
            )
        )
        return 0

    parsed_lists, failures = parse_cbl_mirror(args.mirror_path)
    totals = {
        "inserted_lists": 0,
        "updated_lists": 0,
        "unchanged_lists": 0,
        "entries_written": 0,
    }
    for start in range(0, len(parsed_lists), BATCH_SIZE):
        batch = parsed_lists[start : start + BATCH_SIZE]
        result = _json_request(
            f"{args.api_url.rstrip('/')}/batch",
            token=token,
            method="POST",
            payload={
                "repository": args.repository,
                "revision_sha": args.revision_sha,
                "lists": [asdict(item) for item in batch],
            },
        )
        for key in totals:
            totals[key] += int(result.get(key, 0))

    finalize = _json_request(
        f"{args.api_url.rstrip('/')}/finalize",
        token=token,
        method="POST",
        payload={
            "repository": args.repository,
            "revision_sha": args.revision_sha,
            "active_paths": [item.source_path for item in parsed_lists],
            "protected_paths": [failure.source_path for failure in failures],
        },
    )
    output = {
        **totals,
        "deactivated_lists": int(finalize.get("deactivated_lists", 0)),
        "parsed_lists": len(parsed_lists),
        "parse_failures": [asdict(failure) for failure in failures],
        "repository": args.repository,
        "revision_sha": args.revision_sha,
        "skipped": False,
    }
    print(json.dumps(output, sort_keys=True))
    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(main())
