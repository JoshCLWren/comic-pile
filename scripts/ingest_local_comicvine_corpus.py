#!/usr/bin/env python3
"""Ingest a ComicPile-focused ComicVine corpus into the configured Postgres database.

The importer uses an assessed hydration JSONL as the canonical ComicPile issue mapping seed,
then optionally expands the corpus with complete seed volumes plus every issue sharing a
ComicVine story arc with those seed volumes. All provider metadata is preserved in
``external_identities.metadata_json``.
"""

from __future__ import annotations

import argparse
import json
import os
import sqlite3
from collections.abc import Iterable, Iterator
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit

import psycopg
from psycopg.types.json import Jsonb

ISSUE_JSON_FIELDS = (
    "character_credits",
    "person_credits",
    "team_credits",
    "location_credits",
    "story_arc_credits",
    "associated_images",
)
ISSUE_COLUMNS = (
    "id",
    "volume_id",
    "name",
    "issue_number",
    "cover_date",
    "store_date",
    "description",
    "image_url",
    "site_detail_url",
    *ISSUE_JSON_FIELDS,
)
VOLUME_COLUMNS = (
    "id",
    "name",
    "aliases",
    "start_year",
    "publisher_id",
    "count_of_issues",
    "description",
    "image_url",
    "site_detail_url",
)


def parse_args() -> argparse.Namespace:
    """Parse command-line arguments."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--hydration",
        type=Path,
        default=Path("comicvine-assessed-hydration.jsonl"),
        help="Assessed hydration JSONL (default: %(default)s)",
    )
    parser.add_argument(
        "--localcv",
        type=Path,
        default=Path(
            os.environ.get(
                "COMICPILE_COMICVINE_SQLITE_PATH",
                "/mnt/bigdata/downloads/localcvdb_20260109/localcv.db",
            )
        ),
        help="Read-only local ComicVine SQLite database",
    )
    parser.add_argument("--user-id", type=int, default=1)
    parser.add_argument(
        "--scope",
        choices=("hydrated", "seed-runs", "smart"),
        default="smart",
        help=(
            "hydrated: JSONL issues only; seed-runs: all issues in represented volumes; "
            "smart: seed runs plus issues sharing a story arc with a seed volume"
        ),
    )
    parser.add_argument(
        "--database-url",
        default=os.environ.get("DATABASE_URL"),
        help="Postgres URL (defaults to DATABASE_URL)",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Build and report the corpus without writing Postgres",
    )
    return parser.parse_args()


def psycopg_url(url: str) -> str:
    """Normalize SQLAlchemy-style Postgres URLs for psycopg."""
    return (
        url.replace("postgresql+asyncpg://", "postgresql://", 1)
        .replace("postgresql+psycopg://", "postgresql://", 1)
    )


def chunks(values: Iterable[int], size: int = 500) -> Iterator[list[int]]:
    """Yield stable chunks from an integer iterable."""
    items = list(values)
    for start in range(0, len(items), size):
        yield items[start : start + size]


def load_hydration(path: Path) -> tuple[list[dict[str, Any]], dict[int, dict[str, Any]]]:
    """Load assessed hydration rows and validate duplicate provider payloads."""
    if not path.is_file():
        raise SystemExit(f"Missing hydration file: {path}")

    rows: list[dict[str, Any]] = []
    provider_issues: dict[int, dict[str, Any]] = {}
    comicpile_issue_ids: set[int] = set()

    with path.open(encoding="utf-8") as handle:
        for line_number, line in enumerate(handle, 1):
            row = json.loads(line)
            cv = row["comicvine"]
            comicpile_issue_id = int(row["comicpile_issue_id"])
            provider_issue_id = int(cv["id"])

            if comicpile_issue_id in comicpile_issue_ids:
                raise SystemExit(
                    f"Duplicate ComicPile issue {comicpile_issue_id} at JSONL line {line_number}"
                )
            comicpile_issue_ids.add(comicpile_issue_id)

            previous = provider_issues.get(provider_issue_id)
            if previous is not None and previous != cv:
                raise SystemExit(f"Conflicting ComicVine payloads for issue {provider_issue_id}")
            provider_issues[provider_issue_id] = cv
            rows.append(row)

    return rows, provider_issues


def open_localcv(path: Path) -> sqlite3.Connection:
    """Open the local ComicVine snapshot read-only."""
    if not path.is_file():
        raise SystemExit(f"Missing local ComicVine database: {path}")
    connection = sqlite3.connect(f"file:{path}?mode=ro", uri=True)
    connection.row_factory = sqlite3.Row
    return connection


def parse_json_value(value: object) -> object:
    """Decode JSON text from the local ComicVine snapshot when needed.

    Args:
        value: Raw SQLite field value.

    Returns:
        The decoded JSON value when applicable, otherwise the original value.
    """
    if value is None or isinstance(value, (dict, list, int, float, bool)):
        return value
    if not isinstance(value, str):
        return value
    stripped = value.strip()
    if not stripped:
        return []
    try:
        return json.loads(stripped)
    except json.JSONDecodeError:
        return value


def local_issue_payload(row: sqlite3.Row) -> dict[str, Any]:
    """Convert one local ComicVine issue row to provider metadata JSON."""
    payload = {column: row[column] for column in ISSUE_COLUMNS}
    for field in ISSUE_JSON_FIELDS:
        payload[field] = parse_json_value(payload[field])
    return payload


def local_volume_payload(row: sqlite3.Row) -> dict[str, Any]:
    """Convert one local ComicVine volume row to provider metadata JSON."""
    payload = {column: row[column] for column in VOLUME_COLUMNS}
    payload["publisher_name"] = row["publisher_name"]
    return payload


def select_rows_by_ids(
    db: sqlite3.Connection,
    *,
    table: str,
    columns: tuple[str, ...],
    ids: set[int],
) -> Iterator[sqlite3.Row]:
    """Select local rows by primary-key set without exceeding SQLite parameter limits."""
    if not ids:
        return
    column_sql = ", ".join(columns)
    for part in chunks(sorted(ids)):
        placeholders = ",".join("?" for _ in part)
        yield from db.execute(
            f"SELECT {column_sql} FROM {table} WHERE id IN ({placeholders})",  # noqa: S608
            part,
        )


def issues_for_volumes(db: sqlite3.Connection, volume_ids: set[int]) -> Iterator[sqlite3.Row]:
    """Select all issue rows belonging to a set of ComicVine volumes."""
    column_sql = ", ".join(ISSUE_COLUMNS)
    for part in chunks(sorted(volume_ids)):
        placeholders = ",".join("?" for _ in part)
        yield from db.execute(
            f"SELECT {column_sql} FROM cv_issue WHERE volume_id IN ({placeholders})",  # noqa: S608
            part,
        )


def story_arc_ids(value: object) -> set[int]:
    """Extract stable ComicVine story-arc IDs from one relationship payload.

    Args:
        value: Raw or decoded ComicVine story-arc relationship payload.

    Returns:
        Stable integer ComicVine story-arc identifiers.
    """
    credits = parse_json_value(value)
    if not isinstance(credits, list):
        return set()
    result: set[int] = set()
    for credit in credits:
        if not isinstance(credit, dict) or credit.get("id") is None:
            continue
        try:
            result.add(int(credit["id"]))
        except (TypeError, ValueError):
            continue
    return result


def build_corpus(
    db: sqlite3.Connection,
    hydration_rows: list[dict[str, Any]],
    hydration_payloads: dict[int, dict[str, Any]],
    scope: str,
) -> tuple[dict[int, dict[str, Any]], dict[int, dict[str, Any]], set[int]]:
    """Build provider issue/series payloads for the requested corpus scope."""
    seed_volumes = {int(row["comicvine"]["volume_id"]) for row in hydration_rows}
    issue_payloads = dict(hydration_payloads)

    if scope in {"seed-runs", "smart"}:
        for row in issues_for_volumes(db, seed_volumes):
            issue_payloads[int(row["id"])] = local_issue_payload(row)

    if scope == "smart":
        seed_arcs: set[int] = set()
        for payload in issue_payloads.values():
            if int(payload["volume_id"]) in seed_volumes:
                seed_arcs.update(story_arc_ids(payload.get("story_arc_credits")))

        related_issue_ids: set[int] = set()
        related_volume_ids: set[int] = set()
        for row in db.execute(
            """
            SELECT id, volume_id, story_arc_credits
            FROM cv_issue
            WHERE story_arc_credits IS NOT NULL
              AND story_arc_credits <> ''
              AND story_arc_credits <> '[]'
              AND story_arc_credits <> 'null'
            """
        ):
            if story_arc_ids(row["story_arc_credits"]) & seed_arcs:
                related_issue_ids.add(int(row["id"]))
                related_volume_ids.add(int(row["volume_id"]))

        for row in select_rows_by_ids(
            db,
            table="cv_issue",
            columns=ISSUE_COLUMNS,
            ids=related_issue_ids,
        ):
            issue_payloads[int(row["id"])] = local_issue_payload(row)
        corpus_volumes = seed_volumes | related_volume_ids
    else:
        corpus_volumes = {int(payload["volume_id"]) for payload in issue_payloads.values()}

    volume_payloads: dict[int, dict[str, Any]] = {}
    for part in chunks(sorted(corpus_volumes)):
        placeholders = ",".join("?" for _ in part)
        query = f"""
            SELECT {", ".join(f"v.{column}" for column in VOLUME_COLUMNS)},
                   p.name AS publisher_name
            FROM cv_volume v
            LEFT JOIN cv_publisher p ON p.id = v.publisher_id
            WHERE v.id IN ({placeholders})
        """  # noqa: S608
        for row in db.execute(query, part):
            volume_payloads[int(row["id"])] = local_volume_payload(row)

    return issue_payloads, volume_payloads, seed_volumes


def approximate_payload_bytes(payloads: Iterable[dict[str, Any]]) -> int:
    """Return compact UTF-8 JSON size for reporting."""
    return sum(
        len(json.dumps(payload, separators=(",", ":"), ensure_ascii=False).encode("utf-8"))
        for payload in payloads
    )


def ingest(
    database_url: str,
    *,
    user_id: int,
    hydration_rows: list[dict[str, Any]],
    issue_payloads: dict[int, dict[str, Any]],
    volume_payloads: dict[int, dict[str, Any]],
) -> None:
    """Atomically ingest provider identities and canonical ComicPile mappings."""
    normalized_url = psycopg_url(database_url)
    host = urlsplit(normalized_url).hostname or "(unknown)"
    print(f"Target database host: {host}")
    print("Opening one atomic production transaction...")

    with psycopg.connect(normalized_url) as connection:
        with connection.transaction():
            with connection.cursor() as cursor:
                cursor.execute("SET LOCAL lock_timeout = '10s'")
                cursor.execute("SET LOCAL statement_timeout = '20min'")
                cursor.execute(
                    """
                    CREATE TEMP TABLE cv_issue_ingest (
                        external_id text PRIMARY KEY,
                        external_url text,
                        metadata_json jsonb NOT NULL
                    ) ON COMMIT DROP
                    """
                )
                cursor.execute(
                    """
                    CREATE TEMP TABLE cv_series_ingest (
                        external_id text PRIMARY KEY,
                        external_url text,
                        metadata_json jsonb NOT NULL
                    ) ON COMMIT DROP
                    """
                )
                cursor.execute(
                    """
                    CREATE TEMP TABLE cv_mapping_ingest (
                        issue_id integer PRIMARY KEY,
                        thread_id integer NOT NULL,
                        match_method text NOT NULL,
                        cv_issue_id text NOT NULL,
                        cv_volume_id text NOT NULL
                    ) ON COMMIT DROP
                    """
                )

                with cursor.copy(
                    "COPY cv_issue_ingest (external_id, external_url, metadata_json) FROM STDIN"
                ) as copy:
                    for external_id, payload in issue_payloads.items():
                        copy.write_row(
                            (
                                str(external_id),
                                payload.get("site_detail_url"),
                                Jsonb(payload),
                            )
                        )

                with cursor.copy(
                    "COPY cv_series_ingest (external_id, external_url, metadata_json) FROM STDIN"
                ) as copy:
                    for external_id, payload in volume_payloads.items():
                        copy.write_row(
                            (
                                str(external_id),
                                payload.get("site_detail_url"),
                                Jsonb(payload),
                            )
                        )

                with cursor.copy(
                    """
                    COPY cv_mapping_ingest (
                        issue_id,
                        thread_id,
                        match_method,
                        cv_issue_id,
                        cv_volume_id
                    ) FROM STDIN
                    """
                ) as copy:
                    for row in hydration_rows:
                        cv = row["comicvine"]
                        copy.write_row(
                            (
                                int(row["comicpile_issue_id"]),
                                int(row["comicpile_thread_id"]),
                                row["match_method"],
                                str(cv["id"]),
                                str(cv["volume_id"]),
                            )
                        )

                cursor.execute(
                    """
                    SELECT s.issue_id, s.thread_id
                    FROM cv_mapping_ingest s
                    LEFT JOIN issues i ON i.id = s.issue_id
                    LEFT JOIN threads t ON t.id = i.thread_id
                    WHERE i.id IS NULL
                       OR i.thread_id <> s.thread_id
                       OR t.user_id <> %s
                    LIMIT 20
                    """,
                    (user_id,),
                )
                invalid_ownership = cursor.fetchall()
                if invalid_ownership:
                    raise RuntimeError(
                        "ComicPile issue ownership/thread mismatch: " f"{invalid_ownership}"
                    )

                cursor.execute(
                    """
                    SELECT s.issue_id, s.cv_issue_id, e.external_id
                    FROM cv_mapping_ingest s
                    JOIN issue_external_identity_mappings m
                      ON m.issue_id = s.issue_id
                     AND m.status = 'confirmed'
                    JOIN external_identities e
                      ON e.id = m.external_identity_id
                     AND e.provider = 'comicvine'
                     AND e.entity_type = 'issue'
                    WHERE e.external_id <> s.cv_issue_id
                    LIMIT 20
                    """
                )
                conflicts = cursor.fetchall()
                if conflicts:
                    raise RuntimeError(f"Confirmed ComicVine identity conflicts: {conflicts}")

                cursor.execute(
                    """
                    INSERT INTO external_identities (
                        provider,
                        entity_type,
                        external_id,
                        external_url,
                        metadata_json,
                        created_at,
                        updated_at
                    )
                    SELECT
                        'comicvine',
                        'issue',
                        external_id,
                        external_url,
                        metadata_json::json,
                        now(),
                        now()
                    FROM cv_issue_ingest
                    ON CONFLICT (provider, entity_type, external_id)
                    DO UPDATE SET
                        external_url = EXCLUDED.external_url,
                        metadata_json = EXCLUDED.metadata_json,
                        updated_at = now()
                    """
                )

                cursor.execute(
                    """
                    INSERT INTO external_identities (
                        provider,
                        entity_type,
                        external_id,
                        external_url,
                        metadata_json,
                        created_at,
                        updated_at
                    )
                    SELECT
                        'comicvine',
                        'series',
                        external_id,
                        external_url,
                        metadata_json::json,
                        now(),
                        now()
                    FROM cv_series_ingest
                    ON CONFLICT (provider, entity_type, external_id)
                    DO UPDATE SET
                        external_url = EXCLUDED.external_url,
                        metadata_json = EXCLUDED.metadata_json,
                        updated_at = now()
                    """
                )

                cursor.execute(
                    """
                    INSERT INTO issue_external_identity_mappings (
                        issue_id,
                        external_identity_id,
                        status,
                        evidence_source,
                        confidence,
                        rejection_reason,
                        evidence_json,
                        created_at,
                        updated_at
                    )
                    SELECT
                        s.issue_id,
                        e.id,
                        'confirmed',
                        'localcv_assessment',
                        CASE WHEN s.match_method = 'explicit_issue_mapping' THEN 1.0 ELSE 0.95 END,
                        NULL,
                        json_build_object(
                            'match_method', s.match_method,
                            'source', 'comicvine-assessed-hydration.jsonl',
                            'rich_metadata_ingested', true
                        ),
                        now(),
                        now()
                    FROM cv_mapping_ingest s
                    JOIN external_identities e
                      ON e.provider = 'comicvine'
                     AND e.entity_type = 'issue'
                     AND e.external_id = s.cv_issue_id
                    ON CONFLICT (issue_id, external_identity_id)
                    DO UPDATE SET
                        status = 'confirmed',
                        evidence_source = 'localcv_assessment',
                        confidence = GREATEST(
                            COALESCE(issue_external_identity_mappings.confidence, 0),
                            EXCLUDED.confidence
                        ),
                        rejection_reason = NULL,
                        evidence_json = (
                            issue_external_identity_mappings.evidence_json::jsonb
                            || EXCLUDED.evidence_json::jsonb
                        )::json,
                        updated_at = now()
                    """
                )

                cursor.execute(
                    """
                    INSERT INTO thread_external_series_mappings (
                        thread_id,
                        external_identity_id,
                        status,
                        evidence_source,
                        confidence,
                        created_at,
                        updated_at
                    )
                    SELECT DISTINCT
                        s.thread_id,
                        e.id,
                        'confirmed',
                        'derived_from_confirmed_issue_identity',
                        1.0,
                        now(),
                        now()
                    FROM cv_mapping_ingest s
                    JOIN external_identities e
                      ON e.provider = 'comicvine'
                     AND e.entity_type = 'series'
                     AND e.external_id = s.cv_volume_id
                    ON CONFLICT (thread_id, external_identity_id)
                    DO UPDATE SET
                        status = 'confirmed',
                        evidence_source = 'derived_from_confirmed_issue_identity',
                        confidence = 1.0,
                        updated_at = now()
                    """
                )

                cursor.execute(
                    """
                    SELECT count(*)
                    FROM cv_issue_ingest source
                    JOIN external_identities target
                      ON target.provider = 'comicvine'
                     AND target.entity_type = 'issue'
                     AND target.external_id = source.external_id
                    WHERE target.metadata_json::jsonb = source.metadata_json
                    """
                )
                exact_issue_payloads = int(cursor.fetchone()[0])
                if exact_issue_payloads != len(issue_payloads):
                    raise RuntimeError(
                        "Issue metadata verification failed: "
                        f"{exact_issue_payloads}/{len(issue_payloads)} exact"
                    )

                cursor.execute(
                    """
                    SELECT count(*)
                    FROM cv_series_ingest source
                    JOIN external_identities target
                      ON target.provider = 'comicvine'
                     AND target.entity_type = 'series'
                     AND target.external_id = source.external_id
                    WHERE target.metadata_json::jsonb = source.metadata_json
                    """
                )
                exact_series_payloads = int(cursor.fetchone()[0])
                if exact_series_payloads != len(volume_payloads):
                    raise RuntimeError(
                        "Series metadata verification failed: "
                        f"{exact_series_payloads}/{len(volume_payloads)} exact"
                    )

                cursor.execute(
                    """
                    SELECT count(*)
                    FROM cv_mapping_ingest s
                    JOIN issue_external_identity_mappings m
                      ON m.issue_id = s.issue_id
                     AND m.status = 'confirmed'
                    JOIN external_identities e
                      ON e.id = m.external_identity_id
                     AND e.provider = 'comicvine'
                     AND e.entity_type = 'issue'
                     AND e.external_id = s.cv_issue_id
                    """
                )
                exact_mappings = int(cursor.fetchone()[0])
                if exact_mappings != len(hydration_rows):
                    raise RuntimeError(
                        "ComicPile mapping verification failed: "
                        f"{exact_mappings}/{len(hydration_rows)}"
                    )

                cursor.execute(
                    """
                    SELECT count(*)
                    FROM (
                        SELECT DISTINCT s.thread_id, s.cv_volume_id
                        FROM cv_mapping_ingest s
                    ) source
                    JOIN external_identities e
                      ON e.provider = 'comicvine'
                     AND e.entity_type = 'series'
                     AND e.external_id = source.cv_volume_id
                    JOIN thread_external_series_mappings mapping
                      ON mapping.thread_id = source.thread_id
                     AND mapping.external_identity_id = e.id
                     AND mapping.status = 'confirmed'
                    """
                )
                thread_series_mappings = int(cursor.fetchone()[0])

                print("Verified before commit:")
                print(f"  exact issue payloads: {exact_issue_payloads:,}")
                print(f"  exact series payloads: {exact_series_payloads:,}")
                print(f"  ComicPile issue mappings: {exact_mappings:,}")
                print(f"  thread -> series mappings: {thread_series_mappings:,}")


def main() -> None:
    """Build the corpus and ingest it into Postgres."""
    args = parse_args()
    hydration_rows, hydration_payloads = load_hydration(args.hydration)
    seed_volumes = {int(row["comicvine"]["volume_id"]) for row in hydration_rows}

    if args.scope == "hydrated":
        issue_payloads = hydration_payloads
        volume_payloads: dict[int, dict[str, Any]] = {}
        if args.localcv.is_file():
            with open_localcv(args.localcv) as localcv:
                issue_payloads, volume_payloads, _ = build_corpus(
                    localcv,
                    hydration_rows,
                    hydration_payloads,
                    args.scope,
                )
    else:
        with open_localcv(args.localcv) as localcv:
            issue_payloads, volume_payloads, seed_volumes = build_corpus(
                localcv,
                hydration_rows,
                hydration_payloads,
                args.scope,
            )

    issue_bytes = approximate_payload_bytes(issue_payloads.values())
    volume_bytes = approximate_payload_bytes(volume_payloads.values())
    print(f"Hydrated ComicPile mappings: {len(hydration_rows):,}")
    print(f"Seed ComicVine volumes: {len(seed_volumes):,}")
    print(f"Corpus issue identities: {len(issue_payloads):,}")
    print(f"Corpus series identities: {len(volume_payloads):,}")
    print(f"Provider JSON payload: {(issue_bytes + volume_bytes) / 1024 / 1024:.1f} MB")

    if args.dry_run:
        print("Dry run complete. No Postgres writes performed.")
        return
    if not args.database_url:
        raise SystemExit("DATABASE_URL is not set; pass --database-url or export DATABASE_URL")

    ingest(
        args.database_url,
        user_id=args.user_id,
        hydration_rows=hydration_rows,
        issue_payloads=issue_payloads,
        volume_payloads=volume_payloads,
    )
    print("DONE. ComicVine corpus committed successfully.")


if __name__ == "__main__":
    main()
