#!/usr/bin/env python3
"""Extract assessed ComicPile issue metadata from a local ComicVine snapshot.

Reads the temporary Neon assessment branch and a developer-local ComicVine SQLite
snapshot. Writes JSONL plus a report locally. It never mutates either database and
never calls the live ComicVine API.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import sqlite3
from collections import Counter
from pathlib import Path
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

import asyncpg

DEFAULT_LOCALCV = "/mnt/bigdata/downloads/localcvdb_20260109/localcv.db"
SAFE_MANUAL_KINDS = (
    "collection_alias",
    "creator_run_alias",
    "identity_clear",
    "partial_with_anomaly",
    "single_issue_from_volume",
    "single_issue_range",
    "source_stale",
    "special_label_match",
)


def parse_args() -> argparse.Namespace:
    """Parse command-line arguments."""
    parser = argparse.ArgumentParser()
    parser.add_argument("--scratch-database-url", default=os.getenv("SCRATCH_DATABASE_URL"))
    parser.add_argument("--localcv-db", default=DEFAULT_LOCALCV)
    parser.add_argument("--output", default="comicvine-assessed-hydration.jsonl")
    parser.add_argument("--report", default="comicvine-assessed-hydration-report.json")
    return parser.parse_args()


def normalize_asyncpg_url(url: str) -> str:
    """Normalize SQLAlchemy/libpq Postgres URLs for asyncpg."""
    normalized = url.replace("postgresql+asyncpg://", "postgresql://", 1).replace(
        "postgresql+psycopg://",
        "postgresql://",
        1,
    )
    parts = urlsplit(normalized)
    query = [(key, value) for key, value in parse_qsl(parts.query) if key != "channel_binding"]
    return urlunsplit((parts.scheme, parts.netloc, parts.path, urlencode(query), parts.fragment))


def decode(value: object) -> object:
    """Decode JSON-looking SQLite text while preserving ordinary strings."""
    if not isinstance(value, str):
        return value
    stripped = value.strip()
    if not stripped or stripped[0] not in "[{":
        return value
    try:
        return json.loads(stripped)
    except json.JSONDecodeError:
        return value


def normalize_sqlite_row(row: sqlite3.Row) -> dict[str, object]:
    """Convert a SQLite row to JSON-ready data."""
    return {key: decode(row[key]) for key in row.keys()}


def local_issue_by_id(db: sqlite3.Connection, issue_id: int) -> sqlite3.Row | None:
    """Return one local ComicVine issue by exact ID."""
    return db.execute("SELECT * FROM cv_issue WHERE id = ? LIMIT 1", (issue_id,)).fetchone()


def local_issue_by_volume_number(
    db: sqlite3.Connection,
    volume_id: int,
    issue_number: str,
) -> sqlite3.Row | None:
    """Return one local ComicVine issue by volume and issue number."""
    return db.execute(
        "SELECT * FROM cv_issue WHERE volume_id = ? AND issue_number = ? LIMIT 1",
        (volume_id, issue_number),
    ).fetchone()


async def fetch_assessment_rows(
    database_url: str,
) -> tuple[list[asyncpg.Record], list[tuple[str, list[asyncpg.Record]]]]:
    """Read exact issue mappings and safe volume mappings from the scratch branch."""
    connection = await asyncpg.connect(normalize_asyncpg_url(database_url))
    try:
        explicit = await connection.fetch(
            """
            SELECT m.comicpile_issue_id,
                   m.comicpile_thread_id AS thread_id,
                   t.title AS thread,
                   i.issue_number,
                   m.cv_issue_id AS comicvine_issue_id,
                   m.cv_volume_id AS comicvine_volume_id,
                   m.resolution_kind,
                   m.rationale
            FROM scratch_comicvine.issue_mapping_manual AS m
            JOIN public.issues AS i ON i.id = m.comicpile_issue_id
            JOIN public.threads AS t ON t.id = m.comicpile_thread_id
            ORDER BY m.comicpile_thread_id, i.position
            """
        )

        previously_hydrated = await connection.fetch(
            """
            SELECT h.thread_id,
                   h.thread,
                   h.comicvine_volume_id AS volume_id,
                   i.id AS comicpile_issue_id,
                   i.issue_number,
                   i.position
            FROM scratch_comicvine.hydrated_thread_summary AS h
            JOIN public.issues AS i ON i.thread_id = h.thread_id
            ORDER BY h.thread_id, i.position
            """
        )

        auto = await connection.fetch(
            """
            SELECT a.thread_id,
                   a.thread,
                   a.volume_id,
                   i.id AS comicpile_issue_id,
                   i.issue_number,
                   i.position
            FROM scratch_comicvine.auto_resolution AS a
            JOIN public.issues AS i ON i.thread_id = a.thread_id
            ORDER BY a.thread_id, i.position
            """
        )

        manual = await connection.fetch(
            """
            SELECT m.thread_id,
                   t.title AS thread,
                   m.volume_id,
                   m.resolution_kind,
                   m.rationale,
                   i.id AS comicpile_issue_id,
                   i.issue_number,
                   i.position
            FROM scratch_comicvine.manual_resolution AS m
            JOIN public.threads AS t ON t.id = m.thread_id
            JOIN public.issues AS i ON i.thread_id = m.thread_id
            WHERE m.volume_id IS NOT NULL
              AND m.resolution_kind = ANY($1::text[])
            ORDER BY m.thread_id, i.position
            """,
            list(SAFE_MANUAL_KINDS),
        )
    finally:
        await connection.close()

    return list(explicit), [
        ("previously_hydrated_volume", list(previously_hydrated)),
        ("auto_volume", list(auto)),
        ("manual_volume", list(manual)),
    ]


async def run() -> None:
    """Extract all safely assessed metadata available in the local snapshot."""
    args = parse_args()
    if not args.scratch_database_url:
        raise SystemExit("SCRATCH_DATABASE_URL is required")

    localcv_path = Path(args.localcv_db)
    if not localcv_path.is_file():
        raise SystemExit(f"localcv.db not found: {localcv_path}")

    explicit, volume_sources = await fetch_assessment_rows(args.scratch_database_url)

    sqlite_db = sqlite3.connect(f"file:{localcv_path}?mode=ro", uri=True)
    sqlite_db.row_factory = sqlite3.Row

    emitted_issue_ids: set[int] = set()
    output_rows: list[dict[str, object]] = []
    misses: list[dict[str, object]] = []
    methods: Counter[str] = Counter()

    try:
        for item in explicit:
            comicpile_issue_id = int(item["comicpile_issue_id"])
            comicvine_issue_id = int(item["comicvine_issue_id"])
            cv = local_issue_by_id(sqlite_db, comicvine_issue_id)
            if cv is None:
                misses.append(
                    {
                        "comicpile_issue_id": comicpile_issue_id,
                        "comicpile_thread_id": int(item["thread_id"]),
                        "thread": str(item["thread"]),
                        "comicpile_issue_number": str(item["issue_number"]),
                        "comicvine_issue_id": comicvine_issue_id,
                        "comicvine_volume_id": item["comicvine_volume_id"],
                        "match_method": "explicit_issue_mapping",
                        "reason": "explicit_issue_id_missing_from_snapshot",
                    }
                )
                continue

            emitted_issue_ids.add(comicpile_issue_id)
            methods["explicit_issue_mapping"] += 1
            output_rows.append(
                {
                    "comicpile_issue_id": comicpile_issue_id,
                    "comicpile_thread_id": int(item["thread_id"]),
                    "thread": str(item["thread"]),
                    "comicpile_issue_number": str(item["issue_number"]),
                    "match_method": "explicit_issue_mapping",
                    "match_evidence": {
                        "resolution_kind": str(item["resolution_kind"]),
                        "rationale": str(item["rationale"]),
                    },
                    "comicvine": normalize_sqlite_row(cv),
                }
            )

        for source, rows in volume_sources:
            for item in rows:
                comicpile_issue_id = int(item["comicpile_issue_id"])
                if comicpile_issue_id in emitted_issue_ids:
                    continue

                volume_id = int(item["volume_id"])
                issue_number = str(item["issue_number"])
                cv = local_issue_by_volume_number(sqlite_db, volume_id, issue_number)
                if cv is None:
                    misses.append(
                        {
                            "comicpile_issue_id": comicpile_issue_id,
                            "comicpile_thread_id": int(item["thread_id"]),
                            "thread": str(item["thread"]),
                            "comicpile_issue_number": issue_number,
                            "comicvine_volume_id": volume_id,
                            "match_method": source,
                            "reason": "issue_not_in_local_snapshot",
                        }
                    )
                    continue

                emitted_issue_ids.add(comicpile_issue_id)
                methods[source] += 1
                output_rows.append(
                    {
                        "comicpile_issue_id": comicpile_issue_id,
                        "comicpile_thread_id": int(item["thread_id"]),
                        "thread": str(item["thread"]),
                        "comicpile_issue_number": issue_number,
                        "match_method": source,
                        "comicvine": normalize_sqlite_row(cv),
                    }
                )
    finally:
        sqlite_db.close()

    output_rows.sort(
        key=lambda row: (int(row["comicpile_thread_id"]), int(row["comicpile_issue_id"]))
    )
    output_path = Path(args.output)
    with output_path.open("w", encoding="utf-8") as handle:
        for row in output_rows:
            handle.write(json.dumps(row, ensure_ascii=False, default=str) + "\n")

    report = {
        "hydrated_issue_rows": len(output_rows),
        "match_methods": dict(sorted(methods.items())),
        "local_snapshot_misses": len(misses),
        "live_comicvine_requests": 0,
        "output": str(output_path.resolve()),
        "misses": misses,
    }
    report_path = Path(args.report)
    report_path.write_text(
        json.dumps(report, indent=2, ensure_ascii=False, default=str) + "\n",
        encoding="utf-8",
    )
    print(
        json.dumps(
            {key: value for key, value in report.items() if key != "misses"},
            indent=2,
        )
    )


def main() -> None:
    """Run the async extractor."""
    asyncio.run(run())


if __name__ == "__main__":
    main()
