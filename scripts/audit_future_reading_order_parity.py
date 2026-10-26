"""Read-only Option E future-order parity audit. Exits 1 on unresolved edges."""

import argparse
import asyncio
import json

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine

from app.repositories.reading_shadow_repository import load_shadow_inputs
from app.services.reading_future_parity import HistoricalEdge, audit_future_parity
from app.services.reading_list_evaluator import ReadingSnapshot
from app.services.reading_partial_list_coverage import partial_strict_coverage

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
    """Load canonical and historical rows in one read-only owner transaction.

    This function connects to the PostgreSQL database using an async engine with
    REPEATABLE READ isolation, executes a read‑only transaction, loads the
    shadow inputs for the given user, runs the audit of future unread historical
    edges, and returns a structured JSON report.  The report includes:

    * ``examined`` – total number of historical edges considered (excluding
      excluded issues).
    * ``implied`` – number of edges that are implied by the canonical graph.
    * ``unresolved`` – list of edges that are missing from the canonical graph,
      each with source and target issue labels.
    * ``partial_strict_list_omissions`` – details of strict‑list omissions.
    * ``status`` – ``PASS`` if the audit is safe to certify and there are no
      partial strict‑list omissions, otherwise ``REVIEW_REQUIRED``.

    The function is intended for use by the CLI entry point ``main`` and by
    automated tests that need PostgreSQL coverage of the production path.
    """
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
                    omitted = partial_strict_coverage(snapshot)
                    issue_names = dict(data.issue_labels)
                    list_names = dict(data.list_labels)
                    return {
                        "user_id": uid,
                        "scope": "future_unread_historical_edges_and_strict_partial_threads",
                        "examined": checked.examined,
                        "implied": checked.implied,
                        "unresolved": [
                            {**vars_edge(e),
                             "source_label": issue_names.get(e.source_issue_id),
                             "target_label": issue_names.get(e.target_issue_id)}
                            for e in checked.missing
                        ],
                        "partial_strict_list_omissions": [
                            {"list_id": list_id, "list_name": list_names.get(list_id),
                             "issue_id": issue_id, "issue_label": issue_names.get(issue_id)}
                            for list_id, issue_id in omitted
                        ],
                        "status": (
                            "PASS" if checked.safe_to_certify and not omitted
                            else "REVIEW_REQUIRED"
                        ),
                    }
    finally:
        await engine.dispose()


def vars_edge(edge: HistoricalEdge) -> dict:
    """Serialize one unresolved historical edge without changing it.

    Returns a dictionary with the edge's identifier, source and target issue IDs,
    origin, and note.  This helper is used by the CLI report to produce JSON
    output that is easy to parse.
    """
    return {
        "id": edge.dependency_id, "source": edge.source_issue_id,
        "target": edge.target_issue_id, "origin": edge.origin,
        "note": edge.note,
    }


def main() -> int:
    """Exit nonzero unless the historical unread-edge audit passes.

    Parses command-line arguments for ``--database-url`` and ``--user-id``,
    runs the ``run`` coroutine, prints the JSON report, and exits with a
    status code indicating success (0) or failure (non‑zero).  The exit code
    is useful for CI pipelines to detect audit failures automatically.
    """
    p = argparse.ArgumentParser()
    p.add_argument("--database-url", required=True)
    p.add_argument("--user-id", required=True, type=int)
    a = p.parse_args()
    report = asyncio.run(run(a.database_url, a.user_id))
    print(json.dumps(report, indent=2))
    return int(report["status"] != "PASS")


if __name__ == "__main__":
    raise SystemExit(main())
