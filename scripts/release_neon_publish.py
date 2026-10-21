#!/usr/bin/env python3
"""Publish a trusted, staged Release Writer record directly to production Neon.

This is run only in a separate GitHub Actions job after the model job has finished.
Never give its database connection string to OpenCode or a model-controlled process.
"""

from __future__ import annotations

import argparse
import json
import os
from datetime import datetime
from pathlib import Path

from psycopg import connect
from psycopg.types.json import Json

from scripts import release_reconcile, release_writer


class ReleaseIdentityConflict(ValueError):
    """An existing ledger row belongs to a different PR or merge SHA."""


def _matches_source(rows: list[tuple], pr_number: int, merge_sha: str) -> bool:
    """Require a unique, exact, two-key match; never overwrite a different source."""
    if len(rows) > 1:
        raise ReleaseIdentityConflict("PR and merge SHA identify different releases")
    if not rows:
        return False
    _, stored_pr, stored_sha = rows[0]
    if stored_pr != pr_number or stored_sha != merge_sha:
        raise ReleaseIdentityConflict("source PR or merge SHA is already bound elsewhere")
    return True


def _source_rows(cursor, payload: dict[str, object]) -> list[tuple]:
    return cursor.execute(
        """
        SELECT id, source_pr_number, source_merge_sha
        FROM releases
        WHERE source_repository = %s
          AND (source_pr_number = %s OR source_merge_sha = %s)
        FOR UPDATE
        """,
        (
            payload["source_repository"],
            payload["source_pr_number"],
            payload["source_merge_sha"],
        ),
    ).fetchall()


def publish_payload(connection, payload: dict[str, object]) -> str:
    """Insert at most one release, treating matching retries as no-ops.

    The two source-identity unique constraints enforce idempotence even across
    concurrent writers. The transaction never rewrites an existing release.
    """
    pr = payload["source_pr_number"]
    sha = payload["source_merge_sha"]
    assert isinstance(pr, int) and isinstance(sha, str)
    with connection.transaction():
        with connection.cursor() as cursor:
            if _matches_source(_source_rows(cursor, payload), pr, sha):
                return "already_present"

            inserted = cursor.execute(
                """
                INSERT INTO releases (
                    source_repository, source_pr_number, source_merge_sha, merged_at,
                    released_at, category, title, summary, body, visibility, status,
                    sort_order, provenance_json, created_at, updated_at
                ) VALUES (
                    %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, now(), now()
                )
                ON CONFLICT DO NOTHING
                RETURNING id
                """,
                (
                    payload["source_repository"],
                    pr,
                    sha,
                    payload["merged_at"],
                    payload["released_at"],
                    payload["category"],
                    payload["title"],
                    payload["summary"],
                    payload.get("body"),
                    payload["visibility"],
                    payload["status"],
                    payload["sort_order"],
                    Json(payload["provenance_json"]),
                ),
            ).fetchone()
            if inserted is not None:
                return "inserted"
            if _matches_source(_source_rows(cursor, payload), pr, sha):
                return "already_present"
            raise ReleaseIdentityConflict(
                "insert conflicted with an unexpected unique key; no changes committed"
            )


def _load_validated(path: Path, repository: str, pr_number: int) -> dict[str, object]:
    """Validate untrusted model output against the merged GitHub source."""
    if path.is_symlink() or not path.is_file() or path.stat().st_size > 32768:
        raise ValueError("invalid or oversized release candidate")
    raw = json.loads(path.read_text(encoding="utf-8"))
    payload = release_writer._validate_release(json.dumps(raw))
    if payload["source_repository"] != repository or payload["source_pr_number"] != pr_number:
        raise ReleaseIdentityConflict("candidate does not match requested source")

    source = release_reconcile._fetch_one(repository, pr_number)
    if payload["source_merge_sha"] != source.merge_commit_sha:
        raise ReleaseIdentityConflict("candidate SHA is not the merged PR commit")
    original_time = datetime.fromisoformat(source.merged_at.replace("Z", "+00:00"))
    candidate_time = datetime.fromisoformat(str(payload["merged_at"]).replace("Z", "+00:00"))
    if candidate_time != original_time:
        raise ReleaseIdentityConflict("candidate merged_at differs from GitHub")
    release_writer._validate_publish_grounding(payload)
    return payload


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--candidate", required=True, type=Path)
    parser.add_argument("--repository", required=True)
    parser.add_argument("--pr", required=True, type=int)
    args = parser.parse_args()
    if args.pr < 1:
        parser.error("--pr must be positive")
    # Validate before loading any database credential.
    payload = _load_validated(args.candidate, args.repository, args.pr)
    dsn = os.getenv("RELEASE_NEON_DATABASE_URL")
    if not dsn:
        raise RuntimeError("RELEASE_NEON_DATABASE_URL is required only for trusted publication")
    # Credentials must never appear in logs, model prompts, or artifacts.
    with connect(dsn, connect_timeout=15) as connection:
        outcome = publish_payload(connection, payload)
    print(json.dumps({"pr": args.pr, "outcome": outcome}, separators=(",", ":")))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
