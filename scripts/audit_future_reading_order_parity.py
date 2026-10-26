"""Read-only Option E future-order parity audit. Exits 1 on unresolved edges."""

import argparse
import asyncio
import json

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine

from app.repositories.reading_shadow_repository import load_shadow_inputs
from app.services.reading_future_parity import HistoricalEdge, audit_future_parity
from app.services.reading_list_evaluator import ReadingSnapshot

SQL = """
SELECT d.id, d.source_issue_id, d.target_issue_id, d.origin, d.note
FROM dependencies d
JOIN issues s ON s.id=d.source_issue_id
JOIN issues t ON t.id=d.target_issue_id
JOIN threads st ON st.id=s.thread_id
JOIN threads tt ON tt.id=t.thread_id
WHERE st.user_id=:uid AND tt.user_id=:uid
AND s.status<>'read' AND t.status<>'read'
AND d.origin IS DISTINCT FROM 'reader'
AND (d.note IS NULL OR d.note NOT LIKE 'cbl-order:%')
ORDER BY d.id
"""


async def run(url: str, uid: int) -> dict:
    if not url.startswith("postgresql+asyncpg://") or uid < 1:
        raise ValueError("Specify an asyncpg URL and positive user ID")
    engine = create_async_engine(url, isolation_level="REPEATABLE READ")
    try:
        async with engine.connect() as conn:
            async with conn.begin():
                await conn.execute(text("SET TRANSACTION READ ONLY"))
                async with AsyncSession(bind=conn) as db:
                    data = await load_shadow_inputs(
                        db, uid, include_legacy_diagnostics=False,
                    )
                    rows = (await db.execute(
                        text(SQL), {"uid": uid},
                    )).mappings().all()
                    snapshot = ReadingSnapshot(
                        user_id=uid, threads=data.threads,
                        issues=data.issues, lists=data.lists,
                        prerequisites=data.prerequisites,
                        excluded_issue_ids=data.excluded_issue_ids,
                    )
                    checked = audit_future_parity(snapshot, tuple(
                        HistoricalEdge(r["id"], r["source_issue_id"],
                                       r["target_issue_id"], r["origin"],
                                       r["note"]) for r in rows
                    ))
                    return {
                        "user_id": uid,
                        "examined": checked.examined,
                        "implied": checked.implied,
                        "unresolved": [vars_edge(e) for e in checked.missing],
                        "status": "PASS" if checked.safe_to_certify else "REVIEW_REQUIRED",
                    }
    finally:
        await engine.dispose()


def vars_edge(edge: HistoricalEdge) -> dict:
    return {
        "id": edge.dependency_id, "source": edge.source_issue_id,
        "target": edge.target_issue_id, "origin": edge.origin,
        "note": edge.note,
    }


def main() -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--database-url", required=True)
    p.add_argument("--user-id", required=True, type=int)
    a = p.parse_args()
    report = asyncio.run(run(a.database_url, a.user_id))
    print(json.dumps(report, indent=2))
    return int(report["status"] != "PASS")


if __name__ == "__main__":
    raise SystemExit(main())
