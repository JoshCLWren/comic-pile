"""Read-only Option E future-order parity audit. Exits 1 on unresolved edges."""

import argparse
import asyncio
import json

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine

from app.repositories.reading_shadow_repository import load_shadow_inputs
from app.services.reading_future_parity import HistoricalEdge, audit_future_parity
from app.services.reading_list_evaluator import ReadingSnapshot
from app.services.reading_partial_list_coverage import (
    classify_partial_strict_coverage,
    partial_strict_coverage,
    superseded_converted_edge,
)

SQL = """
SELECT d.id, d.source_issue_id, d.target_issue_id, d.origin, d.note, d.classification
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

OLD_PLAN_SQL = """
SELECT s.custom_cbl_list_id AS list_id, p.id AS plan_id, pi.lane_id, pi.issue_id, pi.display_position
FROM reading_plan_sources s
JOIN continuity_plans p ON p.id=s.plan_id AND p.user_id=:uid
JOIN reading_plan_issues pi ON pi.plan_id=p.id
WHERE s.custom_cbl_list_id IS NOT NULL
ORDER BY s.custom_cbl_list_id, p.id, pi.lane_id, pi.display_position
"""


async def run(url: str, uid: int) -> dict:
    """Run the read-only future-order parity audit for one user.

    Connects to the PostgreSQL database using an async engine with
    REPEATABLE READ isolation, executes a read-only transaction, loads the
    shadow inputs for the given user, runs the audit of future unread
    historical edges, and returns a structured JSON report.

    Args:
        url: Async PostgreSQL connection URL (must start with
            ``postgresql+asyncpg://``).
        uid: Positive reader user ID whose edges are audited.

    Returns:
        A dictionary with the audit report: ``user_id``, ``scope``,
        ``examined``, ``implied``, ``excluded``, ``unresolved``,
        ``contradicted``, ``partial_strict_list_omissions``, and ``status``
        (``PASS`` or ``REVIEW_REQUIRED``). ``examined`` counts every
        historical edge; ``implied`` + ``unresolved`` + ``contradicted``
        + ``excluded`` equals ``examined``. Opposing historical edges remain
        diagnostic and cannot automatically replace the canonical order.

    Raises:
        ValueError: If the URL is not an asyncpg URL or ``uid`` is not positive.
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
                                       r["note"], r["classification"]) for r in rows
                    ))
                    omitted = partial_strict_coverage(snapshot)
                    old_rows = (await db.execute(
                        text(OLD_PLAN_SQL), {"uid": uid},
                    )).mappings().all()
                    plan_positions: dict[
                        int, dict[tuple[int, str], dict[int, int]]
                    ] = {}
                    for old_row in old_rows:
                        list_lanes = plan_positions.setdefault(old_row["list_id"], {})
                        lane = (old_row["plan_id"], old_row["lane_id"])
                        list_lanes.setdefault(lane, {})[
                            old_row["issue_id"]
                        ] = old_row["display_position"]
                    scoped, unresolved_omissions = classify_partial_strict_coverage(
                        snapshot, omitted,
                        {
                            list_id: frozenset(
                                issue_id
                                for lane in lanes.values()
                                for issue_id in lane
                            )
                            for list_id, lanes in plan_positions.items()
                        },
                    )
                    superseded = tuple(
                        edge for edge in checked.contradicted
                        if edge.origin == "converted" and edge.classification == "C"
                        and superseded_converted_edge(
                            edge.source_issue_id, edge.target_issue_id,
                            snapshot, plan_positions,
                        )
                    )
                    superseded_ids = {edge.dependency_id for edge in superseded}
                    unreviewed_contradictions = tuple(
                        edge for edge in checked.contradicted
                        if edge.dependency_id not in superseded_ids
                    )
                    issue_names = dict(data.issue_labels)
                    list_names = dict(data.list_labels)
                    return {
                        "user_id": uid,
                        "scope": "future_unread_historical_edges_and_strict_partial_threads",
                        "examined": checked.examined,
                        "implied": checked.implied,
                        "excluded": [
                            {**vars_edge(e),
                             "reason": _excluded_reason(
                                 e, snapshot.excluded_issue_ids)}
                            for e in checked.excluded
                        ],
                        "unresolved": [
                            {**vars_edge(e),
                             "source_label": issue_names.get(e.source_issue_id),
                             "target_label": issue_names.get(e.target_issue_id)}
                            for e in checked.missing
                        ],
                        "contradicted": [
                            {**vars_edge(e),
                             "reason": "reversed by current canonical order",
                             "source_label": issue_names.get(e.source_issue_id),
                             "target_label": issue_names.get(e.target_issue_id)}
                            for e in checked.contradicted
                        ],
                        "superseded_historical_edges": [
                            {**vars_edge(e), "reason": "old generated ordering superseded by current owned strict list"}
                            for e in superseded
                        ],
                        "unresolved_contradictions": [
                            vars_edge(e) for e in unreviewed_contradictions
                        ],
                        "scoped_strict_list_omissions": [
                            {"list_id": list_id, "issue_id": issue_id, "reason": reason}
                            for list_id, issue_id, reason in scoped
                        ],
                        "unresolved_strict_list_omissions": [
                            {"list_id": list_id, "issue_id": issue_id}
                            for list_id, issue_id in unresolved_omissions
                        ],
                        "partial_strict_list_omissions": [
                            {"list_id": list_id, "list_name": list_names.get(list_id),
                             "issue_id": issue_id, "issue_label": issue_names.get(issue_id)}
                            for list_id, issue_id in omitted
                        ],
                        "status": (
                            "PASS" if not checked.missing and not unreviewed_contradictions
                            and not unresolved_omissions
                            else "REVIEW_REQUIRED"
                        ),
                    }
    finally:
        await engine.dispose()


def vars_edge(edge: HistoricalEdge) -> dict:
    """Serialize one unresolved historical edge without changing it.

    Args:
        edge: The historical edge to serialize.

    Returns:
        A dictionary with the edge's identifier, source and target issue IDs,
        origin, and note. Used by the CLI report to produce parseable JSON
        output.
    """
    return {
        "id": edge.dependency_id, "source": edge.source_issue_id,
        "target": edge.target_issue_id, "origin": edge.origin,
        "note": edge.note, "classification": edge.classification,
    }


def _excluded_reason(edge: HistoricalEdge, excluded_ids: frozenset[int]) -> str:
    """Explain why a historical edge with an excluded endpoint is inactive.

    Args:
        edge: The historical edge being classified as excluded.
        excluded_ids: Issue IDs the reader has excluded from reading history.

    Returns:
        A short sentence naming the excluded endpoint so operators can tell an
        intentional exclusion from a lost result.
    """
    if edge.source_issue_id in excluded_ids:
        return f"source issue {edge.source_issue_id} excluded from reading history"
    return f"target issue {edge.target_issue_id} excluded from reading history"


def main() -> int:
    """Exit nonzero unless the historical unread-edge audit passes.

    Parses command-line arguments for ``--database-url`` and ``--user-id``,
    runs the ``run`` coroutine, prints the JSON report, and exits with a
    status code indicating success (0) or failure (non-zero). The exit code
    is useful for CI pipelines to detect audit failures automatically.

    Returns:
        0 when the audit status is ``PASS``, non-zero otherwise.
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
