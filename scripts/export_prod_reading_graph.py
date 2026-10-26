"""Export an anonymized production Option E graph with one read-only MVCC snapshot.

Only comic identities, reading status, list rules, and constraint relationships are
exported. No users, tokens, notes, ratings, activity timestamps, or connection
details are serialized. A regenerated export is byte-for-byte comparable.
"""

import argparse
import json
import os
from pathlib import Path

from sqlalchemy import text
from sqlalchemy.engine import make_url
from sqlalchemy.ext.asyncio import create_async_engine

SQL = """
WITH owned_threads AS MATERIALIZED (
  SELECT * FROM threads WHERE user_id = :owner_id
), owned_issues AS MATERIALIZED (
  SELECT i.* FROM issues i JOIN owned_threads t ON t.id=i.thread_id
), owned_lists AS MATERIALIZED (
  SELECT * FROM custom_cbl_lists WHERE user_id=:owner_id
), relevant_dependencies AS MATERIALIZED (
  SELECT d.* FROM dependencies d
  JOIN owned_issues s ON s.id=d.source_issue_id
  JOIN owned_issues t ON t.id=d.target_issue_id
), relevant_identifiers AS MATERIALIZED (
  SELECT m.external_identity_id AS id FROM thread_external_series_mappings m
    JOIN owned_threads t ON t.id=m.thread_id
  UNION SELECT continuing_external_identity_id FROM custom_cbl_overlap_decisions WHERE user_id=:owner_id
  UNION SELECT waiting_external_identity_id FROM custom_cbl_overlap_decisions WHERE user_id=:owner_id
  UNION SELECT cs.canonical_external_identity_id
    FROM catalog_series cs JOIN owned_threads t ON t.catalog_series_id=cs.id
  UNION SELECT ci.canonical_external_identity_id
    FROM catalog_issues ci JOIN owned_issues i ON i.catalog_issue_id=ci.id
)
SELECT jsonb_build_object(
 'schema_version', 1,
 'reader', 'anonymous-production-reader',
 'threads', (SELECT coalesce(jsonb_agg(jsonb_build_array(id,title,format,issues_remaining,total_issues,next_unread_issue_id,queue_position,status,is_blocked,queue_position_is_manual,queue_order_key,catalog_series_id) ORDER BY id),'[]'::jsonb) FROM owned_threads),
 'issues', (SELECT coalesce(jsonb_agg(jsonb_build_array(id,thread_id,issue_number,position,status,catalog_issue_id) ORDER BY id),'[]'::jsonb) FROM owned_issues),
 'lists', (SELECT coalesce(jsonb_agg(jsonb_build_array(id,name,mode) ORDER BY id),'[]'::jsonb) FROM owned_lists),
 'entries', (SELECT coalesce(jsonb_agg(jsonb_build_array(e.id,e.list_id,e.issue_id,e.position,e.gate,e.skipped,e.is_checkpoint,e.checkpoint_target_issue_ids) ORDER BY e.list_id,e.position),'[]'::jsonb) FROM custom_cbl_entries e JOIN owned_lists l ON l.id=e.list_id),
 'dependencies', (SELECT coalesce(jsonb_agg(jsonb_build_array(id,source_issue_id,target_issue_id,origin,classification,
  CASE WHEN note LIKE 'cbl-order:%' THEN 'generated' WHEN note IS NULL THEN 'unspecified' ELSE 'documented' END
  ) ORDER BY id),'[]'::jsonb) FROM relevant_dependencies WHERE origin IS NOT NULL OR note IS NULL OR note NOT LIKE 'cbl-order:%'),
 'exclusions', (SELECT coalesce(jsonb_agg(jsonb_build_array(id,provider,external_volume_id,thread_id,issue_id) ORDER BY id),'[]'::jsonb) FROM collection_exclusions WHERE user_id=:owner_id),
 'overlaps', (SELECT coalesce(jsonb_agg(jsonb_build_array(id,list_id,continuing_external_identity_id,waiting_external_identity_id) ORDER BY id),'[]'::jsonb) FROM custom_cbl_overlap_decisions WHERE user_id=:owner_id),
 'identities', (SELECT coalesce(jsonb_agg(jsonb_build_array(id,provider,entity_type,external_id) ORDER BY id),'[]'::jsonb) FROM external_identities WHERE id IN (SELECT id FROM relevant_identifiers)),
 'thread_identity_mappings', (SELECT coalesce(jsonb_agg(jsonb_build_array(m.id,m.thread_id,m.external_identity_id,m.status) ORDER BY m.id),'[]'::jsonb) FROM thread_external_series_mappings m JOIN owned_threads t ON t.id=m.thread_id),
 'catalog_series', (SELECT coalesce(jsonb_agg(jsonb_build_array(cs.id,cs.canonical_external_identity_id) ORDER BY cs.id),'[]'::jsonb) FROM catalog_series cs WHERE cs.id IN (SELECT catalog_series_id FROM owned_threads)),
 'catalog_issues', (SELECT coalesce(jsonb_agg(jsonb_build_array(ci.id,ci.canonical_external_identity_id,ci.catalog_series_id) ORDER BY ci.id),'[]'::jsonb) FROM catalog_issues ci WHERE ci.id IN (SELECT catalog_issue_id FROM owned_issues)),
 'inert_generated_dependencies', (SELECT jsonb_build_object('count',count(*),'fingerprint',md5(coalesce(string_agg(concat_ws(':',id,source_issue_id,target_issue_id),',' ORDER BY id),''))) FROM relevant_dependencies WHERE origin IS NULL AND note LIKE 'cbl-order:%')
) AS fixture"""


async def export(reader_id: int, database_url: str) -> dict[str, object]:
    """Read one reader's fixture under a database-enforced read-only snapshot.

    Args:
        reader_id: Production owner ID, used for filtering and never serialized.
        database_url: PostgreSQL URL provided only by the caller.

    Returns:
        Sanitized deterministic fixture structure.
    """
    url = make_url(database_url)
    if not url.drivername.startswith("postgresql"):
        raise ValueError("Only PostgreSQL snapshots are supported")
    engine = create_async_engine(url.set(drivername="postgresql+asyncpg"), pool_pre_ping=True)
    try:
        async with engine.connect() as connection:
            await connection.exec_driver_sql(
                "SET TRANSACTION ISOLATION LEVEL REPEATABLE READ, READ ONLY"
            )
            result = await connection.execute(text(SQL), {"owner_id": reader_id})
            value = result.scalar_one()
            await connection.rollback()
            return value
    finally:
        await engine.dispose()


def canonical_bytes(fixture: dict[str, object]) -> bytes:
    """Serialize without timestamps, passwords, or unstable key order."""
    return (json.dumps(fixture, sort_keys=True, separators=(",", ":"), ensure_ascii=False) + "\n").encode()


async def run() -> int:
    """Produce or compare the versioned anonymous production graph."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--reader-id", type=int, required=True)
    parser.add_argument("--output", type=Path, default=Path("tests/fixtures/production_reading_graph_v1.json"))
    parser.add_argument("--check", action="store_true")
    args = parser.parse_args()
    database_url = os.environ.get("DATABASE_URL")
    if not database_url:
        parser.error("DATABASE_URL is required; no connection information is stored")
    fixture = await export(args.reader_id, database_url)
    payload = canonical_bytes(fixture)
    if args.check:
        if not args.output.is_file() or args.output.read_bytes() != payload:
            print("Production reading graph changed. Review the fixture diff and authored intent.")
            return 1
        print("Production reading graph matches the committed fixture")
        return 0
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_bytes(payload)
    print(f"Wrote {args.output} ({len(fixture['issues'])} issues); inspect before committing")
    return 0


if __name__ == "__main__":
    import asyncio

    raise SystemExit(asyncio.run(run()))
